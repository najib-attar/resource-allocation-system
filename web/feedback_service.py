"""Private, transactional feedback; no allocation or availability decisions."""
from datetime import datetime, timezone
import hashlib
import json
import re

from sqlalchemy import select

from .calendar_service import CalendarError
from .equipment_access import custodian_faculties, valid_custodians
from .feedback_access import managed_scope, room_faculties, visible_scope
from .notification_service import event_history, publish_event
from .persistence.models import (BorrowItem, BorrowRequest, EquipmentReservation, EquipmentType, EquipmentUnit,
    EquipmentCustodian, FacultyRoomApprover, FeedbackEvent, LoginAccount, Resource, ResourceFeedback, RoomInvitation, StudentRoomRequest, User,
    FEEDBACK_CATEGORIES, FEEDBACK_PRIORITIES, FEEDBACK_STATES)
from .room_calendar import valid_approvers


class FeedbackError(CalendarError):
    pass


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


class FeedbackService:
    def __init__(self, database, clock=None):
        self.database = database
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _identity(self, session, actor, lock=False):
        user = session.get(User, actor, with_for_update=lock) if type(actor) is int and actor > 0 else None
        account = session.get(LoginAccount, actor) if user else None
        if user is None or user.status.casefold() != 'active' or account is None or not account.enabled:
            raise PermissionError('An active authenticated university identity is required.')

    def _text(self, value):
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 4000:
            raise FeedbackError('Enter a description or response of 1-4000 characters.')
        return value.strip()

    def _key(self, key):
        if not isinstance(key, str) or not re.fullmatch('[0-9a-f]{32}', key):
            raise FeedbackError('Refresh the form for a valid submission identity.')

    def _responsible(self, session, room, faculty, lock=False):
        if lock:
            model = FacultyRoomApprover if room else EquipmentCustodian
            session.scalar(select(model).where(model.faculty_id == faculty).with_for_update(read=True))
        people = valid_approvers(session) if room else dict(session.execute(valid_custodians()).all())
        key = people.get(faculty)
        if key is None:
            raise FeedbackError('The owning faculty needs an active responsible staff assignment. Contact university administration.')
        return key

    def _context(self, session, kind, booking_id, actor, lock=False):
        self._identity(session, actor)
        if type(booking_id) is not int or booking_id <= 0:
            raise FeedbackError('Select a valid booking.')
        if kind == 'room':
            booking = session.get(StudentRoomRequest, booking_id, with_for_update={'read':True} if lock else None)
            participant = session.get(RoomInvitation, (booking_id, actor))
            if booking is None or not (booking.organizer_id == actor or (participant and participant.revision == booking.revision and participant.status == 'Accepted')):
                raise PermissionError('Only the organizer or an explicitly registered participating user can report on this booking.')
            if booking.status != 'Confirmed' or self.clock() < booking.start_at:
                raise FeedbackError('Reports require an active or completed confirmed room reservation, not a pending, future or cancelled request.')
            room = session.get(Resource, booking.resource_id)
            return {'kind':kind, 'bookingId':booking_id, 'facultyId':booking.faculty_id,
                    'resources':[{'id':room.id, 'name':room.name, 'completed':self.clock() >= booking.end_at}],
                    'room':booking, 'title':'Room reservation'}
        if kind == 'equipment':
            booking = session.get(BorrowRequest, booking_id, with_for_update={'read':True} if lock else None)
            if booking is None or booking.borrower_id != actor:
                raise PermissionError('Only the recorded borrower can report on this loan.')
            rows = session.execute(select(EquipmentReservation, EquipmentUnit, EquipmentType).join(
                BorrowItem, BorrowItem.id == EquipmentReservation.item_id).join(EquipmentUnit, EquipmentUnit.id == EquipmentReservation.unit_id).join(
                EquipmentType, EquipmentType.id == EquipmentUnit.type_id).where(BorrowItem.request_id == booking_id,
                    EquipmentReservation.handed_at.is_not(None))).all()
            if not rows:
                raise FeedbackError('Feedback requires physical handover; approval or a due date is not proof of resource use.')
            return {'kind':kind, 'bookingId':booking_id, 'facultyId':booking.faculty_id,
                    'resources':[{'id':r.id, 'name':t.name+' / '+u.asset_tag, 'completed':r.returned_at is not None} for r,u,t in rows],
                    'room':None, 'title':'Equipment loan'}
        raise FeedbackError('Select room or equipment feedback.')

    def context(self, kind, booking_id, actor):
        with self.database.transaction(read_only=True) as session:
            result = self._context(session, kind, booking_id, actor)
            return {k:v for k,v in result.items() if k != 'room'}

    def submit(self, actor, kind, booking_id, resource_id, category, description, urgent, key):
        self._key(key)
        description = self._text(description)
        if category not in FEEDBACK_CATEGORIES or type(urgent) is not bool or (urgent and category != 'problem'):
            raise FeedbackError('Choose a supported category; urgent safety flags apply only to problems.')
        if type(resource_id) is not int or resource_id <= 0:
            raise FeedbackError('Choose an actually used resource.')
        payload = fingerprint([kind,booking_id,resource_id,category,description,urgent])
        with self.database.transaction() as session:
            self._identity(session, actor, lock=True)
            existing = session.scalar(select(ResourceFeedback).where(ResourceFeedback.reporter_id == actor, ResourceFeedback.submission_key == key))
            if existing:
                if existing.fingerprint != payload:
                    raise FeedbackError('This submission identity was used for different feedback. Refresh the form.')
                return existing.id
            context = self._context(session, kind, booking_id, actor, lock=True)
            resource = next((r for r in context['resources'] if r['id'] == resource_id), None)
            if resource is None:
                raise PermissionError('The selected resource does not belong to your actual usage record.')
            if not resource['completed'] and category != 'problem':
                raise FeedbackError('During active use, report problems. General feedback and improvements are available after room completion or verified return.')
            room = context['room']
            staff = self._responsible(session, kind == 'room', context['facultyId'], lock=True)
            report = ResourceFeedback(reporter_id=actor, faculty_id=context['facultyId'], assigned_to_id=staff,
                room_request_id=booking_id if room else None, room_resource_id=room.resource_id if room else None,
                room_revision=room.revision if room else None, equipment_reservation_id=resource_id if not room else None,
                category=category, description=description, priority='urgent' if urgent else 'normal',
                submission_key=key, fingerprint=payload)
            session.add(report); session.flush()
            self._event(session, report, actor, 'Submitted '+category+' report'+(' (urgent safety concern)' if urgent else '')+'. '+description, key, payload, staff)
            return report.id

    def _event(self, session, report, actor, message, key, payload, recipient):
        publish_event(session, FeedbackEvent(report_id=report.id, actor_id=actor, revision=report.revision,
            status=report.status, message=message, action_key=key, fingerprint=payload), recipient_ids={recipient}, notify_actor=True)

    def _access(self, session, key, actor, lock=False):
        self._identity(session, actor)
        if type(key) is not int or key <= 0:
            raise PermissionError('A valid private report identity is required.')
        query = select(ResourceFeedback).where(ResourceFeedback.id == key, visible_scope(actor))
        row = session.scalar(query.with_for_update() if lock else query)
        if row is None:
            raise PermissionError('This private report is unavailable to your identity or responsibility scope.')
        return row

    def _managed(self, session, report, actor):
        return session.scalar(select(ResourceFeedback.id).where(ResourceFeedback.id == report.id, managed_scope(actor))) is not None

    def update(self, key, actor, revision, status, priority, response, action_key, *, reply=False):
        self._key(action_key)
        response = self._text(response)
        if type(revision) is not int or revision <= 0 or type(reply) is not bool:
            raise FeedbackError('Refresh the report for its current revision.')
        payload = fingerprint([actor,revision,status,priority,response,reply])
        with self.database.transaction() as session:
            report = self._access(session, key, actor, lock=True)
            if reply:
                if actor != report.reporter_id:
                    raise PermissionError('Only the reporter may add their clarification.')
            elif not self._managed(session, report, actor):
                raise PermissionError('Only current responsible staff can review or resolve this report.')
            previous = session.scalar(select(FeedbackEvent).where(FeedbackEvent.report_id == key, FeedbackEvent.action_key == action_key))
            if previous:
                if previous.fingerprint != payload:
                    raise FeedbackError('This action identity was reused for a different update.')
                return
            if report.revision != revision:
                raise FeedbackError('Another update changed this report. Refresh before responding.')
            staff = self._responsible(session, report.room_request_id is not None, report.faculty_id, lock=True)
            old = report.status
            if reply:
                if old not in {'Submitted','Under Review'}:
                    raise FeedbackError('This report is resolved or closed. Responsible staff must reopen it before further clarification.')
            else:
                transitions = {'Submitted':{'Under Review'}, 'Under Review':{'Under Review','Resolved','Closed'},
                               'Resolved':{'Under Review'}, 'Closed':{'Under Review'}}
                if not isinstance(status,str) or not isinstance(priority,str) or status not in transitions[old] or priority not in FEEDBACK_PRIORITIES:
                    raise FeedbackError('Use Submitted -> Under Review -> Resolved/Closed. Reopen a finished report with an explanation.')
                report.status, report.priority, report.response = status, priority, response
            report.assigned_to_id = staff
            report.revision += 1
            report.updated_at = self.clock()
            message = ('Reporter clarification: ' if reply else old+' -> '+report.status+'; priority '+report.priority+'. ')+response
            self._event(session, report, actor, message, action_key, payload, staff if reply else report.reporter_id)

    def _query(self):
        return select(ResourceFeedback, User.name.label('reporter'), Resource.name.label('room_name'),
            EquipmentType.name.label('equipment_name'), EquipmentUnit.asset_tag, EquipmentUnit.id.label('asset_id'), BorrowItem.request_id.label('loan_id')).join(
            User, User.id == ResourceFeedback.reporter_id).outerjoin(Resource, Resource.id == ResourceFeedback.room_resource_id).outerjoin(
            EquipmentReservation, EquipmentReservation.id == ResourceFeedback.equipment_reservation_id).outerjoin(
            EquipmentUnit, EquipmentUnit.id == EquipmentReservation.unit_id).outerjoin(EquipmentType, EquipmentType.id == EquipmentUnit.type_id).outerjoin(
            BorrowItem, BorrowItem.id == EquipmentReservation.item_id)

    def _summary(self, row):
        report = row[0]
        return {'id':report.id, 'reporterId':report.reporter_id, 'reporter':row.reporter,
                'kind':'room' if report.room_request_id else 'equipment',
                'resource':row.room_name or row.equipment_name+' / '+row.asset_tag,
                'resourceId':report.room_resource_id if report.room_request_id else report.equipment_reservation_id,
                'resourceKey':('room:'+str(report.room_resource_id)) if report.room_request_id else 'equipment:'+str(row.asset_id),
                'bookingId':report.room_request_id or row.loan_id, 'status':report.status, 'category':report.category,
                'priority':report.priority, 'description':report.description, 'response':report.response,
                'created':report.created_at, 'updated':report.updated_at, 'revision':report.revision}

    def list_for(self, actor, scope='mine', status='', category='', kind='', resource=''):
        if scope not in {'mine','managed'} or (status and status not in FEEDBACK_STATES) or (category and category not in FEEDBACK_CATEGORIES) or kind not in {'','room','equipment'}:
            raise FeedbackError('Choose supported report filters.')
        with self.database.transaction(read_only=True) as session:
            self._identity(session, actor)
            query = self._query().where(ResourceFeedback.reporter_id == actor if scope == 'mine' else managed_scope(actor))
            if status:query = query.where(ResourceFeedback.status == status)
            if category:query = query.where(ResourceFeedback.category == category)
            if kind:query = query.where(ResourceFeedback.room_request_id.is_not(None) if kind == 'room' else ResourceFeedback.equipment_reservation_id.is_not(None))
            if resource:
                if not re.fullmatch(r'(room|equipment):[1-9][0-9]*', resource):
                    raise FeedbackError('Choose a valid resource filter.')
                prefix, number = resource.split(':')
                query = query.where(ResourceFeedback.room_resource_id == int(number) if prefix == 'room' else EquipmentReservation.unit_id == int(number))
            return [self._summary(row) for row in session.execute(query.order_by(ResourceFeedback.created_at.desc(),ResourceFeedback.id.desc()).limit(200))]

    def detail(self, key, actor):
        with self.database.transaction(read_only=True) as session:
            report = self._access(session, key, actor)
            row = session.execute(self._query().where(ResourceFeedback.id == key)).one()
            responsible = self._managed(session, report, actor)
            result = self._summary(row)
            try:
                staff = self._responsible(session, report.room_request_id is not None, report.faculty_id)
                staff_name = session.get(User,staff).name
            except FeedbackError:
                staff_name = 'Responsible staff not configured; contact administration.'
            result.update(canManage=responsible, isReporter=report.reporter_id == actor, canAudit=True,
                staff=staff_name, facultyId=report.faculty_id,
                history=event_history(session, FeedbackEvent, key, actor, audit=True))
            return result

    def can_manage(self, actor):
        with self.database.transaction(read_only=True) as session:
            self._identity(session, actor)
            return bool(session.scalar(room_faculties(actor).limit(1)) or session.scalar(custodian_faculties(actor).limit(1)))
