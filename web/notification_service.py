"""Private event inbox; no scheduling rules or parsing of lifecycle messages."""

from datetime import datetime, timezone
from sqlalchemy import String, case, cast, func, literal, or_, select, union_all, update
from sqlalchemy.orm import aliased
from .equipment_access import custodian_faculties
from .feedback_access import visible_scope
from .recurring_records import dated_occurrences
from .reservation_policy import occurrence_summary

from .persistence.models import (Appointment, AppointmentEvent, AppointmentInvitation,
    AppointmentProfessor, Notification, RoomEvent, RoomInvitation, StudentRoomRequest, User,
    BorrowRequest, EquipmentCustodian, EquipmentEvent, WaitingListEntry, FeedbackEvent, ResourceFeedback,
    EligibilityEvent, LoginAccount, RequestEligibility, ResourceRequest, Role)


INBOX_KINDS = {
    'all': 'All services',
    'appointment': 'Appointments',
    'room': 'Rooms',
    'equipment': 'Equipment',
    'feedback': 'Feedback',
    'eligibility': 'Academic eligibility',
}
INBOX_READ_STATES = {'all': 'All updates', 'unread': 'Unread only', 'read': 'Read only'}


def _filters(visible, kind, read_state):
    if kind not in INBOX_KINDS or read_state not in INBOX_READ_STATES:
        raise ValueError('Choose an available service and read status.')
    clauses = []
    if kind != 'all':
        clauses.append(visible.c.kind == kind)
    if read_state == 'unread':
        clauses.append(visible.c.read_at.is_(None))
    elif read_state == 'read':
        clauses.append(visible.c.read_at.is_not(None))
    return clauses


def publish_event(session, event, *, recipient_ids=None, notify_actor=False):
    """Persist history and its recipient notifications in the caller's transaction."""
    if not isinstance(event, (AppointmentEvent, RoomEvent, EquipmentEvent, FeedbackEvent)):
        raise TypeError('Unsupported notification event.')
    session.add(event)
    session.flush()
    if isinstance(event, AppointmentEvent):
        parent = session.get(Appointment, event.appointment_id)
        people = {parent.organizer_id}
        for model in (AppointmentProfessor, AppointmentInvitation):
            people.update(session.scalars(select(model.user_id).where(model.appointment_id == parent.id)))
        source = {'appointment_event_id': event.id}
    elif isinstance(event, RoomEvent):
        parent = session.get(StudentRoomRequest, event.request_id)
        people = {parent.organizer_id, parent.approver_id}
        people.update(session.scalars(select(RoomInvitation.user_id).where(RoomInvitation.request_id == parent.id)))
        source = {'room_event_id': event.id}
    elif isinstance(event, EquipmentEvent):
        parent = session.get(BorrowRequest, event.request_id)
        people = {parent.borrower_id}
        assignment = session.get(EquipmentCustodian, parent.faculty_id)
        if assignment:
            people.add(assignment.user_id)
        source = {'equipment_event_id': event.id}
    else:
        # Reports have a private audience, never all members of the booking.
        if recipient_ids is None:
            raise ValueError('Feedback notifications require explicit authorized recipients.')
        people = set()
        source = {'feedback_event_id': event.id}
    if recipient_ids is not None:
        people = set(recipient_ids)
    session.add_all(Notification(recipient_id=person, **source) for person in people if notify_actor or person != event.actor_id)


def event_history(session, model, parent_id, actor, *, audit=False):
    """Project personal updates or staff audit after authorizing the parent."""
    parent, source = {
        AppointmentEvent: (AppointmentEvent.appointment_id, Notification.appointment_event_id),
        RoomEvent: (RoomEvent.request_id, Notification.room_event_id),
        EquipmentEvent: (EquipmentEvent.request_id, Notification.equipment_event_id),
        FeedbackEvent: (FeedbackEvent.report_id, Notification.feedback_event_id),
    }[model]
    query = select(model).where(parent == parent_id)
    if not audit:
        query = query.where(or_(model.actor_id == actor,
            model.id.in_(select(source).where(Notification.recipient_id == actor))))
    events = list(session.scalars(query.order_by(model.id)))
    if not events:
        return []
    if not audit:
        return [{'id': event.id, 'message': event.message, 'at': event.created_at,
                 'ownAction': event.actor_id == actor} for event in events]
    recipients = {}
    for event_id, person_id, name in session.execute(
            select(source, User.id, User.name).join(User, User.id == Notification.recipient_id)
            .where(source.in_([event.id for event in events])).order_by(Notification.id)):
        recipients.setdefault(event_id, []).append({'id': person_id, 'name': name})
    actors = {person.id: person.name for person in session.scalars(
        select(User).where(User.id.in_({event.actor_id for event in events})))}
    return [{'id': event.id, 'message': event.message, 'at': event.created_at,
             'actorId': event.actor_id, 'actor': actors[event.actor_id],
             'recipients': recipients.get(event.id, []), 'revision': getattr(event, 'revision', None),
             'unitId': getattr(event, 'unit_id', None)} for event in events]


def _visible(actor):
    appointment_scope = or_(Appointment.organizer_id == actor,
        Appointment.id.in_(select(AppointmentProfessor.appointment_id).where(AppointmentProfessor.user_id == actor)),
        Appointment.id.in_(select(AppointmentInvitation.appointment_id).where(AppointmentInvitation.user_id == actor)))
    room_scope = or_(StudentRoomRequest.organizer_id == actor, StudentRoomRequest.approver_id == actor,
        StudentRoomRequest.id.in_(select(RoomInvitation.request_id).where(RoomInvitation.user_id == actor)))
    appointments = select(Notification.id, Notification.read_at, AppointmentEvent.created_at,
        AppointmentEvent.message, Appointment.purpose.label('subject'), Appointment.id.label('subject_id'),
        literal('appointment').label('kind'), AppointmentEvent.actor_id, Notification.recipient_id,
        Appointment.status.label('current_status'), literal(0).label('review_version')).join(AppointmentEvent, AppointmentEvent.id == Notification.appointment_event_id).join(
        Appointment, Appointment.id == AppointmentEvent.appointment_id).where(Notification.recipient_id == actor, appointment_scope)
    rooms = select(Notification.id, Notification.read_at, RoomEvent.created_at, RoomEvent.message,
        StudentRoomRequest.purpose.label('subject'), StudentRoomRequest.id.label('subject_id'),
        literal('room').label('kind'), RoomEvent.actor_id, Notification.recipient_id,
        case((WaitingListEntry.status.in_(['Pending Review', 'Preapproved']),
            literal('Waiting list: ') + WaitingListEntry.status),
            else_=StudentRoomRequest.status).label('current_status'), literal(0).label('review_version')).join(RoomEvent, RoomEvent.id == Notification.room_event_id).join(
        StudentRoomRequest, StudentRoomRequest.id == RoomEvent.request_id).outerjoin(
        WaitingListEntry, WaitingListEntry.room_request_id == StudentRoomRequest.id).where(Notification.recipient_id == actor, room_scope)
    authorized_faculties = custodian_faculties(actor)
    equipment_scope = or_(BorrowRequest.borrower_id == actor, BorrowRequest.faculty_id.in_(authorized_faculties))
    equipment = select(Notification.id, Notification.read_at, EquipmentEvent.created_at, EquipmentEvent.message,
        BorrowRequest.purpose.label('subject'), BorrowRequest.id.label('subject_id'), literal('equipment').label('kind'),
        EquipmentEvent.actor_id, Notification.recipient_id,
        case((WaitingListEntry.status.in_(['Pending Review', 'Preapproved']),
            literal('Waiting list: ') + WaitingListEntry.status),
            else_=BorrowRequest.status).label('current_status'), literal(0).label('review_version')).join(
        EquipmentEvent, EquipmentEvent.id == Notification.equipment_event_id).join(
        BorrowRequest, BorrowRequest.id == EquipmentEvent.request_id).outerjoin(
        WaitingListEntry, WaitingListEntry.borrow_request_id == BorrowRequest.id).where(Notification.recipient_id == actor, equipment_scope)
    feedback = select(Notification.id, Notification.read_at, FeedbackEvent.created_at,
        literal('A private resource report has an update. Open it to review.').label('message'),
        literal('Resource feedback').label('subject'), ResourceFeedback.id.label('subject_id'),
        literal('feedback').label('kind'), FeedbackEvent.actor_id, Notification.recipient_id,
        ResourceFeedback.status.label('current_status'), literal(0).label('review_version')).join(FeedbackEvent, FeedbackEvent.id == Notification.feedback_event_id).join(
        ResourceFeedback, ResourceFeedback.id == FeedbackEvent.report_id).where(Notification.recipient_id == actor, visible_scope(actor))
    instructor = select(User.id).join(LoginAccount, LoginAccount.user_id == User.id).join(
        Role, Role.id == User.primary_role_id).where(User.id == actor, User.status.ilike('active'),
        LoginAccount.enabled.is_(True), Role.name == 'Instructor')
    eligibility = select(Notification.id, Notification.read_at, EligibilityEvent.created_at,
        (EligibilityEvent.status + ' for request revision ' + cast(EligibilityEvent.request_revision, String)
         + '. Open the recorded reason.').label('message'),
        ResourceRequest.title.label('subject'), ResourceRequest.id.label('subject_id'),
        literal('eligibility').label('kind'), EligibilityEvent.actor_id, Notification.recipient_id,
        RequestEligibility.status.label('current_status'), EligibilityEvent.version.label('review_version')).join(
        EligibilityEvent, EligibilityEvent.id == Notification.eligibility_event_id).join(
        ResourceRequest, ResourceRequest.id == EligibilityEvent.request_id).join(
        RequestEligibility, RequestEligibility.request_id == ResourceRequest.id).where(
        Notification.recipient_id == actor, ResourceRequest.requester_id.in_(instructor),
        EligibilityEvent.origin == 'Professor', EligibilityEvent.status.in_(('Eligible', 'Eligibility Rejected')))
    return union_all(appointments, rooms, equipment, feedback, eligibility).subquery()


class NotificationService:
    PAGE_SIZE = 30

    def __init__(self, database):
        self.database = database

    def _identity(self, session, actor):
        user = session.get(User, actor) if type(actor) is int and actor > 0 else None
        if user is None or user.status.casefold() != 'active':
            raise PermissionError('An active university identity is required.')

    def inbox(self, actor, limit=20):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('Use a bounded notification count.')
        with self.database.transaction(read_only=True) as session:
            self._identity(session, actor)
            visible = _visible(actor)
            unread = session.scalar(select(func.count()).select_from(visible).where(visible.c.read_at.is_(None)))
            through = session.scalar(select(func.max(visible.c.id))) or 0
            return {'items': self._items(session, visible, (), limit), 'unreadCount': unread, 'throughId': through}

    @staticmethod
    def _items(session, visible, clauses, limit):
        sender, recipient = aliased(User), aliased(User)
        rows = session.execute(select(visible, sender.name.label('sender_name'), recipient.name.label('recipient_name'))
            .join(sender, sender.id == visible.c.actor_id).join(recipient, recipient.id == visible.c.recipient_id)
            .where(*clauses).order_by(visible.c.created_at.desc(), visible.c.id.desc()).limit(limit)).mappings()
        items = [dict(row) for row in rows]
        for kind in ('room', 'equipment'):
            series = dated_occurrences(session, kind, {r['subject_id'] for r in items if r['kind'] == kind})
            for row in items:
                if row['kind'] == kind and row['subject_id'] in series:
                    row['current_status'] = occurrence_summary(series[row['subject_id']])
        return items

    def inbox_page(self, actor, *, kind='all', read_state='all', before=None):
        if before is not None and (type(before) is not int or not 1 <= before <= 9223372036854775807):
            raise ValueError('This page of Inbox history is unavailable.')
        with self.database.transaction(read_only=True) as session:
            self._identity(session, actor)
            visible = _visible(actor)
            clauses = _filters(visible, kind, read_state)
            unread, through_id = session.execute(select(func.count(), func.max(visible.c.id)).where(
                *clauses, visible.c.read_at.is_(None))).one()
            if before is not None:
                # A read-state change may remove the anchor from the filter, while
                # the recipient's authorized timestamp still anchors navigation.
                anchor = session.execute(select(visible.c.created_at, visible.c.id)
                    .where(visible.c.id == before)).one_or_none()
                if anchor is None:
                    raise ValueError('This page of Inbox history is unavailable.')
                clauses.append(or_(visible.c.created_at < anchor.created_at,
                    (visible.c.created_at == anchor.created_at) & (visible.c.id < anchor.id)))
            items = self._items(session, visible, clauses, self.PAGE_SIZE + 1)
            next_before = items[self.PAGE_SIZE - 1]['id'] if len(items) > self.PAGE_SIZE else None
            return dict(items=items[:self.PAGE_SIZE], unreadCount=unread, throughId=through_id or 0,
                        nextBefore=next_before, before=before, kind=kind, readState=read_state)

    def mark_read(self, actor, notification_id=None, through_id=None, *, kind='all', read_state='all'):
        if (notification_id is None) == (through_id is None):
            raise ValueError('Choose a notification or a displayed inbox boundary.')
        key = notification_id if notification_id is not None else through_id
        if type(key) is not int or not 0 <= key <= 9223372036854775807:
            raise ValueError('Invalid notification identifier.')
        with self.database.transaction() as session:
            self._identity(session, actor)
            visible = _visible(actor)
            eligible = select(visible.c.id)
            if notification_id is not None:
                eligible = eligible.where(visible.c.id == notification_id)
                if session.scalar(eligible) is None:
                    raise PermissionError('This notification is unavailable or private.')
            else:
                eligible = eligible.where(visible.c.id <= through_id, *_filters(visible, kind, read_state))
            session.execute(update(Notification).where(Notification.id.in_(eligible), Notification.read_at.is_(None)).values(
                read_at=datetime.now(timezone.utc)))
