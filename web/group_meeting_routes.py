"""Opt-in pages for participant-scoped meeting requests and decisions."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

from flask import Blueprint, current_app, redirect, render_template, request, session as login_session, url_for
from itsdangerous import BadData, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from research.cdmcs.i3c.process import ProcessFailure

from .calendar_service import CalendarError, local_instant, university_zone
from .cdmcs_rehearsal import FIXTURE_EXTENSION, _selection
from .engine_gateway import EngineGateway, EngineIntegrationError
from .group_meeting_access import group_session
from .group_meeting_planning import plan
from .group_meeting_rooms import meeting_room_choices, meeting_room_features
from .group_meeting_service import (
    ACTIVE, PENDING, MeetingError, cancel, check_pending_relocation, consents_for, decide, revise, submit, visible_meeting,
)
from .persistence.database import DatabaseBusy
from .persistence.models import GroupMeeting, GroupMeetingEvent, GroupMeetingParticipant, Resource, StudentRoomRequest
from .persistence.repository import state_row
from .room_request_service import RoomRequestService


def _ticket():
    return URLSafeTimedSerializer(current_app.secret_key, salt="group-meeting-plan-v1")


def _login_key():
    return sha256(login_session["csrf"].encode("utf-8")).hexdigest()


def _identifier(value, *, optional=False):
    if not value and optional:
        return None
    try:
        number = int(value)
    except (ValueError, TypeError):
        raise MeetingError("Choose a valid record or revision.") from None
    if not 0 < number <= 2**63 - 1:
        raise MeetingError("Choose a valid record or revision.")
    return number


def _future(meeting):
    return meeting.start_at > datetime.now(timezone.utc)


def register_group_meetings(app, fixture):
    """Bind the pilot to the exact database object provisioned by the demo launcher."""
    if app.extensions.get(FIXTURE_EXTENSION) is not fixture:
        raise RuntimeError("The generalized meeting pilot requires the isolated rehearsal.")
    fixture.database.sessions.configure(info={"group_meeting_pilot": True})
    blueprint = Blueprint("group_meetings", __name__, url_prefix="/meetings")

    @blueprint.errorhandler(PermissionError)
    def private(_):
        return render_template("workspace_error.html", status=403,
            message="This meeting action is private or belongs to another participant.",
            recovery=("group_meetings.index", "Group meetings")), 403

    @blueprint.errorhandler(CalendarError)
    def conflict(error):
        return render_template("workspace_error.html", status=409, message=str(error),
            recovery=("group_meetings.index", "Group meetings")), 409

    @blueprint.errorhandler(ValueError)
    @blueprint.errorhandler(DatabaseBusy)
    @blueprint.errorhandler(ProcessFailure)
    @blueprint.errorhandler(EngineIntegrationError)
    @blueprint.errorhandler(SQLAlchemyError)
    def unavailable(_):
        return render_template("workspace_error.html", status=409,
            message="The proposed arrangement could not be verified. Refresh and try another search.",
            recovery=("group_meetings.index", "Group meetings")), 409

    @blueprint.get("/")
    def index():
        with group_session(fixture) as (db, actor, _):
            meetings = db.execute(select(GroupMeeting, GroupMeetingParticipant)
                .join(GroupMeetingParticipant).where(GroupMeetingParticipant.user_id == actor)
                .order_by(GroupMeeting.start_at.desc(), GroupMeeting.id.desc()).limit(100)).all()
            return render_template("group_meeting_list.html", meetings=meetings)

    @blueprint.route("/new", methods=["GET", "POST"])
    def new():
        zone = university_zone()
        first = fixture.start.astimezone(zone).date()
        last = (fixture.end - timedelta(minutes=1)).astimezone(zone).date()
        data = {"cohostIds": [], "requiredIds": [], "optionalIds": [], "fromDate": first.isoformat(),
                "untilDate": last.isoformat(), "duration": 30, "preferredStart": "", "roomId": "",
                "findRoom": False, "features": []}
        result = None
        with group_session(fixture) as (db, actor, roster):
            people = sorted((person for uid, person in roster.items() if uid != actor), key=lambda value: value["name"])
            attached = set(db.scalars(select(GroupMeeting.room_request_id).where(GroupMeeting.organizer_id == actor,
                GroupMeeting.room_request_id.is_not(None), GroupMeeting.status.in_(ACTIVE))))
            rooms = [item for item in meeting_room_choices(db, actor) if item.request_id not in attached]
            if request.method == "GET" and request.args.get("booking"):
                booking = next((item for item in rooms
                                if item.request_id == _identifier(request.args["booking"])), None)
                if booking is None:
                    raise MeetingError("Choose one of your approved and unused meeting room bookings.")
                approval = db.get(StudentRoomRequest, booking.request_id)
                data.update(roomId=booking.request_id, duration=int((booking.end - booking.start).total_seconds() // 60),
                    fromDate=booking.start.astimezone(zone).date().isoformat(),
                    untilDate=booking.end.astimezone(zone).date().isoformat(), features=list(booking.features),
                    requiredIds=[uid for uid in approval.group_participant_ids or () if uid != actor and uid in roster])
            if request.method == "GET" and request.args.get("retry"):
                old, members = visible_meeting(db, _identifier(request.args.get("retry")), actor)
                if old.organizer_id != actor:
                    raise PermissionError("Only the organizer may reuse this request.")
                for side, field in (("host", "cohostIds"), ("guest", "requiredIds"), ("optional", "optionalIds")):
                    data[field] = [p.user_id for p in members if p.side == side and p.user_id != actor and p.user_id in roster]
                data["duration"] = int((old.end_at - old.start_at).total_seconds() // 60)
            if request.method == "POST":
                selection = _selection(request.form, actor, roster, fixture)
                for key in ("cohostIds", "requiredIds", "optionalIds"):
                    data[key] = list(map(int, request.form.getlist(key)))
                for key in ("fromDate", "untilDate", "duration", "preferredStart", "roomId"):
                    data[key] = request.form.get(key, "")
                data["findRoom"] = data["roomId"] == "find"
                room = None if data["findRoom"] else _identifier(data["roomId"], optional=True)
                if room in attached:
                    raise MeetingError("That room booking already belongs to an active group meeting.")
                data["features"] = list(meeting_room_features(request.form.getlist("features")))
                if room is None and not data["findRoom"] and data["features"]:
                    raise MeetingError("Select a room option for the required facilities.")
                if not fixture.admission.acquire(blocking=False):
                    raise MeetingError("Another search is running. Retry shortly.")
                try:
                    direct, moves, room_view = plan(db, fixture, actor, roster, selection, room, data["features"],
                        find_room=data["findRoom"])
                finally:
                    fixture.admission.release()
                sides = {actor: "host", **dict.fromkeys(data["cohostIds"], "host"),
                    **dict.fromkeys(data["requiredIds"], "guest"), **dict.fromkeys(data["optionalIds"], "optional")}
                context = {"actor": actor, "login": _login_key(), "sides": list(sides.items()),
                    "duration": selection[2], "room": room, "features": data["features"],
                    "calendar": state_row(db).calendar_revision}
                for option in direct + moves:
                    candidate = option.get("candidate_room")
                    option["ticket"] = _ticket().dumps({**context, "start": option["start"].isoformat(),
                        "move": option["move"], "candidate_room": candidate.room_id if candidate else None})
                result = {"direct": direct, "moves": moves, "room": room_view,
                          "relationship": f"{1 + len(data['cohostIds'])} to {len(data['requiredIds'])}"}
        return render_template("group_meeting_new.html", form=data, people=people,
                               rooms=rooms, result=result, first=first, last=last, zone=zone.key)

    @blueprint.post("/submit")
    def create():
        raw = request.form.get("ticket", "")
        try:
            if not 1 <= len(raw) <= 4096:
                raise BadData("Invalid ticket length")
            value = _ticket().loads(raw, max_age=900)
        except BadData:
            raise MeetingError("Search again. The selected recommendation expired or is invalid.") from None
        with group_session(fixture, write=True) as (db, actor, roster):
            if value["actor"] != actor or value["login"] != _login_key():
                raise PermissionError("The recommendation belongs to another session.")
            digest = sha256(raw.encode("utf-8")).hexdigest()
            candidate = value.get("candidate_room")
            if candidate:
                previous = db.scalar(select(StudentRoomRequest.id).where(
                    StudentRoomRequest.organizer_id == actor, StudentRoomRequest.group_submission_key == digest))
                if previous:
                    return redirect(url_for("rooms.detail", request_id=previous), code=303)
            existing = db.scalar(select(GroupMeeting.id).where(
                GroupMeeting.organizer_id == actor, GroupMeeting.submission_key == digest))
            if existing:
                return redirect(url_for("group_meetings.detail", meeting_id=existing))
            if value["calendar"] != state_row(db, True).calendar_revision:
                raise MeetingError("Calendars or preferences changed. Search again for current options.")
            if candidate:
                room_service = RoomRequestService(fixture.database,
                    EngineGateway(Path(current_app.root_path).parent, current_app.config["BACKEND_TIMEOUT"], current_app.logger),
                    current_app.config["ROOM_SELECTION_STRATEGY"])
                booking_id = room_service.submit_group_meeting(db, actor, purpose=request.form.get("purpose"),
                    start=datetime.fromisoformat(value["start"]), duration=value["duration"],
                    participant_ids=list(dict(value["sides"])), features=value["features"], room_id=candidate,
                    submission_key=digest)
                return redirect(url_for("rooms.detail", request_id=booking_id), code=303)
            move = value["move"]
            meeting_id = submit(db, fixture, actor, roster, sides=dict(value["sides"]), purpose=request.form.get("purpose"),
                start=datetime.fromisoformat(value["start"]), duration=value["duration"],
                room_id=value["room"], features=value["features"], flexible=request.form.get("flexible") == "yes",
                move=(move[0], move[1], datetime.fromisoformat(move[2])) if move else None, submission_key=digest,
                join_url=request.form.get("join_url"))
        return redirect(url_for("group_meetings.detail", meeting_id=meeting_id))

    @blueprint.get("/<int:meeting_id>")
    def detail(meeting_id):
        with group_session(fixture) as (db, actor, roster):
            meeting, members = visible_meeting(db, meeting_id, actor)
            own = next(p for p in members if p.user_id == actor)
            responses = consents_for(db, meeting.id)
            consent = next((row for row in responses if row.user_id == actor), None)
            affected = consent is not None
            if meeting.status != PENDING:
                consent = None
            relocation = None
            if consent:
                try:
                    target, affected_ids, replacement_end = check_pending_relocation(
                        db, fixture, meeting, members, roster, responses)
                    if actor in affected_ids:
                        relocation = {"id": target.id, "purpose": target.purpose, "start": target.start_at,
                                      "end": target.end_at, "replacement_end": replacement_end}
                except MeetingError:
                    # A refusal can close a stale proposal. Withhold the obsolete target details.
                    pass
            events = list(db.scalars(select(GroupMeetingEvent).where(GroupMeetingEvent.meeting_id == meeting.id)
                .order_by(GroupMeetingEvent.id.desc()).limit(40)))
            room = (db.execute(select(Resource.name, Resource.building).join(StudentRoomRequest,
                StudentRoomRequest.resource_id == Resource.id).where(
                    StudentRoomRequest.id == meeting.room_request_id)).one_or_none()
                if meeting.room_request_id else None)
            room_name = " · ".join(value for value in room if value) if room else None
            return render_template("group_meeting_detail.html", meeting=meeting, members=members, roster=roster,
                actor=actor, own=own, consent=consent, responses=responses, history=events,
                active=meeting.status in ACTIVE and _future(meeting), room_name=room_name, affected=affected,
                relocation=relocation)

    @blueprint.post("/<int:meeting_id>/response")
    def response(meeting_id):
        with group_session(fixture, write=True) as (db, actor, roster):
            decide(db, fixture, actor, roster, meeting_id, _identifier(request.form.get("revision")), request.form.get("action"))
        return redirect(url_for("group_meetings.detail", meeting_id=meeting_id))

    @blueprint.post("/<int:meeting_id>/revise")
    def revision(meeting_id):
        with group_session(fixture, write=True) as (db, actor, roster):
            revise(db, fixture, actor, roster, meeting_id, _identifier(request.form.get("revision")),
                local_instant(request.form.get("start")))
        return redirect(url_for("group_meetings.detail", meeting_id=meeting_id))

    @blueprint.post("/<int:meeting_id>/cancel")
    def cancellation(meeting_id):
        with group_session(fixture, write=True) as (db, actor, _):
            cancel(db, actor, meeting_id, _identifier(request.form.get("revision")))
        return redirect(url_for("group_meetings.detail", meeting_id=meeting_id))

    @blueprint.after_request
    def private_cache(response):
        response.headers["Cache-Control"] = "private, no-store"
        return response

    app.register_blueprint(blueprint)
    from .group_meeting_preferences import create_preferences_blueprint
    from .group_meeting_reschedule_routes import register_group_meeting_reschedule
    app.register_blueprint(create_preferences_blueprint(fixture))
    register_group_meeting_reschedule(app, fixture)
    app.jinja_env.globals["group_meetings_enabled"] = True
