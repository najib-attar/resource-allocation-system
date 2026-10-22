"""Explicit academic bounds and configured quotas, not resource matching rules."""
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from .calendar_service import CalendarError, local_instant
from .persistence.models import AcademicPeriod, BorrowRequest, EquipmentReservation, ReservationOccurrence, ReservationSeries, StudentRoomRequest
from .persistence.repository import state_row


def policy_directory(session):
    state = state_row(session)
    return {'periods': [{'id': p.id, 'name': p.name, 'start': p.start_date, 'end': p.end_date}
                        for p in session.scalars(select(AcademicPeriod).where(AcademicPeriod.is_semester.is_(True)).order_by(AcademicPeriod.start_date, AcademicPeriod.id))],
            'limits': state.recurring_limits, 'priorities': state.reservation_priorities}


def semester(session, expanded, rule):
    key = rule.get('periodId')
    period = session.get(AcademicPeriod, key) if type(key) is int and key > 0 else None
    if period is None or not period.is_semester:
        raise CalendarError('Select an explicitly configured academic semester. Ask administration to configure its dates if none are available.')
    zone = ZoneInfo(period.timezone)
    lower = local_instant(datetime.combine(period.start_date, time()), zone, check_range=False)
    upper = local_instant(datetime.combine(period.end_date + timedelta(days=1), time()), zone, check_range=False)
    if expanded['timezone'] != period.timezone or any(a < lower or b > upper for a, b in expanded['intervals']):
        raise CalendarError('Every pickup/start and return/end must fall within the selected semester and its configured timezone.')
    mode = rule.get('approvalMode', 'all')
    if mode not in {'all', 'partial'}:
        raise CalendarError('Choose all occurrences required or partial approval allowed.')
    return {**expanded, 'periodId': period.id, 'approvalMode': mode, 'semesterStart':lower,'semesterEnd':upper}


def weekly_minutes(intervals, zone):
    totals = defaultdict(float)
    for start, end in intervals:
        local = start.astimezone(zone)
        monday = local.date() - timedelta(days=local.weekday())
        while start < end:
            boundary = local_instant(datetime.combine(monday + timedelta(days=7), time()), zone, check_range=False)
            stop = min(boundary, end)
            totals[monday] += (stop - start).total_seconds() / 60
            start, monday = stop, monday + timedelta(days=7)
    return totals


def check_limits(session, actor, kind, expanded, exclude=None):
    """Caller holds the shared policy lock and student's row lock during creation."""
    limits = state_row(session).recurring_limits.get(kind, {})
    parent, owner, column = ((StudentRoomRequest, StudentRoomRequest.organizer_id, ReservationSeries.room_request_id)
                             if kind == 'room' else (BorrowRequest, BorrowRequest.borrower_id, ReservationSeries.borrow_request_id))
    due=ReservationOccurrence.end_at
    held=select(EquipmentReservation.id).where(EquipmentReservation.occurrence_id==ReservationOccurrence.id,
        EquipmentReservation.handed_at.is_not(None),EquipmentReservation.returned_at.is_(None)).exists()
    if kind=='equipment':
        actual=select(func.max(EquipmentReservation.due_at)).where(EquipmentReservation.occurrence_id==ReservationOccurrence.id).scalar_subquery()
        due=func.greatest(due,func.coalesce(actual,due))
    query = select(ReservationSeries.id, ReservationOccurrence.start_at, due,ReservationOccurrence.status,held).join(
        parent, parent.id == column).join(ReservationOccurrence, ReservationOccurrence.series_id == ReservationSeries.id).where(
        owner == actor, ReservationOccurrence.status.in_(['Proposed', 'Unavailable', 'Reserved','Completed']))
    if exclude is not None:
        query = query.where(parent.id != exclude)
    rows = list(session.execute(query))
    maximum = limits.get('maxActiveSeries')
    if maximum is not None and len({r[0] for r in rows if r[3]!='Completed' and (r[2]>datetime.now(timezone.utc) or r[4])}) >= maximum:
        raise CalendarError('The configured maximum active recurring series has been reached. Cancel unused future requests or contact administration.')
    maximum = limits.get('maxWeeklyMinutes')
    if maximum is not None:
        zone=ZoneInfo(expanded['timezone'])
        affected=weekly_minutes(expanded['intervals'],zone)
        totals = weekly_minutes([(r[1], r[2]) for r in rows] + expanded['intervals'],zone)
        if any(totals[week] > maximum for week in affected):
            raise CalendarError('The request exceeds the configured maximum recurring reservation hours in a calendar week.')


def occurrence_summary(rows):
    states = [r.status if hasattr(r, 'status') else r['status'] for r in rows]
    if states and all(s in {'Completed','Cancelled'} for s in states) and 'Completed' in states:return 'Completed'
    confirmed = sum(s in {'Reserved', 'Completed'} for s in states)
    if confirmed:
        return 'Confirmed' if confirmed + states.count('Cancelled') == len(states) else 'Partially Confirmed'
    if all(s == 'Cancelled' for s in states): return 'Cancelled'
    if all(s in {'Rejected', 'Cancelled'} for s in states): return 'Rejected'
    return 'Pending Review'
