"""Link meeting times to an existing faculty-approved room reservation."""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select

from .calendar_service import CalendarError, aware, epoch
from .persistence.models import (LoginAccount, ReservationSeries, Resource, Role, RoomAccess,
    RoomOrganizerCommitment, RoomPolicy, RoomReservation, StudentRoomRequest, User)
from .persistence.repository import state_row
from .room_calendar import room_usage_intervals


FACILITIES = ("projector", "whiteboard", "computers")


class MeetingRoomError(CalendarError):
    pass


@dataclass(frozen=True)
class MeetingRoom:
    request_id: int
    room_id: int
    name: str
    building: str
    start: datetime
    end: datetime
    capacity: int
    attendee_count: int
    features: tuple[str, ...]


def _valid_actor_id(value):
    return type(value) is int and 1 <= value < 2**31


def meeting_room_features(features):
    if (not isinstance(features, (tuple, list)) or len(features) > len(FACILITIES)
            or any(not isinstance(value, str) or value not in FACILITIES for value in features)
            or len(set(features)) != len(features)):
        raise MeetingRoomError("Select distinct supported room facilities.")
    return tuple(features)


def _approved_rooms(organizer):
    request = StudentRoomRequest
    reservation = RoomReservation
    commitment = RoomOrganizerCommitment
    recurring = select(ReservationSeries.id).where(ReservationSeries.room_request_id == request.id).exists()
    organizer_allowed = select(RoomAccess.user_id).where(
        RoomAccess.resource_id == Resource.id, RoomAccess.user_id == organizer).exists()
    return (select(request, Resource, RoomPolicy)
            .join(User, User.id == request.organizer_id)
            .join(Role, Role.id == User.primary_role_id)
            .join(LoginAccount, LoginAccount.user_id == User.id)
            .join(Resource, Resource.id == request.resource_id)
            .join(RoomPolicy, RoomPolicy.resource_id == Resource.id)
            .join(reservation, reservation.request_id == request.id)
            .join(commitment, commitment.request_id == request.id)
            .where(
                request.organizer_id == organizer, Role.name == "Student",
                func.lower(User.status) == "active", LoginAccount.enabled.is_(True),
                request.status == "Confirmed", request.category == "meeting",
                request.approved_revision == request.revision, request.approved_by == request.approver_id,
                request.start_at > datetime.now(timezone.utc), ~recurring,
                reservation.occurrence_id.is_(None), reservation.resource_id == Resource.id,
                reservation.start_at == request.start_at, reservation.end_at == request.end_at,
                commitment.occurrence_id.is_(None), commitment.user_id == organizer,
                commitment.start_at == request.start_at, commitment.end_at == request.end_at,
                Resource.available.is_(True), RoomPolicy.enabled.is_(True),
                RoomPolicy.faculty_id == request.faculty_id, RoomPolicy.categories.contains(["meeting"]),
                (~RoomPolicy.restricted | organizer_allowed)))


def _meeting_room(request, resource):
    return MeetingRoom(request.id, resource.id, resource.name, resource.building, request.start_at, request.end_at,
                       resource.capacity, request.attendee_count,
                       tuple(feature for feature in FACILITIES
                             if feature in request.required_features and getattr(resource, feature)))


def meeting_room_choices(session, organizer, *, start=None, end=None):
    """Offer only a student's own future approved one-time meeting reservations."""
    if not _valid_actor_id(organizer):
        raise MeetingRoomError("Choose an active reservation organizer.")
    query = _approved_rooms(organizer)
    if start is not None or end is not None:
        start, end = aware(start), aware(end)
        if not epoch(start) < epoch(end):
            raise MeetingRoomError("Use a nonempty room search interval.")
        query = query.where(StudentRoomRequest.start_at >= start, StudentRoomRequest.end_at <= end)
    query = query.order_by(StudentRoomRequest.start_at, StudentRoomRequest.id).limit(100)
    return [_meeting_room(request, resource) for request, resource, _ in session.execute(query)]


def require_meeting_room(session, organizer, request_id, start, end, participant_ids, features=(), *, lock=False):
    """Validate the exact existing room slot. Call under the calendar lock before confirming."""
    start, end = aware(start), aware(end)
    if not epoch(start) < epoch(end):
        raise MeetingRoomError("Use a future, nonempty room interval.")
    if (not _valid_actor_id(organizer) or type(request_id) is not int or not 1 <= request_id < 2**63
            or not isinstance(participant_ids, (tuple, list)) or not 1 <= len(participant_ids) <= 201
            or any(not _valid_actor_id(person) for person in participant_ids)
            or len(set(participant_ids)) != len(participant_ids) or organizer not in participant_ids):
        raise MeetingRoomError("Select an approved room reservation and distinct meeting participants.")
    features = meeting_room_features(features)
    unavailable = "Choose your own approved one-time meeting room for this exact interval."
    if lock:
        # The room aggregate locks this parent before deleting or revising a
        # reservation. Read its child rows only after acquiring that lock.
        owned = session.scalar(select(StudentRoomRequest.id).where(StudentRoomRequest.id == request_id,
            StudentRoomRequest.organizer_id == organizer).with_for_update())
        if owned is None:
            raise MeetingRoomError(unavailable)
    match = session.execute(_approved_rooms(organizer).where(
        StudentRoomRequest.id == request_id, StudentRoomRequest.start_at == start,
        StudentRoomRequest.end_at == end)).one_or_none()
    if match is None:
        raise MeetingRoomError(unavailable)
    approval, resource, policy = match
    room = _meeting_room(approval, resource)
    if len(participant_ids) > min(room.capacity, room.attendee_count):
        raise MeetingRoomError("The room or its approval does not cover the required and optional headcount.")
    if not set(features) <= set(room.features):
        raise MeetingRoomError("The room and its approval must cover every requested facility.")
    if policy.restricted:
        allowed = set(session.scalars(select(RoomAccess.user_id).where(
            RoomAccess.resource_id == room.room_id, RoomAccess.user_id.in_(participant_ids))))
        if not set(participant_ids) <= allowed:
            raise MeetingRoomError("The restricted room must permit all selected participants.")
    busy, unresolved = room_usage_intervals(session, [room.room_id], start, end, state_row(session).active_run_id,
                                            exclude_request=request_id)
    if busy or unresolved:
        raise MeetingRoomError("The approved room conflicts with another protected use or has unresolved availability.")
    return room
