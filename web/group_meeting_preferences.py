"""Owner-scoped soft preferences and published availability for group meetings."""

from contextlib import contextmanager
from datetime import timedelta
import re

from flask import Blueprint, redirect, render_template, request, url_for
from sqlalchemy.exc import SQLAlchemyError

from .calendar_service import expand_weekly, university_zone
from .group_meeting_access import group_session
from .persistence.database import DatabaseBusy
from .persistence.models import GroupMeetingAvailability
from .persistence.repository import state_row
from .preference_values import PreferenceError, clock, day, parse_values
from .scheduling_preference_service import MAX_REVISION, PreferenceConflict, SchedulingPreferenceService


WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MAX_HARD_REVISION = 2**31 - 1
MAX_AVAILABILITY_WINDOWS = 28


class GroupMeetingPreferenceService(SchedulingPreferenceService):
    """Keep the immutable personal-revision contract and add the fixture gate."""

    def __init__(self, fixture):
        super().__init__(fixture.database)
        self.fixture = fixture

    @contextmanager
    def _session(self, *, write=False):
        with group_session(self.fixture, write=write) as (session, owner, _):
            state = state_row(session) if write else None
            yield session, owner
            if state is not None:
                state.calendar_revision += 1


def _bounds(fixture, zone):
    return fixture.start.astimezone(zone).date(), (fixture.end - timedelta(minutes=1)).astimezone(zone).date()


def _revision(form, maximum):
    value = form.get("revision", "")
    if not re.fullmatch(r"0|[1-9][0-9]{0,18}", value) or int(value) > maximum:
        raise PreferenceError("INVALID_REVISION")
    return int(value)


def _windows(form):
    windows = []
    for weekday in range(1, 8):
        starts = form.getlist(f"start_{weekday}")
        ends = form.getlist(f"end_{weekday}")
        if len(starts) != len(ends) or len(starts) > 64:
            raise PreferenceError("INVALID_WINDOW")
        for start, end in zip(starts, ends):
            if not start and not end:
                continue
            windows.append({"weekday": weekday, "start": start, "end": end})
    return windows


def _values(zone, first, last, days, windows, gap):
    return {"timezone": zone.key, "effective": {"from": first.isoformat(), "until": last.isoformat()},
            "preferred_weekdays": days, "preferred_windows": windows, "desired_gap_minutes": gap}


def _soft_form(form, fixture, zone):
    days = form.getlist("preferred_weekday")
    indifferent = form.getlist("gap_indifferent")
    gap = form.get("desired_gap", "")
    if (indifferent not in ([], ["1"]) or any(value not in ("1", "2", "3", "4", "5", "6", "7") for value in days)
            or not indifferent and not re.fullmatch(r"[0-9]{1,4}", gap)):
        raise PreferenceError("INVALID_PREFERENCE")
    first, last = _bounds(fixture, zone)
    return _values(zone, first, last, [int(value) for value in days], _windows(form),
                   "indifferent" if indifferent else int(gap))


def _availability_values(zone, first, last, windows):
    values = parse_values(_values(zone, first, last, [], windows, "indifferent"))
    if len(values.original_windows) > MAX_AVAILABILITY_WINDOWS:
        raise PreferenceError("AVAILABILITY_WINDOW_LIMIT")
    if any(clock(start) >= clock(end, end=True) for _, start, end in values.original_windows):
        raise PreferenceError("HARD_WINDOW_ORDER")
    return values


def _hard_form(form, fixture, zone):
    first, last = day(form.get("valid_from")), day(form.get("valid_until"))
    fixture_first, fixture_last = _bounds(fixture, zone)
    if not fixture_first <= first <= last <= fixture_last:
        raise PreferenceError("AVAILABILITY_DATES")
    relocation = form.getlist("allow_relocation")
    if relocation not in ([], ["1"]):
        raise PreferenceError("INVALID_RELOCATION_SETTING")
    values = _availability_values(zone, first, last, _windows(form))
    return first, last, values.document()["preferred_windows"], bool(relocation)


def availability_intervals(row, horizon_start, horizon_end, zone):
    """Expand only explicit hard publications into half-open UTC intervals."""
    if row is None:
        return ()
    values = _availability_values(zone, row.valid_from, row.valid_until, row.windows)
    intervals = []
    for weekday, start, end in values.windows:
        intervals.extend((max(left, horizon_start), min(right, horizon_end))
                         for left, right in expand_weekly(weekday, start, end, values.first, values.last,
                                                          zone.key, horizon_start, horizon_end))
    return tuple(sorted(intervals))


def _save_availability(fixture, expected, values):
    first, last, windows, relocation = values
    with group_session(fixture, write=True) as (session, owner, _):
        row = session.get(GroupMeetingAvailability, owner)
        current = row.revision if row else 0
        if current != expected or current == MAX_HARD_REVISION:
            raise PreferenceConflict()
        state = state_row(session)
        if row is None:
            row = GroupMeetingAvailability(owner_id=owner)
            session.add(row)
        row.valid_from, row.valid_until = first, last
        row.windows, row.allow_relocation, row.revision = windows, relocation, current + 1
        state.calendar_revision += 1


def _display_windows(windows):
    by_day = {day: [] for day in range(1, 8)}
    for window in windows:
        by_day[window["weekday"]].append((window["start"], window["end"]))
    return by_day


FORM_ERRORS = {
    "INVALID_REVISION": "Reload the page and try again.",
    "INVALID_DATE": "Enter a starting day and an ending day.",
    "AVAILABILITY_DATES": "Choose an ordered date range within the demonstration period.",
    "HARD_WINDOW_ORDER": "Availability must finish later on the same day.",
    "INVALID_CLOCK": "Enter both a start and an end time for every interval.",
    "EMPTY_WINDOW": "Start and end times must differ.",
    "WEEKDAY_WINDOW_CONFLICT": "Select the preferred weekdays that have working hours or clear their hours.",
    "OVERLAPPING_WINDOWS": "Intervals must not overlap on the same day.",
    "AVAILABILITY_WINDOW_LIMIT": "Use at most 28 weekly availability intervals.",
    "INVALID_INTEGER": "Desired breaks must be between 0 and 1440 minutes.",
}


def create_preferences_blueprint(fixture):
    blueprint = Blueprint("group_meeting_preferences", __name__, url_prefix="/meetings/preferences")
    soft_service = GroupMeetingPreferenceService(fixture)

    @blueprint.route("", methods=["GET", "POST"])
    def index():
        zone = university_zone()
        action, error, status = None, None, 200
        try:
            if request.method == "POST":
                action = request.form.get("action")
                if action == "preferences":
                    revision = _revision(request.form, MAX_REVISION)
                    values = _soft_form(request.form, fixture, zone)
                    soft_service.replace(revision, {"preference_version": 1, **values})
                elif action == "availability":
                    revision = _revision(request.form, MAX_HARD_REVISION)
                    values = _hard_form(request.form, fixture, zone)
                    _save_availability(fixture, revision, values)
                else:
                    raise PreferenceError("UNKNOWN_ACTION")
                return redirect(url_for(".index", saved=action), code=303)
        except PreferenceError as failure:
            error, status = FORM_ERRORS.get(failure.code, "Check the scheduling settings and try again."), 422
        except PreferenceConflict:
            error, status = "These settings changed. Review the current settings and try again.", 409
        except (DatabaseBusy, SQLAlchemyError):
            error, status = "The settings could not be saved. Please try again.", 503
        try:
            with group_session(fixture) as (session, owner, _):
                soft = soft_service._view(soft_service._latest(session, owner))
                hard = session.get(GroupMeetingAvailability, owner)
        except (DatabaseBusy, SQLAlchemyError):
            return "Scheduling settings could not be loaded.", 503
        first, last = _bounds(fixture, zone)
        saved = request.args.get("saved") if request.method == "GET" else None
        return render_template("group_meeting_preferences.html", zone=zone.key, weekdays=WEEKDAYS,
            first=first, last=last, soft=soft, hard=hard,
            soft_windows=_display_windows(soft.values.document()["preferred_windows"] if soft.values else []),
            hard_windows=_display_windows(hard.windows if hard else []),
            error=error, saved=saved, attempted=request.form if status == 422 else None, action=action), status

    @blueprint.after_request
    def private_settings(response):
        response.headers["Cache-Control"] = "private, no-store"
        return response

    return blueprint
