"""Explicit calendar projection; feasibility/ranking belongs to the C++ engine."""

from datetime import date, datetime, time, timedelta, timezone
import os
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select

from .persistence.models import (AcademicPeriod, Allocation, AppointmentCommitment, BusySlot,
                                 CalendarBlock, LegacyCalendarBinding, ProfessorAvailability,
                                 ResourceRequest, RequestParticipant, RoomOrganizerCommitment)
from .persistence.repository import PersistenceError, state_row


class CalendarError(PersistenceError):
    pass


def university_zone():
    try:
        return ZoneInfo(os.environ.get("RESOURCE_ALLOCATION_TIMEZONE", "Europe/Istanbul"))
    except ZoneInfoNotFoundError as error:
        raise CalendarError("The configured university timezone is unavailable.") from error


def local_instant(value, zone=None, check_range=True):
    """Require explicit local wall time and reject DST gaps/folds rather than guessing."""
    zone = zone or university_zone()
    try:
        naive = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(naive, datetime):
            raise ValueError()
        if naive.tzinfo is not None:
            raise ValueError()
        if naive.second or naive.microsecond:
            raise ValueError()
        alternatives = {naive.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
                        for fold in (0, 1)
                        if naive.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) == naive}
        if len(alternatives) != 1:
            raise ValueError()
        result = alternatives.pop()
        if check_range:
            epoch(result)
        return result
    except (ValueError, TypeError, OverflowError) as error:
        raise CalendarError("Enter an unambiguous existing local date/time, to the minute, in the university timezone.") from error


def aware(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise CalendarError("Calendar instants must include a timezone.")
    return value.astimezone(timezone.utc)


def epoch(value):
    value = aware(value)
    if value.second or value.microsecond or not 0 <= value.timestamp() <= 4102444800:
        raise CalendarError("Calendar dates must be minute-aligned and between 1970 and 2100.")
    return int(value.timestamp())


def expand_weekly(day, start_minutes, end_minutes, valid_from, valid_until, zone_name,
                  horizon_start, horizon_end, exclusions=(), week_start=None):
    try:
        zone = ZoneInfo(zone_name)
        excluded = {date.fromisoformat(item) for item in exclusions}
    except (ZoneInfoNotFoundError, ValueError, TypeError) as error:
        raise CalendarError("Invalid calendar timezone or excluded date configuration.") from error
    if not (1 <= day <= 7 and 0 <= start_minutes < end_minutes <= 1440 and valid_from <= valid_until):
        raise CalendarError("Invalid bounded weekly calendar pattern.")
    first = max(valid_from, horizon_start.astimezone(zone).date() - timedelta(days=1))
    last = min(valid_until, horizon_end.astimezone(zone).date())
    if week_start is not None:
        if week_start.isoweekday() != 1:
            raise CalendarError("A planning week must start on Monday.")
        first, last = max(first, week_start), min(last, week_start + timedelta(days=6))
    result = []
    current = first
    while current <= last:
        if current.isoweekday() == day and current not in excluded:
            start = local_instant(datetime.combine(current, time()) + timedelta(minutes=start_minutes), zone)
            end = local_instant(datetime.combine(current, time()) + timedelta(minutes=end_minutes), zone)
            if start < horizon_end and end > horizon_start:
                result.append((start, end))
        current += timedelta(days=1)
    return result


def legacy_intervals(session, people, start, end, active_run_id=None, include_details=False):
    """Known identities only: requester/required committee members, not attendee counts."""
    people = set(people)
    bindings = list(session.scalars(select(LegacyCalendarBinding)))
    periods = {item.id: item for item in session.scalars(select(AcademicPeriod))}
    busy_bindings, request_bindings = {}, {}
    for binding in bindings:
        target = busy_bindings if binding.busy_slot_id is not None else request_bindings
        target.setdefault(binding.busy_slot_id if binding.busy_slot_id is not None else binding.request_id, []).append(binding)
    output, unresolved = [], set()

    def project(ids, row, choices, title):
        ids = people.intersection(ids)
        if not ids:
            return
        if not choices:
            unresolved.update(ids)
            return
        for binding in choices:
            period = periods[binding.period_id]
            intervals = expand_weekly(row.day, row.start_minutes, row.end_minutes,
                                      period.start_date, period.end_date, period.timezone, start, end,
                                      binding.excluded_dates, binding.week_start)
            output.extend({"userId": pid, "start": epoch(a), "end": epoch(b),
                           **({"title": title} if include_details else {})} for pid in ids for a, b in intervals)

    for row in session.scalars(select(BusySlot).where(BusySlot.user_id.in_(people))):
        project([row.user_id], row, busy_bindings.get(row.id, []), row.reason or "University commitment")
    if active_run_id is not None:
        requests = {row.id: row for row in session.scalars(select(ResourceRequest))}
        participants = {}
        for row in session.scalars(select(RequestParticipant)):
            participants.setdefault(row.request_id, []).append(row.user_id)
        for row in session.scalars(select(Allocation).where(Allocation.run_id == active_run_id)):
            request = requests[row.request_id]
            project([request.requester_id] + participants.get(request.id, []), row, request_bindings.get(request.id, []),
                    request.title or request.purpose or "University commitment")
    return output, sorted(unresolved)


def calendar_snapshot(session, organizer_id, professor_ids, invited_ids, duration, start, end,
                      action="recommend", proposed=None, preferred=None, exclude_appointment=None):
    start, end = aware(start), aware(end)
    epoch(start)
    epoch(end)
    if start >= end or end - start > timedelta(days=32):
        raise CalendarError("Choose a nonempty search period of at most 32 days.")
    if type(duration) is not int or not 1 <= duration <= 1440:
        raise CalendarError("Appointment duration must be 1-1440 minutes.")
    state = state_row(session)
    people = {organizer_id, *professor_ids, *invited_ids}
    published = []
    for row in session.scalars(select(ProfessorAvailability).where(ProfessorAvailability.user_id.in_(professor_ids))):
        published.extend({"userId": row.user_id, "start": epoch(a), "end": epoch(b)} for a, b in
                         expand_weekly(row.day, row.start_minutes, row.end_minutes, row.valid_from, row.valid_until,
                                       row.timezone, start, end, row.excluded_dates))
    busy, unresolved = legacy_intervals(session, people, start, end, state.active_run_id)
    for model in (CalendarBlock, AppointmentCommitment, RoomOrganizerCommitment):
        query = select(model).where(model.user_id.in_(people), model.start_at < end, model.end_at > start)
        if model is AppointmentCommitment and exclude_appointment is not None:
            query = query.where(model.appointment_id != exclude_appointment)
        busy.extend({"userId": row.user_id, "start": epoch(row.start_at), "end": epoch(row.end_at)}
                    for row in session.scalars(query))
    snapshot = {"protocolVersion": 1, "operation": "appointment", "runId": uuid.uuid4().hex,
                "action": action, "organizerId": organizer_id, "professorIds": sorted(professor_ids),
                "invitedIds": sorted(invited_ids), "durationMinutes": duration, "horizon": {"start": epoch(start), "end": epoch(end)},
                "published": published, "busy": busy, "unresolvedIds": unresolved}
    if proposed is not None:
        snapshot["proposed"] = {"start": epoch(proposed[0]), "end": epoch(proposed[1])}
    if preferred is not None:
        snapshot["preferredStart"] = epoch(preferred)
    return snapshot, state.calendar_revision


def assert_commitments_compatible(session, intervals):
    """Publication integrity gate, not an alternative appointment scheduling algorithm."""
    for value in intervals:
        start = datetime.fromtimestamp(value["start"], timezone.utc)
        end = datetime.fromtimestamp(value["end"], timezone.utc)
        for model in (AppointmentCommitment, RoomOrganizerCommitment):
            key = model.appointment_id if model is AppointmentCommitment else model.request_id
            if session.scalar(select(key).where(model.user_id == value["userId"], model.start_at < end,
                    model.end_at > start).limit(1)) is not None:
                raise CalendarError("This calendar change conflicts with a confirmed appointment or room booking. Cancel or reschedule it first.")
