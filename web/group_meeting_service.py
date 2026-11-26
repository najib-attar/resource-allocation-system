"""Persistent pilot lifecycle. The shared calendar lock serializes confirmations."""

from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from sqlalchemy import delete, select

from .calendar_service import CalendarError, calendar_snapshot, epoch, university_zone
from .group_meeting_preferences import availability_intervals
from .group_meeting_rooms import meeting_room_features, require_meeting_room
from .notification_service import publish_event
from .persistence.models import (GroupMeeting, GroupMeetingAvailability, GroupMeetingCommitment,
    GroupMeetingConsent, GroupMeetingEvent, GroupMeetingParticipant)
from .persistence.repository import state_row


PENDING = "Pending Approval"
ACTIVE = (PENDING, "Confirmed")


class MeetingError(CalendarError):
    pass


def members_for(session, meeting_id):
    return list(session.scalars(select(GroupMeetingParticipant)
        .where(GroupMeetingParticipant.meeting_id == meeting_id).order_by(GroupMeetingParticipant.user_id)))


def consents_for(session, meeting_id):
    return list(session.scalars(select(GroupMeetingConsent)
        .where(GroupMeetingConsent.meeting_id == meeting_id).order_by(GroupMeetingConsent.user_id)))


def visible_meeting(session, meeting_id, actor):
    if not 0 < meeting_id <= 2**63 - 1:
        raise PermissionError("This meeting is private to its participants.")
    meeting = session.get(GroupMeeting, meeting_id)
    members = members_for(session, meeting_id) if meeting else []
    if not any(member.user_id == actor for member in members):
        raise PermissionError("This meeting is private to its participants.")
    return meeting, members


def required_members(members):
    return {member.user_id for member in members if member.side != "optional"}


def hard_windows(session, people, start, end):
    records = {row.owner_id: row for row in session.scalars(select(GroupMeetingAvailability)
        .where(GroupMeetingAvailability.owner_id.in_(people)))}
    zone = university_zone()
    return {uid: availability_intervals(records.get(uid), start, end, zone) for uid in people}, records


def assert_slot(session, fixture, organizer, required, start, end, *, exclude=(), room_request=None):
    if (not fixture.start <= start < end <= fixture.end or start <= datetime.now(timezone.utc)
            or (end - start) not in {timedelta(minutes=n) for n in range(15, 121, 15)}):
        raise MeetingError("Choose a future rehearsal time with a duration of 15 to 120 minutes in 15-minute steps.")
    windows, _ = hard_windows(session, required, start, end)
    if any(not any(a <= start and end <= b for a, b in windows[uid]) for uid in required):
        raise MeetingError("The proposed time is outside one or more required availability windows.")
    duration = int((end - start).total_seconds() // 60)
    facts, _ = calendar_snapshot(session, organizer, sorted(required), [], duration, start, end,
        exclude_group_meetings=exclude, linked_room_request=room_request)
    if set(facts["unresolvedIds"]) & required or any(
            row["start"] < epoch(end) and row["end"] > epoch(start) for row in facts["busy"]):
        raise MeetingError("A required calendar is unavailable or has an overlapping commitment.")


def relocation_target(session, actor, roster, meeting_id, required, revision=None):
    target = session.get(GroupMeeting, meeting_id) if meeting_id and meeting_id <= 2**63 - 1 else None
    if (target is None or target.status != "Confirmed" or target.location_mode != "online" or not target.flexible
            or target.move_target_id is not None
            or target.start_at <= datetime.now(timezone.utc) or (revision is not None and target.revision != revision)):
        raise MeetingError("The flexible meeting is unavailable or its revision changed.")
    affected = required_members(members_for(session, target.id))
    records = {item.owner_id: item for item in session.scalars(select(GroupMeetingAvailability)
        .where(GroupMeetingAvailability.owner_id.in_(affected)))}
    if actor not in affected or not affected <= required or not affected <= roster.keys() or any(
            uid not in records or not records[uid].allow_relocation for uid in affected):
        raise MeetingError("The flexible meeting is unavailable or consent eligibility changed.")
    return target, affected


def _check_arrangement(session, fixture, actor, roster, required, attendees, start, end,
                       *, room_id=None, features=(), move=None):
    if not required <= roster.keys():
        raise MeetingError("A required participant is no longer active.")
    if room_id is not None:
        require_meeting_room(session, actor, room_id, start, end, sorted(attendees), features, lock=True)
    if move is None:
        assert_slot(session, fixture, actor, required, start, end, room_request=room_id)
        return None
    if room_id is not None:
        raise MeetingError("A meeting tied to a room reservation uses a direct option.")
    target_id, revision, replacement = move
    target, affected = relocation_target(session, actor, roster, target_id, required, revision)
    replacement_end = replacement + (target.end_at - target.start_at)
    if not (target.start_at < end and target.end_at > start):
        raise MeetingError("The proposed relocation no longer releases a blocking commitment.")
    if replacement < end and replacement_end > start:
        raise MeetingError("The meeting and proposed replacement overlap.")
    assert_slot(session, fixture, actor, required, start, end, exclude=(target.id,))
    assert_slot(session, fixture, target.organizer_id, affected, replacement, replacement_end, exclude=(target.id,))
    return target, affected, replacement_end


def _event(session, meeting, actor, message, *, notify_actor=False):
    publish_event(session, GroupMeetingEvent(meeting_id=meeting.id, actor_id=actor,
        revision=meeting.revision, message=message), notify_actor=notify_actor)


def submit(session, fixture, actor, roster, *, sides, purpose, start, duration, room_id=None,
           features=(), flexible=False, move=None, submission_key=None, join_url=""):
    state_row(session, True)
    if (not isinstance(purpose, str) or not purpose.strip() or len(purpose) > 2000
            or type(duration) is not int or not 15 <= duration <= 120 or duration % 15):
        raise MeetingError("Enter a short purpose and a supported meeting duration.")
    required = {uid for uid, side in sides.items() if side != "optional"}
    if (sides.get(actor) != "host" or "guest" not in sides.values() or len(sides) > 8
            or not sides.keys() <= roster.keys() or set(sides.values()) - {"host", "guest", "optional"}):
        raise MeetingError("Choose distinct active participants and one or more required guests.")
    features = list(meeting_room_features(features))
    if room_id is None and features or room_id is not None and flexible:
        raise MeetingError("Room facilities belong to a physical meeting, and physical meetings stay fixed.")
    join_url = (join_url or "").strip()
    if join_url:
        try:
            link = urlsplit(join_url)
            if (room_id is not None or len(join_url) > 512 or link.scheme != "https" or not link.hostname
                    or link.username is not None or link.password is not None
                    or any(char.isspace() or ord(char) < 32 or char == "\\" for char in join_url)):
                raise ValueError()
        except ValueError:
            raise MeetingError("Use an HTTPS join link for an online meeting.") from None
    end = start + timedelta(minutes=duration)
    relocation = _check_arrangement(session, fixture, actor, roster, required, set(sides), start, end,
                                    room_id=room_id, features=features, move=move)
    meeting = GroupMeeting(organizer_id=actor, purpose=purpose.strip(), start_at=start, end_at=end,
        revision=1, status=PENDING, location_mode="physical" if room_id else "online",
        room_request_id=room_id, join_url=join_url or None,
        required_features=list(features), flexible=flexible, submission_key=submission_key, **(
            {"move_target_id": move[0], "move_target_revision": move[1], "move_start_at": move[2]} if move else {}))
    session.add(meeting)
    session.flush()
    session.add_all(GroupMeetingParticipant(meeting_id=meeting.id, user_id=uid, side=side, revision=1,
        decision="Approved" if uid == actor else "Invited" if side == "optional" else "Pending")
        for uid, side in sides.items())
    if relocation:
        session.add_all(GroupMeetingConsent(meeting_id=meeting.id, user_id=uid, revision=1, decision="Pending")
                        for uid in relocation[1])
    _event(session, meeting, actor, "Meeting requested. Required approvals are pending." if not move else
           "Meeting requested with a proposed relocation. Required approvals and move consent are pending.")
    return meeting.id


def _reserve(session, meeting, ids):
    session.add_all(GroupMeetingCommitment(meeting_id=meeting.id, user_id=uid,
        start_at=meeting.start_at, end_at=meeting.end_at) for uid in ids)


def _release(session, meeting):
    session.execute(delete(GroupMeetingCommitment).where(GroupMeetingCommitment.meeting_id == meeting.id))


def decide(session, fixture, actor, roster, meeting_id, revision, action):
    state_row(session, True)
    meeting, members = visible_meeting(session, meeting_id, actor)
    own = next(member for member in members if member.user_id == actor)
    if meeting.revision != revision or meeting.status not in ACTIVE or meeting.start_at <= datetime.now(timezone.utc):
        raise MeetingError("Refresh the meeting before responding. The revision or state changed.")
    consents = consents_for(session, meeting.id)
    if action in {"accept-invitation", "decline-invitation"}:
        if own.side != "optional":
            raise PermissionError("Only an optional invitee may respond to this invitation.")
        decision = "Accepted" if action == "accept-invitation" else "Declined"
        if own.decision != decision:
            own.decision = decision
            _event(session, meeting, actor, f"An optional invitee {decision.lower()} the invitation.")
        return
    if meeting.status != PENDING:
        raise MeetingError("This meeting has already been decided.")
    if action in {"approve", "decline"}:
        if own.side == "optional" or meeting.organizer_id == actor:
            raise PermissionError("Only a required invited participant may decide this request.")
        response = own
    elif action in {"consent", "refuse-move"}:
        response = next((row for row in consents if row.user_id == actor), None)
        if response is None:
            raise PermissionError("Only affected required participants may consent to a move.")
    else:
        raise MeetingError("Choose a supported meeting response.")
    decision = "Declined" if action in {"decline", "refuse-move"} else "Approved"
    if response.decision == decision:
        return
    response.decision = decision
    if decision == "Declined":
        meeting.status = "Declined"
        _event(session, meeting, actor, "Relocation declined. The original meeting remains in place." if action == "refuse-move"
               else "A required participant declined. Choose another time or participant set.")
        return
    if not all(p.decision == "Approved" for p in members if p.side != "optional") or not all(
            p.decision == "Approved" and p.revision == revision for p in consents):
        _event(session, meeting, actor, "Move consent recorded." if action == "consent" else "Required approval recorded.")
        return
    move = ((meeting.move_target_id, meeting.move_target_revision, meeting.move_start_at)
            if meeting.move_target_id is not None else None)
    required = required_members(members)
    checked = _check_arrangement(session, fixture, meeting.organizer_id, roster, required,
        {p.user_id for p in members}, meeting.start_at, meeting.end_at,
        room_id=meeting.room_request_id, features=meeting.required_features, move=move)
    if checked:
        target, affected, replacement_end = checked
        if {p.user_id for p in consents} != affected:
            raise MeetingError("The group affected by the move changed. Search again.")
        _release(session, target)
        target.start_at, target.end_at = meeting.move_start_at, replacement_end
        target.revision += 1
        for member in members_for(session, target.id):
            member.revision = target.revision
            if member.side == "optional":
                member.decision = "Invited"
        _reserve(session, target, affected)
        # The target's audience need not know which participant finalized an
        # unrelated new request. Its organizer explicitly consented to this move.
        mover = actor if actor in affected else target.organizer_id
        _event(session, target, mover, "Meeting moved with all affected required consents.", notify_actor=True)
    meeting.status = "Confirmed"
    _reserve(session, meeting, required)
    state_row(session, True).calendar_revision += 1
    _event(session, meeting, actor, "Meeting confirmed after rechecking calendars and approvals.", notify_actor=True)


def revise(session, fixture, actor, roster, meeting_id, revision, start):
    state_row(session, True)
    meeting, members = visible_meeting(session, meeting_id, actor)
    if meeting.organizer_id != actor:
        raise PermissionError("Only the organizer may revise a proposed meeting.")
    if meeting.status != PENDING or meeting.revision != revision or meeting.room_request_id is not None:
        raise MeetingError("Only a current pending online meeting can be revised here.")
    end = start + (meeting.end_at - meeting.start_at)
    if start == meeting.start_at:
        raise MeetingError("Choose a different time for this revision.")
    _check_arrangement(session, fixture, actor, roster, required_members(members),
                       {p.user_id for p in members}, start, end)
    meeting.start_at, meeting.end_at = start, end
    meeting.revision += 1
    meeting.move_target_id = meeting.move_target_revision = meeting.move_start_at = None
    session.execute(delete(GroupMeetingConsent).where(GroupMeetingConsent.meeting_id == meeting.id))
    for member in members:
        member.revision = meeting.revision
        member.decision = "Approved" if member.user_id == actor else "Invited" if member.side == "optional" else "Pending"
    _event(session, meeting, actor, "Organizer proposed a new time. Previous approvals and the move proposal were cleared.")


def cancel(session, actor, meeting_id, revision):
    state_row(session, True)
    meeting, members = visible_meeting(session, meeting_id, actor)
    if actor not in required_members(members):
        raise PermissionError("Only a required participant may cancel.")
    if meeting.revision != revision or meeting.status not in ACTIVE or meeting.start_at <= datetime.now(timezone.utc):
        raise MeetingError("This meeting cannot be cancelled from the current revision.")
    if meeting.status == "Confirmed":
        _release(session, meeting)
        state_row(session, True).calendar_revision += 1
    meeting.status = "Cancelled"
    _event(session, meeting, actor, "Meeting cancelled. Any attached room booking stays with its original organizer.")
