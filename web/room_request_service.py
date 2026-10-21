"""Student/faculty lifecycle and policy transactions; C++ owns room decisions."""

from datetime import datetime, timedelta, timezone, time
from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError

from .calendar_service import CalendarError, aware, epoch, local_instant, university_zone
from .persistence.models import (FacultyRoomApprover, LoginAccount, OrganizationUnit, Resource, Role, User,
    ROOM_CATEGORIES, RoomAccess, RoomClosure, RoomEvent, RoomInvitation, RoomOrganizerCommitment,
    RoomPolicy, RoomReservation, StudentRoomRequest)
from .persistence.repository import state_row
from .room_calendar import academic_room_intervals, assert_room_publication, room_snapshot, valid_approvers
from .notification_service import event_history, publish_event
from .waiting_list_state import close_waiting, guard_waiting, refresh_after_commit


class RoomRequestError(CalendarError):
    pass


ROOM_REASONS = {
    'ROOM_DISABLED': 'Rooms must be available and explicitly enabled for student use.',
    'NO_APPROVER': 'A room-owning faculty needs a valid designated administrative approver.',
    'ACCESS_RESTRICTED': 'The activity or organizer is not allowed by a room policy.',
    'INSUFFICIENT_CAPACITY': 'The total attendee count exceeds room capacity.',
    'MISSING_FACILITY': 'Required facilities are not present.',
    'UNRESOLVED_CALENDAR': 'Academic calendar dates are unresolved; an administrator must configure explicit period bindings.',
    'ROOM_BUSY': 'The room is allocated, reserved or closed during this interval.',
    'ORGANIZER_BUSY': 'The organizer has another commitment during this interval.',
    'NO_ELIGIBLE_ROOM': 'No eligible room is available for these requirements and time.',
}


class RoomRequestService:
    def __init__(self, database, gateway, strategy='best_fit'):
        if strategy not in {'best_fit', 'greedy'}:
            raise RoomRequestError('Configure a supported single-room selection strategy.')
        self.database, self.gateway, self.strategy = database, gateway, strategy

    def _user(self, session, actor, role=None):
        user = session.get(User, actor) if type(actor) is int and actor > 0 else None
        if user is None or user.status.casefold() != 'active' or (role and session.get(Role, user.primary_role_id).name != role):
            raise PermissionError('An active university identity with the required role is necessary.')
        return user

    def _admin(self, session, actor):
        user = self._user(session, actor)
        account = session.get(LoginAccount, actor)
        if not account or not account.enabled or not (account.administrator or session.get(Role, user.primary_role_id).name == 'Administrator'):
            raise PermissionError('University administration access is required for room configuration.')

    def _faculty(self, session, key):
        unit = session.get(OrganizationUnit, key) if type(key) is int and key > 0 else None
        if unit is None or unit.unit_type != 'Faculty':
            raise RoomRequestError('Select an explicitly configured faculty.')
        return unit

    def _room_manager(self, session, actor, room_id):
        user = self._user(session, actor)
        account = session.get(LoginAccount, actor)
        administrator = bool(account and account.enabled and (account.administrator or session.get(Role,user.primary_role_id).name == 'Administrator'))
        policy = session.get(RoomPolicy, room_id)
        if not administrator and (not policy or valid_approvers(session).get(policy.faculty_id) != actor):
            raise PermissionError('Only university administration or the current owning-faculty room manager can change closures.')

    def _validate(self, session, actor, values, invitees):
        self._user(session, actor, 'Student')
        if not isinstance(values, dict):
            raise RoomRequestError('Invalid room requirements.')
        duration, count = values.get('duration'), values.get('count')
        if type(duration) is not int or not 1 <= duration <= 1440 or type(count) is not int or not 1 <= count <= 2147483647:
            raise RoomRequestError('Enter duration 1-1440 minutes and a positive total attendee count.')
        if values.get('category') not in ROOM_CATEGORIES:
            raise RoomRequestError('Select a supported activity category.')
        features = values.get('features', [])
        if not isinstance(features, list) or len(features) > 3 or any(not isinstance(f, str) or f not in {'projector','whiteboard','computers'} for f in features) or len(set(features)) != len(features):
            raise RoomRequestError('Select distinct supported facilities.')
        if not isinstance(invitees, list) or len(invitees) > 100 or any(type(x) is not int or x <= 0 for x in invitees) or len(set(invitees)) != len(invitees):
            raise RoomRequestError('Select distinct professor invitees (at most 100).')
        participants = values.get('participantIds', [])
        if not isinstance(participants, list) or len(participants) > 100 or any(type(x) is not int or x <= 0 or x == actor for x in participants) or len(set(participants)) != len(participants):
            raise RoomRequestError('Select distinct registered students, excluding the organizer (at most 100).')
        for participant in participants:
            self._user(session, participant, 'Student')
        if count < len(invitees) + len(participants) + 1:
            raise RoomRequestError('Total attendees must include the organizer, registered students and invited professors.')
        for key, limit in (('purpose', 2000), ('description', 4000), ('club', 200), ('building', 200)):
            value = values.get(key, '')
            if not isinstance(value, str) or len(value) > limit or (key == 'purpose' and not value.strip()):
                raise RoomRequestError('Enter a purpose and bounded text fields.')
        for actor_id in invitees:
            self._user(session, actor_id, 'Instructor')
        if values.get('faculty') is not None:
            self._faculty(session, values['faculty'])
        start = aware(values.get('start'))
        epoch(start)
        end = start + timedelta(minutes=duration)
        epoch(end)
        return {**values, 'start': start, 'end': end, 'features': features}

    def _evaluate(self, actor, values, invitees, selected=None, exclude=None, alternatives=False):
        with self.database.transaction(read_only=True) as session:
            values = self._validate(session, actor, values, invitees)
            horizon_end = min(values['end'] + timedelta(days=7), datetime(2100,1,1,tzinfo=timezone.utc)) if alternatives else values['end']
            snapshot, revision = room_snapshot(session, actor, 'Student', values, (values['start'], horizon_end),
                self.strategy, selected, 'validate' if selected is not None else 'recommend', exclude)
        result, _ = self.gateway.execute_room(snapshot)
        return result, revision, snapshot, values

    def recommend(self, actor, values, invitees):
        if not isinstance(values, dict):
            raise RoomRequestError('Invalid room requirements.')
        if aware(values.get('start')) <= datetime.now(timezone.utc):
            raise RoomRequestError('Select a future dated interval.')
        result, revision, snapshot, _ = self._evaluate(actor, values, invitees, alternatives=True)
        by_room = {row['id']: row for row in snapshot['rooms']}
        with self.database.transaction(read_only=True) as session:
            faculties = {row.id: row.name for row in session.scalars(select(OrganizationUnit))}
        for key in ('candidates', 'alternatives'):
            for row in result[key]:
                source = by_room[row['roomId']]
                row.update(name=source['name'], type=source['type'], building=source['building'], facultyName=faculties.get(row['facultyId'], ''))
        return {**result, 'calendarRevision': revision, 'strategy': self.strategy,
                'messages': [ROOM_REASONS.get(key, key) for key in result['explanations']]}

    def _same_calendar(self, state, revision):
        if state.calendar_revision != revision:
            raise RoomRequestError('Availability or room policy changed. Refresh candidates and retry.')

    def _selected(self, session, snapshot, room_id):
        row = next((item for item in snapshot['rooms'] if item['id'] == room_id), None)
        if row is None:
            raise RoomRequestError('Select a system-verified room.')
        policy = session.get(RoomPolicy, room_id)
        approver = valid_approvers(session).get(row['facultyId'])
        if not policy or policy.faculty_id != row['facultyId'] or not approver or approver != row['approverId']:
            raise RoomRequestError('Room ownership or designated approval changed. Refresh the candidate.')
        return row['facultyId'], approver

    def _event(self, session, record, actor, message):
        publish_event(session, RoomEvent(request_id=record.id, actor_id=actor, revision=record.revision, message=message))

    def submit(self, actor, values, invitees, room_id, request_id=None, revision=None):
        if not isinstance(values, dict):
            raise RoomRequestError('Invalid room requirements.')
        if type(room_id) is not int or room_id <= 0:
            raise RoomRequestError('Choose a verified room candidate.')
        if aware(values.get('start')) <= datetime.now(timezone.utc):
            raise RoomRequestError('Select a future dated interval.')
        result, calendar_revision, snapshot, values = self._evaluate(actor, values, invitees, room_id, request_id)
        if not result['feasible']:
            raise RoomRequestError(ROOM_REASONS.get(result['reasonCode'], 'Selected room is no longer eligible. Refresh candidates.'))
        with self.database.transaction() as session:
            self._same_calendar(state_row(session, True), calendar_revision)
            self._validate(session, actor, values, invitees)
            faculty, approver = self._selected(session, snapshot, room_id)
            if request_id is not None:
                record = self._visible(session, request_id, actor)
                guard_waiting(session, room=request_id)
                if actor != record.organizer_id or record.revision != revision or record.status not in {'Pending Faculty Approval','Needs Revision','Rejected'}:
                    raise RoomRequestError('Only the organizer can revise this pending request. Cancel confirmed events and submit a new request.')
                record.revision += 1
                record.approved_revision = record.approved_by = None
                session.execute(delete(RoomInvitation).where(RoomInvitation.request_id == record.id))
            else:
                record = StudentRoomRequest(organizer_id=actor)
                session.add(record)
            self._store(session, record, values, invitees, room_id, faculty, approver)
            record.status, record.explanation = 'Pending Faculty Approval', result['candidates'][0]['reason']
            self._event(session,record,actor,'Submitted material revision for the room-owning faculty approval; no reservation. Professor invitations are optional.')
            return record.id

    def _store(self, session, record, values, invitees, room_id, faculty, approver):
        record.resource_id, record.faculty_id, record.approver_id = room_id, faculty, approver
        record.category, record.purpose = values['category'], values['purpose'].strip()
        record.description, record.club_affiliation = values.get('description',''), values.get('club','')
        record.attendee_count, record.required_features = values['count'], values['features']
        record.preferred_faculty_id, record.preferred_building = values.get('faculty'), values.get('building','')
        record.start_at, record.end_at, record.duration_minutes = values['start'], values['end'], values['duration']
        session.flush()
        session.add_all(RoomInvitation(request_id=record.id,user_id=pid,revision=record.revision) for pid in invitees)
        session.add_all(RoomInvitation(request_id=record.id,user_id=pid,revision=record.revision,status='Accepted') for pid in values.get('participantIds', []))

    def _confirm(self, session, record, actor, state):
        record.status, record.approved_by, record.approved_revision = 'Confirmed', actor, record.revision
        session.add(RoomReservation(request_id=record.id,resource_id=record.resource_id,start_at=record.start_at,end_at=record.end_at))
        session.add(RoomOrganizerCommitment(request_id=record.id,user_id=record.organizer_id,start_at=record.start_at,end_at=record.end_at))
        state.calendar_revision += 1

    def _visible(self, session, request_id, actor):
        permitted = or_(StudentRoomRequest.organizer_id == actor, StudentRoomRequest.approver_id == actor,
            StudentRoomRequest.id.in_(select(RoomInvitation.request_id).where(RoomInvitation.user_id == actor)))
        record = session.scalar(select(StudentRoomRequest).where(StudentRoomRequest.id == request_id, permitted))
        if record is None:
            raise PermissionError('This room request is unavailable or private to its organizer, assigned approver and invitees.')
        return record

    def detail(self, request_id, actor):
        with self.database.transaction(read_only=True) as session:
            self._user(session, actor)
            row = self._visible(session,request_id,actor)
            invitees = list(session.scalars(select(RoomInvitation).where(RoomInvitation.request_id == row.id).order_by(RoomInvitation.user_id)))
            people = {u.id:u for u in session.scalars(select(User).where(User.id.in_({row.organizer_id,row.approver_id,*[i.user_id for i in invitees]})))}
            names = {key: person.name for key, person in people.items()}
            student_role = session.scalar(select(Role.id).where(Role.name == 'Student'))
            room, faculty = session.get(Resource,row.resource_id), session.get(OrganizationUnit,row.faculty_id)
            can_approve = row.approver_id == actor and valid_approvers(session).get(row.faculty_id) == actor
            return {'id':row.id,'organizerId':row.organizer_id,'organizerName':names[row.organizer_id],
                'approverId':row.approver_id,'approverName':names[row.approver_id], 'facultyId':row.faculty_id,'facultyName':faculty.name,
                'roomId':room.id,'roomName':room.name,'roomType':room.type,'building':room.building,'capacity':room.capacity,
                'category':row.category,'purpose':row.purpose,'description':row.description,'club':row.club_affiliation,
                'count':row.attendee_count,'features':row.required_features,'start':row.start_at,'end':row.end_at,
                'duration':row.duration_minutes,'preferredFaculty':row.preferred_faculty_id,'preferredBuilding':row.preferred_building,
                'revision':row.revision,'status':row.status,'explanation':row.explanation,
                'canApprove':can_approve, 'canAudit':can_approve,
                'canFeedback':row.status == 'Confirmed' and row.start_at <= datetime.now(timezone.utc) and (row.organizer_id == actor or any(i.user_id == actor and i.status == 'Accepted' for i in invitees)),
                'invitations':[{'id':i.user_id,'name':names[i.user_id],'status':i.status} for i in invitees if people[i.user_id].primary_role_id != student_role],
                'participants':[{'id':i.user_id,'name':names[i.user_id]} for i in invitees if people[i.user_id].primary_role_id == student_role],
                'history':event_history(session,RoomEvent,row.id,actor,audit=can_approve)}

    def list_for(self, actor):
        with self.database.transaction(read_only=True) as session:
            self._user(session,actor)
            query = select(StudentRoomRequest.id).where(or_(StudentRoomRequest.organizer_id == actor,
                StudentRoomRequest.approver_id == actor, StudentRoomRequest.id.in_(select(RoomInvitation.request_id).where(RoomInvitation.user_id == actor))))
            keys = list(session.scalars(query.order_by(StudentRoomRequest.start_at,StudentRoomRequest.id)))
        return [self.detail(key,actor) for key in keys]

    def _values(self, row):
        return {'start':row['start'],'duration':row['duration'],'count':row['count'],'category':row['category'],
                'features':row['features'],'purpose':row['purpose'],'description':row['description'],'club':row['club'],
                'faculty':row['preferredFaculty'],'building':row['preferredBuilding'],
                'participantIds':[p['id'] for p in row.get('participants', [])]}

    def decide(self, request_id, actor, revision, approve, reason=''):
        if type(approve) is not bool:
            raise RoomRequestError('Choose approve or reject.')
        current = self.detail(request_id,actor)
        if type(revision) is not int or current['revision'] != revision:
            raise RoomRequestError('This request revision changed. Refresh before deciding.')
        if not current['canApprove'] or actor == current['organizerId']:
            raise PermissionError('Only the currently designated room-faculty approver can decide.')
        result = snapshot = calendar_revision = None
        if approve and current['start'] > datetime.now(timezone.utc):
            result, calendar_revision, snapshot, _ = self._evaluate(current['organizerId'],self._values(current),
                [i['id'] for i in current['invitations']],current['roomId'],request_id)
        if not approve and (not isinstance(reason,str) or not reason.strip() or len(reason)>2000):
            raise RoomRequestError('Enter a rejection explanation of 1-2000 characters.')
        try:
            with self.database.transaction() as session:
                state = state_row(session,True)
                record = self._visible(session,request_id,actor)
                guard_waiting(session, room=request_id)
                if record.revision != revision or record.status != 'Pending Faculty Approval':
                    raise RoomRequestError('This request revision is not awaiting approval. Refresh its status.')
                if valid_approvers(session).get(record.faculty_id) != actor or record.approver_id != actor:
                    raise PermissionError('Only the currently designated room-faculty approver can decide.')
                if not approve:
                    record.status, record.explanation = 'Rejected', reason.strip()
                else:
                    if result is not None:
                        self._same_calendar(state,calendar_revision)
                    if result is None or not result['feasible']:
                        record.status = 'Needs Revision'
                        record.explanation = 'Selected room/time no longer available. Choose a fresh candidate and obtain a new faculty approval.'
                    else:
                        self._selected(session,snapshot,record.resource_id)
                        self._confirm(session, record, actor, state)
                self._event(session,record,actor,'Faculty decision on revision '+str(revision)+': '+record.status+'. '+record.explanation)
                return record.status
        except IntegrityError as error:
            if getattr(error.orig,'sqlstate',None) == '23P01':
                raise RoomRequestError('The room or organizer was just reserved. Refresh candidates; no partial approval was saved.') from error
            raise

    def cancel(self, request_id, actor, revision):
        with self.database.transaction() as session:
            state = state_row(session,True)
            self._user(session,actor)
            record = self._visible(session,request_id,actor)
            if actor != record.organizer_id and (record.approver_id != actor or valid_approvers(session).get(record.faculty_id) != actor):
                raise PermissionError('Only the organizer or current assigned faculty approver may cancel.')
            if record.revision != revision or record.status == 'Cancelled':
                raise RoomRequestError('The request changed or is already cancelled.')
            record.status = 'Cancelled'
            close_waiting(session, actor, room=request_id)
            session.execute(delete(RoomReservation).where(RoomReservation.request_id == record.id))
            session.execute(delete(RoomOrganizerCommitment).where(RoomOrganizerCommitment.request_id == record.id))
            state.calendar_revision += 1
            self._event(session,record,actor,'Cancelled; room and organizer reservations released. History retained.')
            refresh_after_commit(session, self.database, self.gateway, 'room', record.faculty_id, self.strategy)

    def respond(self, request_id, actor, revision, accept):
        if type(accept) is not bool:
            raise RoomRequestError('Choose accept or decline.')
        current = self.detail(request_id,actor)
        if type(revision) is not int or current['revision'] != revision:
            raise RoomRequestError('This invitation revision changed. Refresh before responding.')
        calendar_revision = None
        if accept:
            with self.database.transaction(read_only=True) as session:
                self._user(session,actor,'Instructor')
                values = self._values(current)
                values['end'] = current['end']
                snapshot,calendar_revision = room_snapshot(session,actor,'Instructor',values,(current['start'],current['end']),self.strategy,action='attendance')
            result,_ = self.gateway.execute_room(snapshot)
            if not result['feasible']:
                raise RoomRequestError('Your calendar is busy or unresolved. Invitation acceptance cannot override an existing commitment.')
        with self.database.transaction() as session:
            state = state_row(session,True)
            if calendar_revision is not None:
                self._same_calendar(state,calendar_revision)
            record = self._visible(session,request_id,actor)
            self._user(session,actor,'Instructor')
            invitation = session.get(RoomInvitation,(record.id,actor))
            if not invitation or record.revision != revision or record.status not in {'Pending Faculty Approval','Confirmed'}:
                raise RoomRequestError('This current invitation is not available for a response.')
            if accept and record.end_at <= datetime.now(timezone.utc):
                raise RoomRequestError('A past invitation cannot be accepted.')
            invitation.status = 'Accepted' if accept else 'Declined'
            self._event(session,record,actor,'Professor invitation '+invitation.status.lower()+'. Optional attendance does not veto or change room approval.')

    def directory(self, actor, configuration=False):
        with self.database.transaction(read_only=True) as session:
            self._user(session,actor)
            administrator = False
            if configuration:
                try:
                    self._admin(session,actor)
                    administrator = True
                except PermissionError:
                    if actor not in valid_approvers(session).values():
                        raise
            faculties = [{'id':u.id,'name':u.name} for u in session.scalars(select(OrganizationUnit).where(OrganizationUnit.unit_type == 'Faculty').order_by(OrganizationUnit.name))]
            professors = [{'id':u.id,'name':u.name} for u in session.scalars(select(User).join(Role,Role.id == User.primary_role_id).where(Role.name == 'Instructor',User.status == 'active').order_by(User.name,User.id))]
            result = {'faculties':faculties,'professors':professors,'buildings':sorted(set(session.scalars(select(Resource.building))))}
            result['students'] = [{'id':u.id,'name':u.name} for u in session.scalars(select(User).join(Role,Role.id == User.primary_role_id).where(Role.name == 'Student',User.status == 'active',User.id != actor).order_by(User.name,User.id))]
            if configuration:
                result['canConfigure'] = administrator
                result['rooms'] = [{'id':r.id,'name':r.name,'type':r.type,'capacity':r.capacity} for r in session.scalars(select(Resource).order_by(Resource.source_order))]
                result['policies'] = [{'room':r.resource_id,'faculty':r.faculty_id,'enabled':r.enabled,'restricted':r.restricted,'categories':r.categories} for r in session.scalars(select(RoomPolicy))]
                result['approvers'] = [{'faculty':r.faculty_id,'user':r.user_id} for r in session.scalars(select(FacultyRoomApprover))]
                result['accounts'] = [{'id':u.id,'name':u.name} for u in session.scalars(select(User).join(LoginAccount,LoginAccount.user_id == User.id).join(Role,Role.id == User.primary_role_id).where(LoginAccount.enabled == True,User.status == 'active',Role.name != 'Student',or_(Role.name.in_(['Staff','Administrator']),LoginAccount.administrator == True)).order_by(User.name))]
                result['closures'] = [{'id':r.id,'room':r.resource_id,'start':r.start_at,'end':r.end_at,'reason':r.reason} for r in session.scalars(select(RoomClosure).order_by(RoomClosure.start_at))]
                if not administrator:
                    managed = {faculty for faculty, person in valid_approvers(session).items() if person == actor}
                    result['policies'] = [p for p in result['policies'] if p['faculty'] in managed]
                    room_ids = {p['room'] for p in result['policies']}
                    result['rooms'] = [r for r in result['rooms'] if r['id'] in room_ids]
                    result['closures'] = [r for r in result['closures'] if r['room'] in room_ids]
                    result['accounts'] = []
                    result['approvers'] = [r for r in result['approvers'] if r['faculty'] in managed]
            return result

    def configure_approver(self, actor, faculty, approver):
        with self.database.transaction() as session:
            state = state_row(session,True)
            self._admin(session,actor)
            self._faculty(session,faculty)
            user = self._user(session,approver)
            account = session.get(LoginAccount,approver)
            role = session.get(Role,user.primary_role_id).name
            if not account or not account.enabled or role == 'Student' or not (role in {'Staff','Administrator'} or account.administrator):
                raise RoomRequestError('Designate an active, provisioned administrative account, not a student.')
            row = session.get(FacultyRoomApprover,faculty)
            if row is None:
                session.add(FacultyRoomApprover(faculty_id=faculty,user_id=approver))
            else:
                row.user_id = approver
            state.calendar_revision += 1
            refresh_after_commit(session, self.database, self.gateway, 'room', faculty, self.strategy)

    def configure_room(self, actor, room_id, faculty, enabled, categories, restricted=False, allowed_users=()):
        if type(enabled) is not bool or type(restricted) is not bool or not isinstance(categories,(list,tuple)) or not categories or any(not isinstance(c,str) or c not in ROOM_CATEGORIES for c in categories) or len(set(categories)) != len(categories):
            raise RoomRequestError('Select valid room categories and explicit access settings.')
        if not isinstance(allowed_users,(list,tuple)) or len(allowed_users)>10000 or any(type(key) is not int or key <= 0 for key in allowed_users) or len(set(allowed_users)) != len(allowed_users):
            raise RoomRequestError('Use distinct existing identifiers in the optional whitelist.')
        with self.database.transaction() as session:
            state = state_row(session,True)
            self._admin(session,actor)
            self._faculty(session,faculty)
            if session.get(Resource,room_id) is None:
                raise RoomRequestError('Select an existing room.')
            if session.scalar(select(RoomReservation.request_id).where(RoomReservation.resource_id == room_id,RoomReservation.end_at > datetime.now(timezone.utc)).limit(1)) is not None:
                raise RoomRequestError('Resolve future confirmed bookings before changing this room policy.')
            for key in allowed_users:
                self._user(session,key)
            policy = session.get(RoomPolicy,room_id)
            if policy is None:
                policy = RoomPolicy(resource_id=room_id,faculty_id=faculty)
                session.add(policy)
            policy.faculty_id,policy.enabled,policy.restricted,policy.categories = faculty,enabled,restricted,list(categories)
            session.flush()
            session.execute(delete(RoomAccess).where(RoomAccess.resource_id == room_id))
            session.add_all(RoomAccess(resource_id=room_id,user_id=key) for key in allowed_users)
            state.calendar_revision += 1
            refresh_after_commit(session, self.database, self.gateway, 'room', faculty, self.strategy)

    def close_room(self, actor, room_id, start, end, reason=''):
        start,end = aware(start),aware(end)
        epoch(start); epoch(end)
        if start >= end or not isinstance(reason,str) or len(reason)>2000:
            raise RoomRequestError('Enter a valid dated closure and bounded reason.')
        with self.database.transaction() as session:
            state = state_row(session,True)
            self._room_manager(session,actor,room_id)
            if session.get(Resource,room_id) is None:
                raise RoomRequestError('Select an existing room.')
            if session.scalar(select(RoomReservation.request_id).where(RoomReservation.resource_id == room_id,RoomReservation.start_at < end,RoomReservation.end_at > start).limit(1)) is not None:
                raise RoomRequestError('Cancel conflicting confirmed student bookings before closing a room.')
            session.add(RoomClosure(resource_id=room_id,start_at=start,end_at=end,reason=reason))
            session.flush()
            assert_room_publication(session,state.active_run_id)
            state.calendar_revision += 1
            from .feedback_state import record_resource_action
            record_resource_action(session, 'room', room_id, actor, 'Dated closure added: '+start.isoformat()+' to '+end.isoformat()+'. '+reason)

    def reopen_room(self, actor, closure_id):
        with self.database.transaction() as session:
            state = state_row(session,True)
            row = session.get(RoomClosure,closure_id)
            if row is None:
                raise RoomRequestError('Closure not found.')
            self._room_manager(session,actor,row.resource_id)
            from .feedback_state import record_resource_action
            record_resource_action(session, 'room', row.resource_id, actor, 'Dated closure removed: '+row.start_at.isoformat()+' to '+row.end_at.isoformat()+'. '+row.reason)
            session.delete(row)
            state.calendar_revision += 1
            policy = session.get(RoomPolicy, row.resource_id)
            if policy:
                refresh_after_commit(session, self.database, self.gateway, 'room', policy.faculty_id, self.strategy)

    def availability(self, actor, room_id, day):
        zone=university_zone()
        start=local_instant(datetime.combine(day,time()),zone)
        end=local_instant(datetime.combine(day+timedelta(days=1),time()),zone)
        with self.database.transaction(read_only=True) as session:
            self._user(session,actor)
            room=session.get(Resource,room_id)
            policy=session.get(RoomPolicy,room_id)
            account=session.get(LoginAccount,actor)
            administrator=bool(account and account.enabled and (account.administrator or session.get(Role,session.get(User,actor).primary_role_id).name == 'Administrator'))
            permitted=administrator or (policy and policy.enabled and (not policy.restricted or session.get(RoomAccess,(room_id,actor)) is not None))
            if room is None or not permitted:
                raise PermissionError('Room availability is not available to this identity.')
            values,unresolved=academic_room_intervals(session,[room_id],start,end,state_row(session).active_run_id)
            intervals=[{'start':datetime.fromtimestamp(v['start'],zone),'end':datetime.fromtimestamp(v['end'],zone)} for v in values]
            for model in (RoomReservation,RoomClosure):
                intervals.extend({'start':v.start_at.astimezone(zone),'end':v.end_at.astimezone(zone)} for v in session.scalars(select(model).where(
                    model.resource_id == room_id,model.start_at < end,model.end_at > start)))
            intervals.sort(key=lambda v:(v['start'],v['end']))
            return {'id':room.id,'name':room.name,'date':day,'zone':zone.key,'unresolved':bool(unresolved),
                    'enabled':bool(policy and policy.enabled and room.available),'busy':intervals}
