"""Replace a confirmed arrangement only after every required person approves."""

from datetime import datetime, timezone

from sqlalchemy import select

from .group_meeting_rooms import require_meeting_room
from .group_meeting_service import (
    ACTIVE, PENDING, MeetingError, _event, _release, _reserve, assert_slot, required_members, visible_meeting,
)
from .persistence.models import GroupMeeting, GroupMeetingReschedule, GroupMeetingRescheduleDecision, StudentRoomRequest
from .persistence.repository import state_row


def upcoming(meeting):
    return meeting.status == "Confirmed" and meeting.start_at > datetime.now(timezone.utc)


def current_proposal(meeting, proposal):
    return (proposal.status == PENDING and upcoming(meeting) and proposal.source_revision == meeting.revision
            and proposal.start_at > datetime.now(timezone.utc))


def proposals_for(session, meeting_id):
    return list(session.scalars(select(GroupMeetingReschedule)
        .where(GroupMeetingReschedule.meeting_id == meeting_id)
        .order_by(GroupMeetingReschedule.id.desc()).limit(30)))


def decisions_for(session, proposal_id):
    return list(session.scalars(select(GroupMeetingRescheduleDecision)
        .where(GroupMeetingRescheduleDecision.proposal_id == proposal_id)
        .order_by(GroupMeetingRescheduleDecision.user_id)))


def _pending_for(session, meeting_id):
    return session.scalar(select(GroupMeetingReschedule).where(
        GroupMeetingReschedule.meeting_id == meeting_id, GroupMeetingReschedule.status == PENDING))


def supersede_active(session, meeting_id):
    """Close a proposal after another operation changes its confirmed source."""
    pending = _pending_for(session, meeting_id)
    if pending is not None:
        pending.status, pending.resolved_at = "Superseded", datetime.now(timezone.utc)


def _check_slot(session, fixture, meeting, members, roster, start, end, room_id):
    required = required_members(members)
    if not required <= roster.keys():
        raise MeetingError("A required participant is no longer active.")
    if start == meeting.start_at:
        raise MeetingError("Choose a time different from the confirmed arrangement.")
    if meeting.location_mode == "physical":
        if room_id is None or room_id == meeting.room_request_id:
            raise MeetingError("Choose a separate approved room booking for the replacement time.")
        require_meeting_room(session, meeting.organizer_id, room_id, start, end,
                             [member.user_id for member in members], meeting.required_features, lock=True)
        attached = session.scalar(select(GroupMeeting.id).where(
            GroupMeeting.room_request_id == room_id, GroupMeeting.status.in_(ACTIVE)).limit(1))
        if attached is not None:
            raise MeetingError("That approved room booking is already attached to an active meeting.")
    elif room_id is not None:
        raise MeetingError("An online meeting replacement keeps its online location.")
    assert_slot(session, fixture, meeting.organizer_id, required, start, end,
                exclude=(meeting.id,), room_request=room_id)


def propose(session, fixture, actor, roster, meeting_id, revision, start, *, room_id=None,
            submission_key=None, calendar_revision=None):
    state = state_row(session, True)
    meeting, members = visible_meeting(session, meeting_id, actor)
    if meeting.organizer_id != actor:
        raise PermissionError("Only the organizer may propose a replacement.")
    if submission_key:
        existing = session.scalar(select(GroupMeetingReschedule.id).where(
            GroupMeetingReschedule.meeting_id == meeting.id, GroupMeetingReschedule.submission_key == submission_key))
        if existing is not None:
            return existing
    if not upcoming(meeting) or meeting.revision != revision:
        raise MeetingError("The confirmed meeting changed. Refresh it before proposing a replacement.")
    if calendar_revision is not None and calendar_revision != state.calendar_revision:
        raise MeetingError("Calendars or preferences changed. Search again for current options.")
    if not isinstance(start, datetime) or start.tzinfo is None or start.utcoffset() is None:
        raise MeetingError("Choose a valid replacement time.")
    pending = _pending_for(session, meeting.id)
    if pending is not None and current_proposal(meeting, pending):
        raise MeetingError("Withdraw the current proposal before requesting another time.")
    end = start + (meeting.end_at - meeting.start_at)
    _check_slot(session, fixture, meeting, members, roster, start, end, room_id)
    now = datetime.now(timezone.utc)
    if pending is not None:
        pending.status, pending.resolved_at = "Superseded", now
        session.flush()
    proposal = GroupMeetingReschedule(
        meeting_id=meeting.id, source_revision=meeting.revision, original_start_at=meeting.start_at,
        original_end_at=meeting.end_at, original_room_request_id=meeting.room_request_id, start_at=start,
        end_at=end, room_request_id=room_id, status=PENDING, submission_key=submission_key,
    )
    session.add(proposal)
    session.flush()
    session.add_all(GroupMeetingRescheduleDecision(
        proposal_id=proposal.id, user_id=uid, decision="Approved" if uid == actor else "Pending",
        decided_at=now if uid == actor else None) for uid in required_members(members))
    _event(session, meeting, actor, "Replacement time proposed. The confirmed meeting stays in place while required approvals are pending.")
    return proposal.id


def respond(session, fixture, actor, roster, meeting_id, proposal_id, revision, action, *, room_service=None):
    state = state_row(session, True)
    meeting, members = visible_meeting(session, meeting_id, actor)
    proposal = session.get(GroupMeetingReschedule, proposal_id)
    if proposal is None or proposal.meeting_id != meeting.id:
        raise PermissionError("This replacement proposal is private to its meeting participants.")
    voters = decisions_for(session, proposal.id)
    own = next((vote for vote in voters if vote.user_id == actor), None)
    if action not in {"approve", "decline", "withdraw"}:
        raise MeetingError("Choose a supported rescheduling response.")
    if action == "withdraw" and actor != meeting.organizer_id:
        raise PermissionError("Only the organizer may withdraw a replacement proposal.")
    if action != "withdraw" and (own is None or actor == meeting.organizer_id):
        raise PermissionError("Only the invited required participants may approve or decline the replacement.")
    if proposal.source_revision != revision:
        raise MeetingError("Refresh the meeting before responding. The proposal revision changed.")
    if (action == "withdraw" and proposal.status == "Withdrawn"
            or action == "approve" and proposal.status == "Applied" and own.decision == "Approved"
            or action == "decline" and proposal.status == "Declined" and own.decision == "Declined"):
        return
    if proposal.status != PENDING or (action != "withdraw" and not current_proposal(meeting, proposal)):
        raise MeetingError("This proposal is no longer current. Refresh the confirmed meeting before continuing.")
    now = datetime.now(timezone.utc)
    if action == "withdraw":
        proposal.status, proposal.resolved_at = "Withdrawn", now
        _event(session, meeting, actor, "The organizer withdrew the replacement proposal. No calendar change was made.")
        return
    if action == "decline":
        own.decision, own.decided_at = "Declined", now
        session.flush([own])
        proposal.status, proposal.resolved_at = "Declined", now
        _event(session, meeting, actor, "A required participant declined the replacement. The original meeting remains confirmed.")
        return
    if own.decision == "Approved":
        return
    own.decision, own.decided_at = "Approved", now
    if not all(vote.decision == "Approved" for vote in voters):
        _event(session, meeting, actor, "A required participant approved the replacement time. The original meeting remains confirmed.")
        return
    required = required_members(members)
    if {vote.user_id for vote in voters} != required:
        raise MeetingError("The required participant list changed. Propose a new replacement.")
    _check_slot(session, fixture, meeting, members, roster, proposal.start_at, proposal.end_at, proposal.room_request_id)
    prior_booking = session.get(StudentRoomRequest, meeting.room_request_id) if meeting.room_request_id else None
    release_prior = prior_booking is not None and prior_booking.group_participant_ids is not None
    if release_prior and room_service is None:
        raise MeetingError("The prior meeting room could not be released safely. Refresh and try again.")
    session.flush([own])
    _release(session, meeting)
    meeting.start_at, meeting.end_at = proposal.start_at, proposal.end_at
    meeting.room_request_id = proposal.room_request_id
    meeting.revision += 1
    for member in members:
        member.revision = meeting.revision
        if member.side == "optional":
            member.decision = "Invited"
    _reserve(session, meeting, required)
    proposal.status, proposal.resolved_at = "Applied", now
    if release_prior:
        # Faculty already approved the replacement; the original organizer
        # consented when requesting it. Publish the swap and release together.
        session.flush()
        room_service.release_replaced_group_booking(session, prior_booking.id, meeting.organizer_id)
    else:
        state.calendar_revision += 1
    _event(session, meeting, actor, "The replacement is confirmed and calendars were updated. Optional invitees can respond again.",
           notify_actor=True)
