"""Bounded calendar expansion shared by room and returnable-equipment workflows."""
from datetime import date, datetime, time, timedelta
import re

from .calendar_service import CalendarError, aware, epoch, expand_weekly, local_instant, university_zone


MAX_OCCURRENCES = 366
MAX_RANGE_DAYS = 730


def expand_recurrence(rule, duration, *, zone=None, now=None):
    """Date bounds include pickup/start dates; duration is elapsed minutes."""
    zone = zone or university_zone()
    try:
        if not isinstance(rule, dict) or type(duration) is not int or not 1 <= duration <= 365 * 1440:
            raise ValueError()
        first, last = (rule.get(key) for key in ('startDate', 'endDate'))
        if any(not isinstance(v, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', v) for v in (first, last)):
            raise ValueError()
        first, last = date.fromisoformat(first), date.fromisoformat(last)
        if not date(1970, 1, 1) <= first <= last <= date(2099, 12, 31) or (last-first).days > MAX_RANGE_DAYS:
            raise ValueError()
        days = rule.get('weekdays')
        if not isinstance(days, list) or not 1 <= len(days) <= 7 or any(type(d) is not int or not 1 <= d <= 7 for d in days) or len(set(days)) != len(days):
            raise ValueError()
        clock = rule.get('startTime')
        if not isinstance(clock, str) or not re.fullmatch(r'([01][0-9]|2[0-3]):[0-5][0-9]', clock):
            raise ValueError()
        minutes = int(clock[:2])*60 + int(clock[3:])
    except (ValueError, TypeError, OverflowError) as error:
        raise CalendarError('Choose distinct weekdays, a local HH:MM start, valid start/end dates within two years, and a positive supported duration.') from error
    lower = local_instant(datetime.combine(first, time()), zone, check_range=False)
    upper = local_instant(datetime.combine(last + timedelta(days=1), time()), zone, check_range=False)
    # Reuse bounded weekday expansion; validate the real start separately so an
    # artificial one-minute anchor cannot reject a valid start before a DST gap.
    dates = [a.astimezone(zone).date() for day in sorted(days) for a, _ in expand_weekly(
        day, 720, 721, first, last, zone.key, lower, upper)]
    starts = [local_instant(datetime.combine(day, time()) + timedelta(minutes=minutes), zone) for day in dates]
    intervals = sorted((a, a + timedelta(minutes=duration)) for a in starts)
    if not intervals or len(intervals) > MAX_OCCURRENCES:
        raise CalendarError('The selected range must generate 1-366 occurrences. Shorten the range or choose applicable weekdays.')
    for a, b in intervals:
        epoch(a); epoch(b)
    if any(previous[1] > following[0] for previous, following in zip(intervals, intervals[1:])):
        raise CalendarError('Recurring periods overlap. Use one continuous borrowing interval or separate non-overlapping periods.')
    if now is not None and intervals[0][0] <= aware(now):
        raise CalendarError('Every proposed occurrence must start in the future.')
    return {'startDate': first, 'endDate': last, 'weekdays': sorted(days), 'startMinutes': minutes,
            'durationMinutes': duration, 'timezone': zone.key, 'intervals': intervals}


def recurrence_preview(expanded):
    return [{'start': epoch(a), 'end': epoch(b)} for a, b in expanded['intervals']]


def recurrence_fields(form):
    """Only university configuration, not a supplied browser timezone, is trusted."""
    mode = form.get('reservationMode', 'once')
    if mode == 'once':
        return None
    if mode != 'weekly':
        raise CalendarError('Choose a one-time/continuous or weekly recurring reservation.')
    try:period=int(form.get('academicPeriod',''))
    except (ValueError,TypeError) as error:
        raise CalendarError('Select an explicitly configured academic semester before requesting recurrence.') from error
    try:
        return {'periodId': period, 'approvalMode': form.get('approvalMode', 'all'),
                'startDate': form.get('recurrenceStart'), 'endDate': form.get('recurrenceEnd'),
                'startTime': form.get('recurrenceTime'), 'weekdays': [int(v) for v in form.getlist('recurrenceDays')]}
    except (ValueError, TypeError) as error:
        raise CalendarError('Choose valid recurrence weekdays.') from error
