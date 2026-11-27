"""Read-only CDMCS recommendations for a freshly provisioned rehearsal."""

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
import secrets
from threading import Lock

from flask import Blueprint, abort, g, render_template, request, session as login_session
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from research.cdmcs.i3a.execution import validate_cdmcs
from research.cdmcs.i3a.snapshot import Commitment, Interval, Participant, Snapshot
from research.cdmcs.i3c.process import ProcessFailure, execute
from research.cdmcs.i3d.d1.compiler import compile_preferences

from .account_service import AccountService, is_research_assistant
from .appointment_service import AppointmentService
from .backend_executable import file_sha256
from .calendar_service import CalendarError, calendar_snapshot, epoch, local_instant, university_zone
from .cost_policy_values import OPERATION, OBJECTIVE, RATE_MODEL
from .persistence.database import DatabaseBusy
from .persistence.models import LoginAccount, Role, User
from .persistence.repository import state_row
from .scheduling_preference_service import SchedulingPreferenceService


@dataclass(frozen=True, repr=False)
class FlexibleMeeting:
    people: tuple[int, ...]
    start: datetime
    end: datetime
    replacements: tuple[datetime, ...]


@dataclass(frozen=True, repr=False)
class RehearsalFixture:
    database: object
    engine: Path
    engine_sha256: str
    people: tuple[int, ...]
    start: datetime
    end: datetime
    flexible: tuple[FlexibleMeeting, ...] = ()
    admission: Lock = field(default_factory=Lock, init=False)


class RehearsalError(ValueError):
    pass


DEMO_ROLES = {"Student", "Instructor", "Research Assistant", "Staff", "Administrator"}
FIXTURE_EXTENSION = "cdmcs_rehearsal_fixture"
SESSION_COOKIE = "cdmcs_rehearsal_session"
ORIGIN = {"source": "synthetic-itu-rehearsal", "fixture_id": "appointments"}
TIER_POLICY = dict(preferred_rate=1, outside_window_rate=2, outside_day_rate=4,
    gap_weight=1, nearby_limit=120, exception_fee=0, move_fixed_cost=25,
    move_participant_cost=50, delay_per_day=10)


def _role(role, assistant_type):
    return "Research Assistant" if is_research_assistant(role, assistant_type) else role


@contextmanager
def _read(fixture, *, write=False):
    authenticated = getattr(g, "authenticated_database_url", None)
    principal = getattr(g, "principal", None)
    token = login_session.get("csrf")
    if (not principal or principal.user_id not in fixture.people or login_session.get("login_format") != 2
            or not isinstance(token, str) or not token or authenticated != fixture.database.engine.url):
        abort(403)
    with fixture.database.transaction(read_only=not write) as session, session.no_autoflush:
        if session.get_bind().url != authenticated:
            abort(403)
        if write:
            state_row(session, True)
            if session.get(LoginAccount, principal.user_id, with_for_update=True) is None:
                abort(403)
        current = AccountService(fixture.database).identity(login_session.get("user_id"),
            login_session.get("session_version"), session=session, session_token=token)
        if current != principal:
            abort(403)
        rows = list(session.execute(select(User, Role.name, LoginAccount.enabled)
            .join(Role, Role.id == User.primary_role_id).outerjoin(LoginAccount, LoginAccount.user_id == User.id)))
        if {user.id for user, _, _ in rows} != set(fixture.people):
            abort(403)
        roster = {user.id: {"id": user.id, "name": user.name, "role": _role(role, user.assistant_type)}
                  for user, role, enabled in rows if enabled and user.status.casefold() == "active"
                  and _role(role, user.assistant_type) in DEMO_ROLES}
        if principal.user_id not in roster:
            abort(403)
        yield session, principal.user_id, roster


def _selection(form, actor, roster, fixture):
    try:
        identifiers = [[int(value) for value in form.getlist(key)]
                       for key in ("cohostIds", "requiredIds", "optionalIds")]
        hosts, guests, optional = identifiers
        required = [actor, *hosts, *guests]
        people = [*required, *optional]
        duration = int(form["duration"])
        first, last = date.fromisoformat(form["fromDate"]), date.fromisoformat(form["untilDate"])
        start = local_instant(datetime.combine(first, time()))
        end = local_instant(datetime.combine(last + timedelta(days=1), time()))
        raw_preferred = form.get("preferredStart", "")
        preferred = local_instant(raw_preferred) if raw_preferred else None
    except (ValueError, KeyError, CalendarError, OverflowError):
        raise RehearsalError("Enter a valid duration and dates within the rehearsal period.") from None
    if not guests or len(set(people)) != len(people) or not set(people) <= roster.keys() or len(people) > 8:
        raise RehearsalError("Select distinct rehearsal participants and at least one required invitee.")
    if not 15 <= duration <= 120 or duration % 15:
        raise RehearsalError("Choose a duration from 15 to 120 minutes in 15-minute steps.")
    if not fixture.start <= start < end <= fixture.end or (preferred and not start <= preferred < end):
        raise RehearsalError("Choose dates and a preferred time within the rehearsal period.")
    return required, optional, duration, start, end, preferred


def _interval(start, end):
    return {"start": datetime.fromtimestamp(start, timezone.utc).isoformat(),
            "end": datetime.fromtimestamp(end, timezone.utc).isoformat()}


def _preference(session, actor, opaque, fixture, zone):
    view = SchedulingPreferenceService._view(SchedulingPreferenceService._latest(session, actor))
    first = fixture.start.astimezone(zone).date()
    last = (fixture.end - timedelta(minutes=1)).astimezone(zone).date()
    if (view.state == "configured" and view.values.timezone == zone.key
            and view.values.first <= first <= last <= view.values.last):
        values = view.values.document()
    else:
        # Explicit fixture defaults, including for missing or inapplicable intent.
        values = {"timezone": zone.key, "effective": {"from": first.isoformat(), "until": last.isoformat()},
                  "preferred_weekdays": list(range(1, 8)),
                  "preferred_windows": [{"weekday": day, "start": "10:00", "end": "15:00"} for day in range(1, 8)],
                  "desired_gap_minutes": 15}
    return {"preference_version": 1, "synthetic": True, "owner": opaque, "revision": max(1, view.revision),
            "state": "configured", **values, "provenance": ORIGIN}, view.revision


def _compile(session, fixture, actor, roster, selection, *, hard_windows=None, facts_snapshot=None):
    required, optional, duration, start, end, preferred = selection
    zone = university_zone()
    anchor, boundary = epoch(fixture.start), epoch(fixture.end)
    low, high = epoch(start), epoch(end)
    # This adapter reads the existing publication and busy facts for the same
    # role-neutral participant set. It grants no standard appointment capability.
    facts, revision = (calendar_snapshot(session, actor, required, optional, duration, fixture.start, fixture.end)
                       if facts_snapshot is None else facts_snapshot)
    if set(facts["unresolvedIds"]) & set(required):
        raise RehearsalError("A required calendar has unresolved commitments.")
    opaque = {pid: f"person-{index}" for index, pid in enumerate(required)}
    publications = window_map(fixture, roster, facts, required) if hard_windows is None else {
        uid: [Interval(epoch(a), epoch(b)) for a, b in hard_windows[uid]] for uid in required}
    # Clip occupancy to the complete, intentionally bounded rehearsal calendar.
    # Deduplicate overlaps while preserving touching events and their zero gap.
    busy = {pid: [] for pid in required}
    for row in facts["busy"]:
        if row["userId"] in busy:
            a, b = max(anchor, row["start"]), min(boundary, row["end"])
            if a < b:
                busy[row["userId"]].append(Interval(a, b))
    events = []
    for pid, intervals in busy.items():
        covered = []
        for value in sorted(intervals, key=lambda item: item.start):
            if covered and value.start < covered[-1].end:
                covered[-1] = Interval(covered[-1].start, max(value.end, covered[-1].end))
            else:
                covered.append(value)
        events.extend(Commitment(f"protected-{opaque[pid]}-{index}", value, (opaque[pid],), ())
                      for index, value in enumerate(covered))
    flexible = None
    for meeting in fixture.flexible:
        # A move must account for the entire fictional meeting, including its
        # attendees. Omit the move if any such attendee lies outside this search.
        if not set(meeting.people) & set(required):
            continue
        identity = "rehearsal-flex"
        interval = Interval(epoch(meeting.start), epoch(meeting.end))
        members = tuple(opaque[pid] for pid in meeting.people if pid in opaque)
        events.append(Commitment(identity, interval, members, ()))
        if set(meeting.people) <= set(required):
            flexible = meeting
    participants = tuple(Participant(opaque[pid], True, pid != actor, "known", tuple(publications[pid]), None,
                                     roster[pid]["role"]) for pid in required)
    starts = tuple(stamp for stamp in range(low, high - duration * 60 + 1, 900)
                   if all(any(window.start <= stamp and stamp + duration * 60 <= window.end
                              for window in person.published) for person in participants))
    if not starts:
        return None, flexible, revision, ()
    snapshot = Snapshot(id="itu-rehearsal", zone=zone.key, anchor=anchor, horizon=Interval(low, high), duration=duration,
        organizer=opaque[actor], participants=participants, commitments=tuple(event for event in events
            if event.interval.start < high and event.interval.end > low), resources=(), candidate_mode="explicit",
        grid_anchor=opaque[required[1]], explicit_starts=starts,
        preferred_start=epoch(preferred) if preferred else None, provenance=tuple(ORIGIN.items()), unsupported=())
    preferences, revisions = zip(*(_preference(session, pid, opaque[pid], fixture, zone) for pid in required))
    policy = dict(policy_version=1, synthetic=True, id="provisional-rehearsal",
                  revision=1, rate_model=RATE_MODEL, **TIER_POLICY, provenance=ORIGIN)
    context = {"context_version": 1, "synthetic": True, "state": "complete",
        "coverage": _interval(anchor, boundary), "complete_for": list(opaque.values()),
        "left_boundary": "calendar_start", "right_boundary": "calendar_end", "provenance": ORIGIN,
        "commitments": [{"id": event.id, "interval": _interval(event.interval.start, event.interval.end),
                         "people": list(event.people), "resources": [], "protected": True} for event in events]}
    payload = compile_preferences(snapshot, list(preferences), policy, context).to_request()
    # Preserve whole-window admission even if the research adapter coalesces
    # adjacent publication intervals while building its minute prefix arrays.
    for pid, windows in publications.items():
        payload["profiles"][opaque[pid]]["published"] = [
            [(window.start - anchor) // 60, (window.end - anchor) // 60] for window in windows]
    return payload, flexible, revision, tuple(revisions)


def window_map(fixture, roster, facts, required):
    zone = university_zone()
    anchor, boundary = epoch(fixture.start), epoch(fixture.end)
    publications = {pid: [] for pid in required}
    for row in facts["published"]:
        if roster[row["userId"]]["role"] == "Instructor":
            publications[row["userId"]].append(Interval(max(anchor, row["start"]), min(boundary, row["end"])))
    for pid in required:
        if roster[pid]["role"] == "Instructor":
            continue
        current = fixture.start.astimezone(zone).date()
        while current <= (fixture.end - timedelta(minutes=1)).astimezone(zone).date():
            a = epoch(local_instant(datetime.combine(current, time(9)), zone))
            b = epoch(local_instant(datetime.combine(current, time(17)), zone))
            publications[pid].append(Interval(a, b))
            current += timedelta(days=1)
    return publications


def _run(fixture, payload):
    if not secrets.compare_digest(file_sha256(fixture.engine), fixture.engine_sha256):
        raise RehearsalError("The verified CDMCS executable changed. Restart the rehearsal.")
    return execute([str(fixture.engine)], payload, timeout=5, memory_bytes=256 * 1024**2,
                   input_limit=4 * 1024**2, output_limit=512 * 1024).payload


def _relocation_rows(fixture, payload, meeting):
    if meeting is None:
        return []
    anchor = epoch(fixture.start)
    original = next(event for event in payload["existing"] if event["id"] == "rehearsal-flex")
    starts = [start for start in payload["candidate_starts"]
              if start < original["start"] + original["duration"] and start + payload["duration"] > original["start"]]
    if not starts:
        return []
    # Keep the global delay anchor even if the earliest candidate is direct.
    starts = sorted({min(payload["candidate_starts"]), *starts})
    replacements = [(epoch(start) - anchor) // 60 for start in meeting.replacements]
    request_data = dict(payload, candidate_starts=starts, replacement_starts=replacements,
        existing=[{**event, "flexible": True} if event is original else event for event in payload["existing"]])
    if len(starts) * len(replacements) > request_data["limit"]:
        raise RehearsalError("This rehearsal search has too many relocation alternatives.")
    answer = _run(fixture, request_data)
    rows = answer.get("recommendations")
    expected = {"new_meeting_extra_availability": [], "relocated_meeting_extra_availability": [],
                "relocation_participant_approval": original["people"]}
    if (answer.get("operation") != OPERATION or answer.get("model") != OBJECTIVE
            or answer.get("status") not in {"OK", "NO_FEASIBLE_PROPOSAL"} or answer.get("truncated") is not False
            or not isinstance(rows, list) or len(rows) != answer.get("returned_count")
            or len(rows) != answer.get("solutions_evaluated") or bool(rows) != (answer["status"] == "OK")):
        raise RehearsalError("The relocation engine response could not be verified.")
    proposals = [row for row in rows if row.get("moved_meeting_id") is not None]
    if any(row.get("moved_meeting_id") != original["id"] or row.get("start_minute") not in starts
           or row.get("end_minute") != row["start_minute"] + payload["duration"]
           or row.get("replacement_start_minute") not in replacements
           or row.get("proposal_status") != "CONDITIONAL_PENDING_APPROVAL"
           or row.get("required_permissions") != expected
           or type(row.get("total_cost")) is not int or type(row.get("fairness_max_burden")) is not int
           for row in proposals):
        raise RehearsalError("The relocation engine response could not be verified.")
    return proposals


def _format_options(fixture, selection, rows, meeting=None):
    zone = university_zone()
    preferred = selection[-1]
    def when(minute):
        return fixture.start + timedelta(minutes=minute)

    def label(value):
        return value.astimezone(zone).strftime("%a %d %b, %H:%M")

    def rank(row):
        start = when(row["start_minute"])
        distance = abs((start - preferred).total_seconds()) if preferred else 0
        return row["total_cost"], row["fairness_max_burden"], distance, row["start_minute"]

    values = []
    for row in sorted(rows, key=rank)[:8]:
        start = when(row["start_minute"])
        explanation = None
        if preferred:
            delta = int((start - preferred).total_seconds() // 60)
            direction = "after" if delta > 0 else "before"
            explanation = f"{abs(delta)} min {direction} your preferred start." if delta else "Matches your preferred start."
        value = {"start": label(start), "end": label(when(row["end_minute"])),
                 "localStart": start.astimezone(zone).strftime("%Y-%m-%dT%H:%M"),
                 "replacementStart": None, "replacementEnd": None, "explanation": explanation}
        if meeting:
            replacement = when(row["replacement_start_minute"])
            value.update(replacementStart=label(replacement),
                         replacementEnd=label(replacement + (meeting.end - meeting.start)))
        values.append(value)
    return values


def _standard_booking(fixture, selection, roster):
    required, optional = selection[:2]
    if (roster[required[0]]["role"] != "Student" or any(roster[uid]["role"] != "Instructor" for uid in required[1:])
            or any(roster[uid]["role"] != "Student" for uid in optional)):
        return None
    directory = AppointmentService(fixture.database, None).directory()
    faculties = {row["id"]: row["facultyId"] for row in directory["professors"]}
    groups = {faculties.get(uid) for uid in required[1:]}
    if len(groups) == 1 and None not in groups:
        return {"faculty": groups.pop(), "professors": required[1:], "invitees": optional, "duration": selection[2]}
    return None


def register_rehearsal(app, fixture):
    """The dedicated launcher alone registers this blueprint on its new local DB."""
    url = fixture.database.engine.url
    if (url.host != "127.0.0.1" or url.database != "ras_cdmcs_rehearsal" or not url.port
            or url.query or not 2 <= len(fixture.people) <= 8 or len(set(fixture.people)) != len(fixture.people)
            or len(fixture.flexible) > 1 or not timedelta(days=1) <= fixture.end - fixture.start <= timedelta(days=3)
            or file_sha256(fixture.engine) != fixture.engine_sha256):
        raise RehearsalError("Rehearsal requires its verified executable and freshly owned fixture database.")
    for meeting in fixture.flexible:
        span = meeting.end - meeting.start
        if (not timedelta(minutes=15) <= span <= timedelta(hours=3)
                or not 1 <= len(meeting.replacements) <= 4 or not meeting.people
                or len(set(meeting.people)) != len(meeting.people) or not set(meeting.people) <= set(fixture.people)
                or not fixture.start <= meeting.start < meeting.end <= fixture.end
                or any(not fixture.start <= stamp < stamp + span <= fixture.end for stamp in meeting.replacements)):
            raise RehearsalError("Invalid fictional relocation fixture.")
    blueprint = Blueprint("cdmcs_rehearsal", __name__, url_prefix="/appointments/rehearsal")

    @blueprint.route("", methods=["GET", "POST"])
    def index():
        if request.remote_addr != "127.0.0.1":
            abort(403)
        zone = university_zone()
        first, last = fixture.start.astimezone(zone).date(), (fixture.end - timedelta(minutes=1)).astimezone(zone).date()
        form = {"cohostIds": [], "requiredIds": [], "optionalIds": [], "duration": 30,
                "fromDate": first.isoformat(), "untilDate": last.isoformat(), "preferredStart": ""}
        people, result, error, status = (), None, None, 200
        try:
            with _read(fixture) as (session, actor, roster):
                people = sorted((row for uid, row in roster.items() if uid != actor), key=lambda row: row["name"])
                if request.method != "POST":
                    return render_template("cdmcs_rehearsal.html", people=people, form=form, zone=zone.key,
                        error=error, result=result, first=first, last=last), 200
                selection = _selection(request.form, actor, roster, fixture)
                form.update({key: [int(value) for value in request.form.getlist(key)]
                             for key in ("cohostIds", "requiredIds", "optionalIds")})
                form.update({key: request.form.get(key, "") for key in ("duration", "fromDate", "untilDate", "preferredStart")})
                payload, meeting, revision, preferences = _compile(session, fixture, actor, roster, selection)
            result = {"direct": [], "relocation": [], "message": "",
                      "relationship": f"{1 + len(form['cohostIds'])} to {len(form['requiredIds'])}"}
            if payload is not None:
                if not fixture.admission.acquire(blocking=False):
                    raise RehearsalError("Another rehearsal search is running. Please retry.")
                try:
                    direct = _run(fixture, payload)
                    validate_cdmcs(direct, payload)
                    result["direct"] = _format_options(fixture, selection, direct["recommendations"])
                    result["relocation"] = _format_options(fixture, selection,
                        _relocation_rows(fixture, payload, meeting), meeting)
                finally:
                    fixture.admission.release()
                with _read(fixture) as (session, _, roster):
                    latest = tuple(SchedulingPreferenceService._view(
                        SchedulingPreferenceService._latest(session, pid)).revision for pid in selection[0])
                    if (state_row(session).calendar_revision != revision or latest != preferences
                            or not set(selection[0] + selection[1]) <= roster.keys()):
                        raise RehearsalError("Calendars or preferences changed during this search. Please retry.")
                if result["direct"]:
                    result["booking"] = _standard_booking(fixture, selection, roster)
            if not (result["direct"] or result["relocation"]):
                result["message"] = "No options fit the selected required participants and dates."
        except RehearsalError as failure:
            error, result, status = str(failure), None, 409
        except (ValueError, CalendarError, ProcessFailure, OSError, DatabaseBusy, SQLAlchemyError):
            error, result, status = "The rehearsal could not safely evaluate these calendars.", None, 409
        return render_template("cdmcs_rehearsal.html", people=people,
            form=form, zone=zone.key, error=error, result=result, first=first, last=last), status

    @blueprint.after_request
    def private_preview(response):
        response.headers["Cache-Control"] = "private, no-store"
        return response

    app.register_blueprint(blueprint)
    app.extensions[FIXTURE_EXTENSION] = fixture
    app.config["SESSION_COOKIE_NAME"] = SESSION_COOKIE
    app.jinja_env.globals["cdmcs_rehearsal_enabled"] = True
