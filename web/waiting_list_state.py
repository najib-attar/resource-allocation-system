"""Small shared queue guards and post-commit refresh hooks, not booking rules."""

import logging
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError

from .calendar_service import CalendarError
from .engine_gateway import EngineIntegrationError
from .notification_service import publish_event
from .persistence.database import DatabaseBusy
from .persistence.models import WaitingListEntry, WAITING_ACTIVE, RoomEvent, EquipmentEvent


def linked_entry(session, *, room=None, equipment=None):
    column = WaitingListEntry.room_request_id if room is not None else WaitingListEntry.borrow_request_id
    return session.scalar(select(WaitingListEntry).where(column == (room if room is not None else equipment)))


def guard_waiting(session, *, room=None, equipment=None):
    entry = linked_entry(session, room=room, equipment=equipment)
    if entry and entry.status in WAITING_ACTIVE:
        raise CalendarError('This is an active waiting-list request. Use its waiting-list review or cancel it before revising.')


def queue_event(session, entry, actor, message, *, student_only=False, include_participants=False):
    if entry.room_request_id is not None:
        from .persistence.models import StudentRoomRequest
        parent = session.get(StudentRoomRequest, entry.room_request_id)
        record = RoomEvent(request_id=parent.id, revision=parent.revision, actor_id=actor, message=message)
        reviewer = parent.approver_id
    else:
        from .equipment_access import valid_custodians
        record = EquipmentEvent(request_id=entry.borrow_request_id, faculty_id=entry.faculty_id, actor_id=actor, message=message)
        from .persistence.models import EquipmentCustodian
        reviewer = session.scalar(valid_custodians().where(EquipmentCustodian.faculty_id == entry.faculty_id)
                                  .with_only_columns(EquipmentCustodian.user_id))
    people = {entry.owner_id} if student_only else {entry.owner_id, reviewer} - {None}
    publish_event(session, record, recipient_ids=None if include_participants else people, notify_actor=True)


def close_waiting(session, actor, *, room=None, equipment=None):
    entry = linked_entry(session, room=room, equipment=equipment)
    if entry and entry.status in WAITING_ACTIVE:
        entry.status, entry.explanation = 'Cancelled', 'Withdrawn without penalty; no active queue position remains.'
        queue_event(session, entry, actor, 'Waiting list cancelled. ' + entry.explanation)


def refresh_after_commit(session, database, gateway, kind, faculty, strategy='best_fit', clock=None):
    """Release must commit even if the engine is temporarily unavailable afterwards."""
    key = (kind, faculty)
    pending = session.info.setdefault('waiting_refresh', set())
    if key in pending:
        return
    pending.add(key)

    def refresh(_):
        from .waiting_list_service import WaitingListService
        try:
            WaitingListService(database, gateway, strategy, clock=clock).process(kind, faculty)
        except (CalendarError, EngineIntegrationError, SQLAlchemyError, DatabaseBusy):
            logging.getLogger(__name__).exception('Waiting-list refresh failed after committed availability change; eligible entries remain retryable.')

    event.listen(session, 'after_commit', refresh, once=True)
