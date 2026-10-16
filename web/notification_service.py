"""Private event inbox; no scheduling rules or parsing of lifecycle messages."""

from datetime import datetime, timezone
from sqlalchemy import func, literal, or_, select, union_all, update

from .persistence.models import (Appointment, AppointmentEvent, AppointmentInvitation,
    AppointmentProfessor, Notification, RoomEvent, RoomInvitation, StudentRoomRequest, User)


def publish_event(session, event):
    """Persist history and its recipient notifications in the caller's transaction."""
    if not isinstance(event, (AppointmentEvent, RoomEvent)):
        raise TypeError('Unsupported notification event.')
    session.add(event)
    session.flush()
    if isinstance(event, AppointmentEvent):
        parent = session.get(Appointment, event.appointment_id)
        people = {parent.organizer_id}
        for model in (AppointmentProfessor, AppointmentInvitation):
            people.update(session.scalars(select(model.user_id).where(model.appointment_id == parent.id)))
        source = {'appointment_event_id': event.id}
    else:
        parent = session.get(StudentRoomRequest, event.request_id)
        people = {parent.organizer_id, parent.approver_id}
        people.update(session.scalars(select(RoomInvitation.user_id).where(RoomInvitation.request_id == parent.id)))
        source = {'room_event_id': event.id}
    session.add_all(Notification(recipient_id=person, **source) for person in people if person != event.actor_id)


def _visible(actor):
    appointment_scope = or_(Appointment.organizer_id == actor,
        Appointment.id.in_(select(AppointmentProfessor.appointment_id).where(AppointmentProfessor.user_id == actor)),
        Appointment.id.in_(select(AppointmentInvitation.appointment_id).where(AppointmentInvitation.user_id == actor)))
    room_scope = or_(StudentRoomRequest.organizer_id == actor, StudentRoomRequest.approver_id == actor,
        StudentRoomRequest.id.in_(select(RoomInvitation.request_id).where(RoomInvitation.user_id == actor)))
    appointments = select(Notification.id, Notification.read_at, AppointmentEvent.created_at,
        AppointmentEvent.message, Appointment.purpose.label('subject'), Appointment.id.label('subject_id'),
        literal('appointment').label('kind')).join(AppointmentEvent, AppointmentEvent.id == Notification.appointment_event_id).join(
        Appointment, Appointment.id == AppointmentEvent.appointment_id).where(Notification.recipient_id == actor, appointment_scope)
    rooms = select(Notification.id, Notification.read_at, RoomEvent.created_at, RoomEvent.message,
        StudentRoomRequest.purpose.label('subject'), StudentRoomRequest.id.label('subject_id'),
        literal('room').label('kind')).join(RoomEvent, RoomEvent.id == Notification.room_event_id).join(
        StudentRoomRequest, StudentRoomRequest.id == RoomEvent.request_id).where(Notification.recipient_id == actor, room_scope)
    return union_all(appointments, rooms).subquery()


class NotificationService:
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
            rows = session.execute(select(visible).order_by(visible.c.created_at.desc(), visible.c.id.desc()).limit(limit)).mappings()
            return {'items': [dict(row) for row in rows], 'unreadCount': unread, 'throughId': through}

    def mark_read(self, actor, notification_id=None, through_id=None):
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
                eligible = eligible.where(visible.c.id <= through_id)
            session.execute(update(Notification).where(Notification.id.in_(eligible), Notification.read_at.is_(None)).values(
                read_at=datetime.now(timezone.utc)))
