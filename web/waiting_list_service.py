"""Shared consent/review/FCFS coordination; existing C++ services own matching."""

from datetime import datetime, timezone
import copy
import hashlib
import json
import re

from sqlalchemy import or_, select

from .calendar_service import CalendarError
from .equipment_access import custodian_faculties
from .equipment_service import EquipmentService
from .notification_service import event_history
from .persistence.models import (ApplicationState, BorrowRequest, EquipmentEvent, EquipmentType, OrganizationUnit, RoomEvent,
    StudentRoomRequest, User, WaitingListEntry, WAITING_ACTIVE)
from .persistence.repository import state_row
from .room_calendar import room_snapshot, valid_approvers
from .room_request_service import RoomRequestService
from .waiting_list_state import queue_event, refresh_after_commit
from .persistence.models import AcademicPeriod, ReservationPriorityOverride
from .reservation_policy import policy_directory


POLICY_VERSION = 'waiting-lists-v1'


class WaitingListError(CalendarError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'),
                                     default=lambda v: v.astimezone(timezone.utc).isoformat()).encode()).hexdigest()


class WaitingListService:
    def __init__(self, database, gateway, strategy='best_fit', clock=None):
        self.database, self.gateway = database, gateway
        self.rooms = RoomRequestService(database, gateway, strategy)
        self.equipment = EquipmentService(database, gateway)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def policy(self):
        with self.database.transaction(read_only=True) as session:
            return {'version': POLICY_VERSION, 'noticeMinutes': state_row(session).waiting_notice_minutes,**policy_directory(session)}

    def configure_reservations(self, actor, limits, priorities):
        if not isinstance(limits,dict) or set(limits)-{'room','equipment'} or not isinstance(priorities,list):
            raise WaitingListError('Choose explicit room/equipment limits and priority levels.')
        for values in limits.values():
            if not isinstance(values,dict) or set(values)-{'maxWeeklyMinutes','maxActiveSeries'} or any(
                    type(v) is not int or not 1<=v<=2147483647 for v in values.values()):
                raise WaitingListError('Configured quotas must be positive integers; leave a limit unset for no quota.')
        if len(priorities)>100 or any(type(v) is not int or not 0<v<=1000000 for v in priorities) or len(set(priorities))!=len(priorities):
            raise WaitingListError('Configure distinct positive priority levels. Standard priority is zero; larger levels go first.')
        with self.database.transaction() as session:
            self.rooms._admin(session,actor)
            state=state_row(session,True)
            state.recurring_limits,state.reservation_priorities=limits,sorted(priorities)
            state.calendar_revision+=1

    def configure_semester(self, actor, name, start, end):
        from .calendar_service import university_zone
        if not isinstance(name,str) or not 1<=len(name.strip())<=200 or start>end:
            raise WaitingListError('Enter a named semester with explicit start and end dates.')
        with self.database.transaction() as session:
            self.rooms._admin(session,actor)
            state_row(session,True)
            existing=session.scalar(select(AcademicPeriod).where(AcademicPeriod.name==name.strip()))
            if existing:
                if (existing.start_date,existing.end_date,existing.timezone)!=(start,end,university_zone().key):
                    raise WaitingListError('This academic period has different dates. Existing dates are not overwritten.')
                existing.is_semester=True
            else:session.add(AcademicPeriod(name=name.strip(),start_date=start,end_date=end,timezone=university_zone().key,is_semester=True))

    def bind_series_semester(self, actor, kind, key, period_id):
        from .recurring_records import occurrences_for,series_for
        from .reservation_policy import semester
        with self.database.transaction() as session:
            self.rooms._admin(session,actor)
            state=state_row(session,True)
            parent=session.get(StudentRoomRequest if kind=='room' else BorrowRequest,key) if kind in {'room','equipment'} else None
            series=series_for(session,parent) if parent else None
            if series is None or series.period_id is not None:
                raise WaitingListError('Only an existing series without a semester may be explicitly bound once.')
            rows=occurrences_for(session,series)
            semester(session,{'timezone':series.timezone,'intervals':[(r.start_at,r.end_at) for r in rows]},
                {'periodId':period_id,'approvalMode':series.approval_mode})
            series.period_id=period_id
            state.calendar_revision+=1
            message='Explicitly bound existing recurring series to academic semester '+str(period_id)+'. Calendar dates unchanged.'
            if kind=='room':self.rooms._event(session,parent,actor,message)
            else:self.equipment._event(session,actor,parent.faculty_id,message,key)

    def override_priority(self, kind, key, actor, priority, reason):
        if type(priority) is not int or not isinstance(reason,str) or not 1<=len(reason.strip())<=2000:
            raise WaitingListError('A configured priority and mandatory justification are required.')
        with self.database.transaction() as session:
            if kind=='room':
                parent=self.rooms._visible(session,key,actor)
            elif kind=='equipment':
                parent=self.equipment._request(session,actor,key)
            else:raise WaitingListError('Choose room or equipment.')
            state=self._lock(session,kind,parent.faculty_id)
            session.refresh(parent)
            if self._reviewer(session,kind,parent.faculty_id)!=actor:
                raise PermissionError('Only the current responsible faculty approver or custodian can override priority.')
            if priority not in [0,*state.reservation_priorities] or priority==parent.priority:
                raise WaitingListError('Choose a different explicitly configured priority.')
            from .recurring_records import occurrences_for,series_for
            remaining=[o for o in occurrences_for(session,series_for(session,parent)) if o.status in {'Proposed','Unavailable'} and o.start_at>self.clock()]
            if not remaining and (parent.start_at<=self.clock() or parent.status in {'Cancelled','Rejected','Returned','Confirmed','Approved','Borrowed','Partially Returned'}):
                raise WaitingListError('Priority may change only for a future unconfirmed request.')
            old=parent.priority
            audit=ReservationPriorityOverride(actor_id=actor,original_priority=old,selected_priority=priority,reason=reason.strip(),
                room_request_id=key if kind=='room' else None,borrow_request_id=key if kind=='equipment' else None)
            session.add(audit);session.flush()
            parent.priority=priority
            message=f'Priority override {old} -> {priority}. Reason: {reason.strip()}'
            if kind=='room':self.rooms._event(session,parent,actor,message)
            else:self.equipment._event(session,actor,parent.faculty_id,message,key)
            self._positions(session,self._active(session,kind,parent.faculty_id))

    def configure_notice(self, actor, minutes):
        if type(minutes) is not int or not 1 <= minutes <= 2147483647:
            raise WaitingListError('Configure an explicit positive number of advance-notice minutes.')
        with self.database.transaction() as session:
            self.rooms._admin(session, actor)
            state_row(session, True).waiting_notice_minutes = minutes
            for kind, faculty in {(self._kind(e), e.faculty_id) for e in session.scalars(
                    select(WaitingListEntry).where(WaitingListEntry.status.in_(WAITING_ACTIVE)))}:
                refresh_after_commit(session, self.database, self.gateway, kind, faculty, self.rooms.strategy, self.clock)

    def management(self, actor):
        with self.database.transaction(read_only=True) as session:
            self.rooms._admin(session, actor)
        return self.policy()

    def _consent(self, version, accepted, key):
        if version != POLICY_VERSION or accepted is not True:
            raise WaitingListError('Read and explicitly accept the current waiting-list policy before joining.')
        if not isinstance(key, str) or not re.fullmatch('[0-9a-f]{32}', key):
            raise WaitingListError('Refresh the form for a valid submission identity.')

    def _retry(self, session, actor, key, fingerprint):
        entry = session.scalar(select(WaitingListEntry).where(WaitingListEntry.owner_id == actor,
            WaitingListEntry.submission_key == key))
        if entry and entry.fingerprint != fingerprint:
            raise WaitingListError('This submission identity was used for different requirements. Refresh the form.')
        return entry

    def _lock(self, session, kind, faculty):
        if kind == 'room':
            state = state_row(session, True)
            self.rooms._faculty(session, faculty)
        elif kind == 'equipment':
            state = self._notice_lock(session)
            self.equipment._faculty(session, faculty, True)
        else:
            raise WaitingListError('Choose room or equipment waiting lists.')
        return state

    def _notice_lock(self, session):
        # Policy changes must not overtake an in-flight equipment confirmation.
        # Always acquire state before identity/faculty locks, matching room order.
        return session.scalar(select(ApplicationState).where(ApplicationState.id == 1)
            .with_for_update(read=True).execution_options(populate_existing=True)) or state_row(session)

    def _kind(self, entry):
        return 'room' if entry.room_request_id is not None else 'equipment'

    def _parent(self, session, entry):
        return session.get(StudentRoomRequest, entry.room_request_id) if entry.room_request_id is not None else session.get(BorrowRequest, entry.borrow_request_id)

    def _reviewer(self, session, kind, faculty):
        return valid_approvers(session).get(faculty) if kind == 'room' else self.equipment._custodian(session, faculty)

    def _room_values(self, row):
        return {'start': row.start_at, 'end': row.end_at, 'duration': row.duration_minutes, 'count': row.attendee_count,
                'category': row.category, 'features': row.required_features, 'purpose': row.purpose,
                'description': row.description, 'club': row.club_affiliation,
                'faculty': row.preferred_faculty_id, 'building': row.preferred_building}

    def _room_match(self, session, actor, values, faculty, *, eligibility=False):
        snapshot, _ = room_snapshot(session, actor, 'Student', values, (values['start'], values['end']), self.rooms.strategy)
        snapshot['rooms'] = [r for r in snapshot['rooms'] if r['facultyId'] == faculty]
        if eligibility:
            # Hypothetical physical availability ignores occupancy/out-of-service.
            # C++ still evaluates every
            # access/capacity/facility/calendar/organizer rule, without a second rule set.
            snapshot = copy.deepcopy(snapshot)
            for room in snapshot['rooms']:
                room['busy'] = []
                room['available'] = True
        result, _ = self.gateway.execute_room(snapshot)
        return result

    def _new_entry(self, session, actor, faculty, key, fingerprint, queue, **parent):
        entry = WaitingListEntry(owner_id=actor, faculty_id=faculty, submission_key=key, fingerprint=fingerprint,
            queue_key=digest(queue), policy_version=POLICY_VERSION,
            notice_minutes=state_row(session).waiting_notice_minutes, **parent)
        session.add(entry)
        session.flush()
        queue_event(session, entry, actor, 'Joined waiting list with explicit '+POLICY_VERSION+' consent. '+entry.explanation)
        return entry

    def join_room(self, actor, values, invitees, faculty, version, accepted, key):
        if isinstance(values,dict) and values.get('recurrence'):
            raise WaitingListError('Recurring series need a reviewed series queue policy. Revise unavailable dates; individual occurrences are not enrolled separately.')
        self._consent(version, accepted, key)
        with self.database.transaction() as session:
            self._lock(session, 'room', faculty)
            self.equipment._user(session, actor, student=True)
            values = self.rooms._validate(session, actor, values, invitees)
            fingerprint = digest({'kind': 'room', 'values': values, 'invitees': sorted(invitees), 'faculty': faculty})
            retry = self._retry(session, actor, key, fingerprint)
            if retry:
                return retry.id
            if values['start'] <= self.clock():
                raise WaitingListError('Waiting lists require a future interval; dates are never changed automatically.')
            full, _ = room_snapshot(session, actor, 'Student', values, (values['start'], values['end']), self.rooms.strategy)
            available, _ = self.gateway.execute_room(full)
            if available['feasible']:
                raise WaitingListError('An eligible room is available. Review candidates and use the normal request workflow.')
            eligible = self._room_match(session, actor, values, faculty, eligibility=True)
            if not eligible['feasible']:
                raise WaitingListError('No compatible room policy exists in this faculty, or the organizer/calendar is unavailable. Resolve eligibility before joining.')
            choice = eligible['candidates'][0]
            reviewer = self._reviewer(session, 'room', faculty)
            parent = StudentRoomRequest(organizer_id=actor)
            session.add(parent)
            self.rooms._store(session, parent, values, invitees, choice['roomId'], faculty, reviewer)
            parent.explanation = 'Waiting for any compatible room in this owning faculty; the displayed room is not reserved.'
            queue = {'kind': 'room', 'faculty': faculty, 'start': values['start'], 'end': values['end'],
                     'category': values['category'], 'count': values['count'], 'features': sorted(values['features'])}
            entry = self._new_entry(session, actor, faculty, key, fingerprint, queue, room_request_id=parent.id)
            self._positions(session, self._active(session, 'room', faculty))
            return entry.id

    def join_equipment(self, actor, faculty, items, start, due, purpose, notes, version, accepted, key):
        self._consent(version, accepted, key)
        items, (start, due) = self.equipment._items(items), self.equipment._period(start, due)
        purpose = self.equipment._text(purpose, 'purpose')
        notes = self.equipment._text(notes, 'notes', 4000, False)
        payload = {'kind': 'equipment', 'faculty': faculty, 'items': items, 'start': start, 'due': due, 'purpose': purpose, 'notes': notes}
        fingerprint = digest(payload)
        with self.database.transaction() as session:
            self._notice_lock(session)
            # Keep identity -> faculty ordering after the shared policy lock.
            session.scalar(select(User).where(User.id == actor).with_for_update())
            self.equipment._user(session, actor, student=True)
            self._lock(session, 'equipment', faculty)
            retry = self._retry(session, actor, key, fingerprint)
            if retry:
                return retry.id
            if session.scalar(select(BorrowRequest.id).where(BorrowRequest.borrower_id == actor, BorrowRequest.submission_key == key)):
                raise WaitingListError('This identity already belongs to a normal borrowing request. Refresh the form.')
            result = self.equipment._match(session, actor, faculty, items, start, due)
            if result['feasible']:
                raise WaitingListError('Equipment is available. Use the normal borrowing request workflow.')
            if any(i['reasonCode'] not in {'AVAILABLE', 'INSUFFICIENT_QUANTITY'} for i in result['items']):
                raise WaitingListError('The request is not eligible under current equipment/custodian policies. Resolve eligibility before joining.')
            parent = self.equipment._store(session, actor, faculty, items, start, due, purpose, notes, key, fingerprint)
            queue = {'kind': 'equipment', 'faculty': faculty, 'items': items, 'start': start, 'due': due}
            entry = self._new_entry(session, actor, faculty, key, fingerprint, queue, borrow_request_id=parent.id)
            self._positions(session, self._active(session, 'equipment', faculty))
            return entry.id

    def _active(self, session, kind, faculty):
        column = WaitingListEntry.room_request_id if kind == 'room' else WaitingListEntry.borrow_request_id
        entries=list(session.scalars(select(WaitingListEntry).where(WaitingListEntry.faculty_id == faculty,
            column.is_not(None), WaitingListEntry.status.in_(WAITING_ACTIVE)).order_by(WaitingListEntry.id)))
        return sorted(entries,key=lambda e:(-self._parent(session,e).priority,e.accepted_at,e.id))

    def _ranks(self, session, entries):
        estimates, eligible, result = {}, {}, {}
        notice = state_row(session).waiting_notice_minutes
        for entry in entries:
            if entry.status not in WAITING_ACTIVE:
                continue
            estimates[entry.queue_key] = estimates.get(entry.queue_key, 0) + 1
            position = estimates[entry.queue_key]
            if entry.status == 'Preapproved':
                parent = self._parent(session, entry)
                if notice is None or (parent.start_at-self.clock()).total_seconds() < max(notice, entry.notice_minutes or 0)*60:
                    result[entry.id] = None
                    continue
                eligible[entry.queue_key] = eligible.get(entry.queue_key, 0) + 1
                position = eligible[entry.queue_key]
            result[entry.id] = position
        return result

    def _positions(self, session, entries):
        result = self._ranks(session, entries)
        for entry in entries:
            position = result.get(entry.id)
            if entry.status == 'Preapproved' and position is not None:
                for field, applies, message in (
                    ('top_three_notified', position <= 3, 'First entry into the top three eligible waiting positions.'),
                    ('first_notified', position == 1, 'You reached eligible waiting position one. Availability and advance-notice checks still apply.')):
                    if applies and not getattr(entry, field):
                        setattr(entry, field, True)
                        queue_event(session, entry, entry.approved_by, message, student_only=True)
        return result

    def _access(self, session, key, actor):
        self.equipment._user(session, actor)
        entry = session.get(WaitingListEntry, key) if type(key) is int and key > 0 else None
        if entry is None or (actor != entry.owner_id and actor != self._reviewer(session, self._kind(entry), entry.faculty_id)):
            raise PermissionError('This waiting-list entry is private to its student and current responsible staff.')
        return entry

    def review(self, key, actor, approve, reason=''):
        if type(approve) is not bool or not isinstance(reason, str) or len(reason) > 2000 or (not approve and not reason.strip()):
            raise WaitingListError('Choose pre-approve or reject, with a bounded explanation for rejection.')
        with self.database.transaction() as session:
            entry = self._access(session, key, actor)
            kind, faculty = self._kind(entry), entry.faculty_id
            state = self._lock(session, kind, faculty)
            session.refresh(entry)
            if self._reviewer(session, kind, faculty) != actor or (kind == 'room' and actor == entry.owner_id):
                raise PermissionError('Only the current owning-faculty approver or custodian may review this queue.')
            if entry.status != 'Pending Review':
                raise WaitingListError('This entry is no longer awaiting review. Refresh its status.')
            parent = self._parent(session, entry)
            if kind == 'room':
                parent.approver_id = actor
            if approve:
                entry.status, entry.approved_by, entry.approved_at = 'Preapproved', actor, self.clock()
                if state.waiting_notice_minutes is not None:
                    entry.notice_minutes = max(entry.notice_minutes or 0, state.waiting_notice_minutes)
                entry.explanation = 'Preapproved; no resource is held. Final eligibility, availability and advance notice will be checked.'
                queue_event(session, entry, actor, 'Waiting-list pre-approval. '+entry.explanation)
            else:
                self._close(session, entry, actor, 'Rejected', reason.strip())
            if approve:
                self._process_locked(session, kind, faculty, state)
            else:
                self._positions(session, self._active(session, kind, faculty))
                refresh_after_commit(session, self.database, self.gateway, kind, faculty, self.rooms.strategy, self.clock)

    def _close(self, session, entry, actor, status, explanation):
        parent = self._parent(session, entry)
        entry.status, entry.explanation = status, explanation
        parent.status = 'Cancelled' if status in {'Cancelled', 'Expired'} else 'Rejected'
        if entry.room_request_id is not None:
            parent.explanation = explanation
        queue_event(session, entry, actor, 'Waiting list '+status.lower()+'. '+explanation)

    def cancel(self, key, actor):
        with self.database.transaction() as session:
            entry = self._access(session, key, actor)
            kind, faculty = self._kind(entry), entry.faculty_id
            self._lock(session, kind, faculty)
            session.refresh(entry)
            self._access(session, key, actor)
            if entry.status == 'Cancelled':
                return
            if entry.status not in WAITING_ACTIVE:
                raise WaitingListError('Only a waiting entry can be withdrawn. Use the normal reservation lifecycle after assignment.')
            self._close(session, entry, actor, 'Cancelled', 'Withdrawn without penalty; no active queue position remains.')
            self._positions(session, self._active(session, kind, faculty))
            refresh_after_commit(session, self.database, self.gateway, kind, faculty, self.rooms.strategy, self.clock)

    def process(self, kind, faculty, contender_id=None):
        """Internal processing has no caller authority: stored pre-approval is revalidated."""
        with self.database.transaction() as session:
            state = self._lock(session, kind, faculty)
            contender=session.get(StudentRoomRequest if kind=='room' else BorrowRequest,contender_id) if contender_id is not None else None
            return self._process_locked(session, kind, faculty, state, contender)

    def _process_locked(self, session, kind, faculty, state, contender=None):
        entries = self._active(session, kind, faculty)
        assigned = []
        for entry in entries:
            parent = self._parent(session, entry)
            # Existing pre-approved queues are already eligible. A pending series
            # cannot overtake peers merely because it was drafted earlier.
            if contender is not None and parent.priority<contender.priority:
                continue
            reviewer = self._reviewer(session, kind, faculty)
            if parent.start_at <= self.clock():
                self._close(session, entry, reviewer or entry.approved_by or entry.owner_id, 'Expired', 'Automatic policy expiry: the requested start passed without assignment. No reservation or penalty was created.')
                continue
            if entry.policy_version != POLICY_VERSION:
                self._close(session, entry, reviewer or entry.owner_id, 'Ineligible', 'The waiting-list policy changed. Read and accept the current policy in a new request.')
                continue
            if entry.status == 'Preapproved' and reviewer != entry.approved_by:
                entry.status, entry.approved_by, entry.approved_at = 'Pending Review', None, None
                entry.explanation = 'Responsible staff changed or became unavailable. A fresh authorized pre-approval is required.'
                if kind == 'room' and reviewer is not None:
                    parent.approver_id = reviewer
                queue_event(session, entry, entry.owner_id, entry.explanation)
            if reviewer is None:
                entry.explanation = 'Responsible staff configuration is unavailable; automatic assignment is blocked.'
                continue
            try:
                self.equipment._user(session, entry.owner_id, student=True)
                if kind == 'room':
                    invitees, students = self.rooms._member_ids(session,parent.id)
                    values = self.rooms._validate(session, entry.owner_id,
                        {**self._room_values(parent), 'participantIds':students}, invitees)
                    eligible = self._room_match(session, entry.owner_id, values, faculty, eligibility=True)['feasible']
                    match = self._room_match(session, entry.owner_id, values, faculty) if eligible else None
                else:
                    items = self.equipment._needs(self.equipment._lines(session, parent.id))
                    match = self.equipment._match(session, entry.owner_id, faculty, items, parent.start_at, parent.due_at)
                    eligible = all(i['reasonCode'] in {'AVAILABLE', 'INSUFFICIENT_QUANTITY'} for i in match['items'])
            except PermissionError:
                eligible, match = False, None
            if not eligible:
                self._close(session, entry, reviewer, 'Ineligible', 'Mandatory eligibility or calendar requirements no longer hold. Submit a corrected request for a new review.')
                continue
            if entry.status != 'Preapproved':
                continue
            notice = state.waiting_notice_minutes
            if notice is None:
                entry.explanation = 'Automatic assignment is disabled until administration explicitly configures minimum advance notice.'
                continue
            entry.notice_minutes = max(entry.notice_minutes or 0, notice)
            if (parent.start_at - self.clock()).total_seconds() < entry.notice_minutes * 60:
                entry.explanation = 'Too little advance notice for automatic assignment. No last-minute booking or penalty will be created.'
                continue
            if not match['feasible']:
                entry.explanation = 'Still waiting for the complete compatible request at its original interval.'
                continue
            # Positions are computed before consumption, so one-time milestones
            # and the reservation become visible in the same transaction.
            self._positions(session, entries)
            if kind == 'room':
                choice = match['candidates'][0]
                parent.resource_id, parent.approver_id = choice['roomId'], reviewer
                self.rooms._confirm(session, parent, reviewer, state)
                parent.explanation = 'Automatically confirmed under the owning faculty pre-approval and accepted waiting-list policy.'
            else:
                self.equipment._reserve(session, parent, match)
            entry.status, entry.explanation = 'Assigned', 'Automatically assigned the complete original request; no second acceptance is required.'
            queue_event(session, entry, reviewer, entry.explanation + (' Physical equipment handover is still required.' if kind == 'equipment' else ''),
                        include_participants=True)
            session.flush()
            assigned.append(entry.id)
        self._positions(session, entries)
        return assigned

    def refresh_for(self, actor):
        """Refresh only queues visible to this identity; never accept a supplied actor."""
        with self.database.transaction(read_only=True) as session:
            self.equipment._user(session, actor)
            scopes = self._visible_entries(session, actor)
            groups = {(self._kind(e), e.faculty_id) for e in scopes if e.status in WAITING_ACTIVE}
        for kind, faculty in sorted(groups):
            self.process(kind, faculty)

    def refresh_all(self, kind=None):
        """Internal maintenance entry point; HTTP callers use refresh_for instead."""
        with self.database.transaction(read_only=True) as session:
            query = select(WaitingListEntry).where(WaitingListEntry.status.in_(WAITING_ACTIVE))
            if kind is not None:
                if kind not in {'room', 'equipment'}:
                    raise WaitingListError('Choose a supported waiting-list kind.')
                column = WaitingListEntry.room_request_id if kind == 'room' else WaitingListEntry.borrow_request_id
                query = query.where(column.is_not(None))
            groups = {(self._kind(e), e.faculty_id) for e in session.scalars(query)}
        for source, faculty in sorted(groups):
            self.process(source, faculty)

    def _visible_entries(self, session, actor):
        faculties = [faculty for faculty, person in valid_approvers(session).items() if person == actor]
        return list(session.scalars(select(WaitingListEntry).where(or_(WaitingListEntry.owner_id == actor,
            (WaitingListEntry.room_request_id.is_not(None) & WaitingListEntry.faculty_id.in_(faculties)),
            (WaitingListEntry.borrow_request_id.is_not(None) & WaitingListEntry.faculty_id.in_(custodian_faculties(actor)))))
            .order_by(WaitingListEntry.id)))

    def list_for(self, actor):
        with self.database.transaction(read_only=True) as session:
            self.equipment._user(session, actor)
            entries = self._visible_entries(session, actor)
            ranks = {}
            for kind, faculty in {(self._kind(e), e.faculty_id) for e in entries}:
                ranks.update(self._ranks(session, self._active(session, kind, faculty)))
            return [self._detail(session, e, actor, ranks) for e in entries]

    def detail(self, key, actor):
        with self.database.transaction(read_only=True) as session:
            return self._detail(session, self._access(session, key, actor), actor)

    def for_parent(self, kind, parent_id, actor):
        with self.database.transaction(read_only=True) as session:
            column = WaitingListEntry.room_request_id if kind == 'room' else WaitingListEntry.borrow_request_id
            key = session.scalar(select(WaitingListEntry.id).where(column == parent_id))
            if key is None:
                return None
            try:
                entry = self._access(session, key, actor)
            except PermissionError:
                return None
            return self._detail(session, entry, actor)

    def _detail(self, session, entry, actor, ranks=None):
        kind, parent = self._kind(entry), self._parent(session, entry)
        eligible = entry.status == 'Preapproved'
        if ranks is None:
            ranks = self._ranks(session, self._active(session, kind, entry.faculty_id))
        position = ranks.get(entry.id)
        requirements = self._room_values(parent) if kind == 'room' else self.equipment._needs(self.equipment._lines(session, parent.id))
        if kind == 'equipment':
            for line in requirements:
                line['name'] = session.get(EquipmentType, line['typeId']).name
        reviewer = actor == self._reviewer(session, kind, entry.faculty_id) and (kind != 'room' or actor != entry.owner_id)
        return {'id': entry.id, 'kind': kind, 'ownerId': entry.owner_id, 'owner': session.get(User, entry.owner_id).name,
                'faculty': session.get(OrganizationUnit, entry.faculty_id).name, 'facultyId': entry.faculty_id,
                'status': entry.status, 'explanation': entry.explanation, 'purpose': parent.purpose,
                'priority':parent.priority,'priorities':state_row(session).reservation_priorities,
                'start': parent.start_at, 'end': parent.end_at if kind == 'room' else parent.due_at,
                'requirements': requirements, 'requestId': parent.id, 'position': position,
                'positionLabel': 'Eligible' if eligible else 'Estimated', 'acceptedAt': entry.accepted_at,
                'policyVersion': entry.policy_version, 'noticeMinutes': entry.notice_minutes,
                'canReview': reviewer, 'canAudit': reviewer,
                'history': event_history(session, RoomEvent if kind == 'room' else EquipmentEvent, parent.id, actor, audit=reviewer)}
