"""Participant-scoped pages for replacing an upcoming confirmed group meeting."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

from flask import Blueprint, current_app, redirect, render_template, request, url_for
from itsdangerous import BadData, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.datastructures import MultiDict

from research.cdmcs.i3c.process import ProcessFailure

from .calendar_service import CalendarError, university_zone
from .cdmcs_rehearsal import RehearsalError, _selection
from .engine_gateway import EngineGateway
from .group_meeting_access import group_session
from .group_meeting_planning import plan
from .group_meeting_reschedule import current_proposal, decisions_for, proposals_for, propose, respond, upcoming
from .group_meeting_rooms import meeting_room_choices
from .group_meeting_routes import _identifier, _login_key
from .group_meeting_service import ACTIVE, PENDING, MeetingError, assert_slot, required_members, visible_meeting
from .persistence.database import DatabaseBusy
from .persistence.models import ApplicationState, GroupMeeting, Resource, StudentRoomRequest
from .persistence.repository import state_row
from .room_request_service import RoomRequestService


def _ticket():
    return URLSafeTimedSerializer(current_app.secret_key, salt="confirmed-group-meeting-replacement-v1")


def _calendar_revision(session):
    return session.scalar(select(ApplicationState.calendar_revision).where(ApplicationState.id == 1))


def _room_service(fixture):
    return RoomRequestService(fixture.database,
        EngineGateway(Path(current_app.root_path).parent, current_app.config["BACKEND_TIMEOUT"], current_app.logger),
        current_app.config["ROOM_SELECTION_STRATEGY"])


def _room_names(session, proposals):
    room_ids = {room_id for proposal in proposals
                for room_id in (proposal.original_room_request_id, proposal.room_request_id) if room_id is not None}
    if not room_ids:
        return {}
    return dict(session.execute(select(StudentRoomRequest.id, Resource.name)
        .join(Resource, Resource.id == StudentRoomRequest.resource_id)
        .where(StudentRoomRequest.id.in_(room_ids))).all())


def register_group_meeting_reschedule(app, fixture):
    blueprint = Blueprint("group_meeting_reschedule", __name__, url_prefix="/meetings")

    @blueprint.errorhandler(PermissionError)
    def private(_):
        return render_template("workspace_error.html", status=403,
            message="This rescheduling action is private or belongs to another participant.",
            recovery=("group_meetings.index", "Group meetings")), 403

    @blueprint.errorhandler(CalendarError)
    @blueprint.errorhandler(RehearsalError)
    def conflict(exc):
        return render_template("workspace_error.html", status=409, message=str(exc),
            recovery=("group_meetings.index", "Group meetings")), 409

    @blueprint.errorhandler(ValueError)
    @blueprint.errorhandler(DatabaseBusy)
    @blueprint.errorhandler(ProcessFailure)
    @blueprint.errorhandler(SQLAlchemyError)
    def unavailable(_):
        return render_template("workspace_error.html", status=409,
            message="The replacement could not be verified. Refresh the meeting and try another search.",
            recovery=("group_meetings.index", "Group meetings")), 409

    @blueprint.route("/<int:meeting_id>/reschedule", methods=["GET", "POST"])
    def detail(meeting_id):
        zone = university_zone()
        first = max(fixture.start, datetime.now(timezone.utc)).astimezone(zone).date()
        last = (fixture.end - timedelta(minutes=1)).astimezone(zone).date()
        dates = {"fromDate": first.isoformat(), "untilDate": last.isoformat(), "preferredStart": "", "roomId": ""}
        result, rooms = None, []
        booking = None
        find_room = False
        with group_session(fixture) as (db, actor, roster):
            meeting, members = visible_meeting(db, meeting_id, actor)
            proposals = proposals_for(db, meeting.id)
            pending = next((item for item in proposals if item.status == PENDING), None)
            current = pending is not None and current_proposal(meeting, pending)
            can_search = actor == meeting.organizer_id and upcoming(meeting) and not current and first <= last
            votes = decisions_for(db, pending.id) if pending else []
            own = next((vote for vote in votes if vote.user_id == actor and actor != meeting.organizer_id), None)
            if can_search and meeting.location_mode == "physical":
                attached = set(db.scalars(select(GroupMeeting.room_request_id).where(
                    GroupMeeting.room_request_id.is_not(None), GroupMeeting.status.in_(ACTIVE))))
                rooms = [room for room in meeting_room_choices(db, actor)
                         if room.request_id not in attached and room.end - room.start == meeting.end_at - meeting.start_at
                         and len(members) <= min(room.capacity, room.attendee_count)
                         and set(meeting.required_features) <= set(room.features)]
                booking_id = _identifier(request.args.get("booking"), optional=True)
                if booking_id is not None:
                    booking = db.scalar(select(StudentRoomRequest).where(StudentRoomRequest.id == booking_id,
                        StudentRoomRequest.organizer_id == actor,
                        StudentRoomRequest.group_participant_ids == sorted(member.user_id for member in members)))
                    if booking is not None and any(room.request_id == booking.id for room in rooms):
                        dates["roomId"] = str(booking.id)
            if request.method == "POST":
                if actor != meeting.organizer_id:
                    raise PermissionError("Only the organizer may search for a replacement.")
                if not can_search or _identifier(request.form.get("revision")) != meeting.revision:
                    raise MeetingError("Refresh the confirmed meeting before searching for a replacement.")
                for key in dates:
                    dates[key] = request.form.get(key, "")
                room_id = _identifier(dates["roomId"], optional=True)
                if room_id is not None and meeting.location_mode == "physical" and room_id not in {
                        room.request_id for room in rooms}:
                    raise MeetingError("Choose your approved room booking for the replacement time.")
                if meeting.location_mode == "online" and room_id is not None:
                    raise MeetingError("This replacement keeps the online meeting location.")
                find_room = meeting.location_mode == "physical" and room_id is None
                fields = MultiDict(dates)
                fields["duration"] = str(int((meeting.end_at - meeting.start_at).total_seconds() // 60))
                for member in members:
                    if member.user_id == actor or (member.side == "optional" and member.user_id not in roster
                                                  and meeting.location_mode == "online"):
                        continue
                    fields.add({"host": "cohostIds", "guest": "requiredIds", "optional": "optionalIds"}[member.side],
                               str(member.user_id))
                selection = _selection(fields, actor, roster, fixture)
                revision = _calendar_revision(db)
                if not fixture.admission.acquire(blocking=False):
                    raise MeetingError("Another search is running. Retry shortly.")
                try:
                    result, _, _ = plan(db, fixture, actor, roster, selection, room_id, meeting.required_features,
                                        replace_meeting=meeting, find_room=find_room)
                finally:
                    fixture.admission.release()
                signer = _ticket()
                for option in result:
                    candidate = option.get("candidate_room")
                    option["ticket"] = signer.dumps({"actor": actor, "login": _login_key(), "meeting": meeting.id,
                        "revision": meeting.revision, "start": option["start"].isoformat(), "room": room_id,
                        "calendar": revision, "candidate_room": candidate.room_id if candidate else None})
            return render_template("group_meeting_reschedule.html", meeting=meeting, actor=actor, roster=roster,
                proposals=proposals, pending=pending, current=current, votes=votes, own=own, can_search=can_search,
                rooms=rooms, room_names=_room_names(db, proposals), results=result, first=first, last=last,
                dates=dates, zone=zone.key, booking=booking, find_room=find_room)

    @blueprint.post("/<int:meeting_id>/reschedule/request")
    def create(meeting_id):
        raw = request.form.get("ticket", "")
        try:
            if not 1 <= len(raw) <= 4096:
                raise BadData("Invalid ticket length")
            value = _ticket().loads(raw, max_age=900)
        except BadData:
            raise MeetingError("Search again. The selected replacement expired or is invalid.") from None
        with group_session(fixture, write=True) as (db, actor, roster):
            if value["actor"] != actor or value["login"] != _login_key() or value["meeting"] != meeting_id:
                raise PermissionError("The replacement belongs to another session or meeting.")
            start, digest = datetime.fromisoformat(value["start"]), sha256(raw.encode("utf-8")).hexdigest()
            if value["candidate_room"] is not None:
                return request_candidate(db, actor, roster, meeting_id, value, start, digest)
            propose(db, fixture, actor, roster, meeting_id, value["revision"], start,
                    room_id=value["room"], submission_key=digest, calendar_revision=value["calendar"])
        return redirect(url_for("group_meeting_reschedule.detail", meeting_id=meeting_id))

    def request_candidate(db, actor, roster, meeting_id, value, start, digest):
        state = state_row(db, True)
        meeting, members = visible_meeting(db, meeting_id, actor)
        if actor != meeting.organizer_id:
            raise PermissionError("Only the organizer may request a replacement room.")
        previous = db.scalar(select(StudentRoomRequest.id).where(
            StudentRoomRequest.organizer_id == actor, StudentRoomRequest.group_submission_key == digest))
        if previous is None:
            if (meeting.location_mode != "physical" or not upcoming(meeting) or meeting.revision != value["revision"]
                    or any(current_proposal(meeting, proposal) for proposal in proposals_for(db, meeting.id))):
                raise MeetingError("Refresh the current physical meeting before requesting another room.")
            if state.calendar_revision != value["calendar"]:
                raise MeetingError("Calendars or preferences changed. Search again for current options.")
            required = required_members(members)
            if not required <= roster.keys():
                raise MeetingError("A required participant is no longer active.")
            end = start + (meeting.end_at - meeting.start_at)
            assert_slot(db, fixture, actor, required, start, end)
            previous = _room_service(fixture).submit_group_meeting(db, actor, purpose=meeting.purpose,
                start=start, duration=int((end - start).total_seconds() // 60),
                participant_ids=[member.user_id for member in members], features=meeting.required_features,
                room_id=value["candidate_room"], submission_key=digest)
        return redirect(url_for("group_meeting_reschedule.detail", meeting_id=meeting_id, booking=previous), code=303)

    @blueprint.post("/<int:meeting_id>/reschedule/<int:proposal_id>/response")
    def response(meeting_id, proposal_id):
        with group_session(fixture, write=True) as (db, actor, roster):
            respond(db, fixture, actor, roster, meeting_id, _identifier(proposal_id),
                    _identifier(request.form.get("revision")), request.form.get("action"),
                    room_service=_room_service(fixture))
        return redirect(url_for("group_meeting_reschedule.detail", meeting_id=meeting_id))

    @blueprint.after_request
    def private_cache(response):
        response.headers["Cache-Control"] = "private, no-store"
        return response

    app.register_blueprint(blueprint)
