"""Find eligible room/time pairs and link exact faculty-approved reservations."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select

from .account_service import is_research_assistant
from .calendar_service import CalendarError, aware, epoch
from .persistence.models import (LoginAccount, ReservationSeries, Resource, Role, RoomAccess,
    RoomOrganizerCommitment, RoomPolicy, RoomReservation, StudentRoomRequest, User)
from .persistence.repository import state_row
from .room_calendar import room_usage_intervals, valid_approvers


FACILITIES = ("projector", "whiteboard", "computers")
GROUP_ROOM_ROLES = {"Student", "Instructor", "Research Assistant", "Staff", "Administrator"}


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


@dataclass(frozen=True)
class MeetingRoomCandidate:
    room_id: int
    name: str
    building: str
    capacity: int


def _valid_actor_id(value):
    return type(value) is int and 1 <= value < 2**31


def meeting_room_features(features):
    if (not isinstance(features, (tuple, list)) or len(features) > len(FACILITIES)
            or any(not isinstance(value, str) or value not in FACILITIES for value in features)
            or len(set(features)) != len(features)):
        raise MeetingRoomError("Select distinct supported room facilities.")
    return tuple(features)


def group_room_members(session, organizer, participant_ids, *, lock=False):
    """Require an explicit meeting pilot and active login-capable actors."""
    if not session.info.get("group_meeting_pilot"):
        raise PermissionError("The group meeting room pilot is not active.")
    if (not isinstance(participant_ids, (tuple, list)) or not 2 <= len(participant_ids) <= 8
            or not _valid_actor_id(organizer) or any(not _valid_actor_id(person) for person in participant_ids)
            or len(set(participant_ids)) != len(participant_ids) or organizer not in participant_ids):
        raise MeetingRoomError("Select distinct active meeting participants, including the organizer.")
    query = (select(User.id, Role.name, User.assistant_type)
            .join(Role, Role.id == User.primary_role_id).join(LoginAccount, LoginAccount.user_id == User.id)
            .where(User.id.in_(participant_ids), func.lower(User.status) == "active", LoginAccount.enabled.is_(True))
            .order_by(User.id))
    if lock:
        query = query.with_for_update(of=(User, LoginAccount))
    roles = {}
    for user_id, role, assistant_type in session.execute(query):
        role = "Research Assistant" if is_research_assistant(role, assistant_type) else role
        if role in GROUP_ROOM_ROLES:
            roles[user_id] = role
    if set(roles) != set(participant_ids):
        raise MeetingRoomError("One or more selected participants are no longer eligible for the meeting pilot.")
    return roles[organizer]


def allowed_group_rooms(session, organizer, participant_ids, features, *, room_id=None):
    """Project the same live room policies used by preview, submission and approval."""
    approvers = valid_approvers(session)
    query = (select(Resource, RoomPolicy).join(RoomPolicy, RoomPolicy.resource_id == Resource.id)
        .where(Resource.available.is_(True), RoomPolicy.enabled.is_(True), RoomPolicy.categories.contains(["meeting"]),
              Resource.capacity >= len(participant_ids), RoomPolicy.faculty_id.in_(
                  faculty for faculty, approver in approvers.items() if approver != organizer)))
    if room_id is not None:
        query = query.where(Resource.id == room_id)
    for feature in features:
        query = query.where(getattr(Resource, feature).is_(True))
    rooms = list(session.execute(query.order_by(Resource.capacity, Resource.id)))
    restricted = {room.id for room, policy in rooms if policy.restricted}
    allowed = {}
    for key, person in session.execute(select(RoomAccess.resource_id, RoomAccess.user_id)
            .where(RoomAccess.resource_id.in_(restricted), RoomAccess.user_id.in_(participant_ids))):
        allowed.setdefault(key, set()).add(person)
    return [(room, policy, approvers[policy.faculty_id]) for room, policy in rooms
            if not policy.restricted or set(participant_ids) <= allowed.get(room.id, set())]


def meeting_room_candidates(session, organizer, participant_ids, starts, duration, features=()):
    """Offer at most three live candidate rooms per native participant-feasible start."""
    group_room_members(session, organizer, participant_ids)
    features = meeting_room_features(features)
    if type(duration) is not int or not 15 <= duration <= 120 or duration % 15:
        raise MeetingRoomError("Choose a supported meeting duration.")
    now = datetime.now(timezone.utc)
    starts = sorted({aware(start) for start in starts})
    starts = [start for start in starts if start > now]
    if not starts:
        return {}
    rooms = allowed_group_rooms(session, organizer, participant_ids, features)
    if not rooms:
        return {}
    span = timedelta(minutes=duration)
    occupied, unresolved = room_usage_intervals(session, [room.id for room, _, _ in rooms],
        starts[0], starts[-1] + span, state_row(session).active_run_id)
    busy = {}
    for row in occupied:
        busy.setdefault(row["resourceId"], []).append((row["start"], row["end"]))
    eligible = [room for room, _, _ in rooms if room.id not in unresolved]
    result = {}
    for start in starts:
        lower, upper = epoch(start), epoch(start + span)
        choices = [MeetingRoomCandidate(room.id, room.name, room.building, room.capacity) for room in eligible
                   if not any(a < upper and b > lower for a, b in busy.get(room.id, ()))]
        if choices:
            result[start] = choices[:3]
    return result


def _approved_rooms(organizer, *, group_pilot=False):
    request = StudentRoomRequest
    reservation = RoomReservation
    commitment = RoomOrganizerCommitment
    recurring = select(ReservationSeries.id).where(ReservationSeries.room_request_id == request.id).exists()
    organizer_allowed = select(RoomAccess.user_id).where(
        RoomAccess.resource_id == Resource.id, RoomAccess.user_id == organizer).exists()
    organizer_role = and_(Role.name == "Student", request.group_participant_ids.is_(None))
    if group_pilot:
        assistant_kind = func.regexp_replace(func.lower(func.btrim(User.assistant_type)), r"\s+", " ", "g")
        organizer_role = or_(organizer_role, and_(request.group_participant_ids.is_not(None),
            or_(Role.name.in_(GROUP_ROOM_ROLES - {"Research Assistant"}), and_(Role.name == "TeachingAssistant",
                assistant_kind.in_(("research assistant", "research and teaching"))))))
    return (select(request, Resource, RoomPolicy)
            .join(User, User.id == request.organizer_id)
            .join(Role, Role.id == User.primary_role_id)
            .join(LoginAccount, LoginAccount.user_id == User.id)
            .join(Resource, Resource.id == request.resource_id)
            .join(RoomPolicy, RoomPolicy.resource_id == Resource.id)
            .join(reservation, reservation.request_id == request.id)
            .join(commitment, commitment.request_id == request.id)
            .where(
                request.organizer_id == organizer, organizer_role,
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
    """Offer only the organizer's future approved one-time meeting reservations."""
    if not _valid_actor_id(organizer):
        raise MeetingRoomError("Choose an active reservation organizer.")
    query = _approved_rooms(organizer, group_pilot=session.info.get("group_meeting_pilot"))
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
    match = session.execute(_approved_rooms(organizer, group_pilot=session.info.get("group_meeting_pilot")).where(
        StudentRoomRequest.id == request_id, StudentRoomRequest.start_at == start,
        StudentRoomRequest.end_at == end)).one_or_none()
    if match is None:
        raise MeetingRoomError(unavailable)
    approval, resource, policy = match
    if approval.group_participant_ids is not None:
        group_room_members(session, organizer, list(participant_ids), lock=lock)
        if set(approval.group_participant_ids) != set(participant_ids):
            raise MeetingRoomError("Use the same required and optional participants submitted for faculty review.")
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
