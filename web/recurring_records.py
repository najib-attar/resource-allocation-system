"""Shared persistence/projection helpers, not another booking or matching service."""
import hashlib
import json
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from .calendar_service import CalendarError
from .persistence.models import BorrowRequest, ReservationOccurrence, ReservationSeries, StudentRoomRequest
from .reservation_policy import occurrence_summary


def series_for(session, parent):
    column=ReservationSeries.room_request_id if isinstance(parent,StudentRoomRequest) else ReservationSeries.borrow_request_id
    return session.scalar(select(ReservationSeries).where(column==parent.id))


def occurrences_for(session, series):
    return list(session.scalars(select(ReservationOccurrence).where(ReservationOccurrence.series_id==series.id)
                               .order_by(ReservationOccurrence.ordinal))) if series else []


def submission_fingerprint(values):
    return hashlib.sha256(json.dumps(values,sort_keys=True,ensure_ascii=False,
        default=lambda v:v.isoformat(),separators=(',',':')).encode('utf-8')).hexdigest()


def describe_series(expanded):
    zone=ZoneInfo(expanded['timezone'])
    return expanded['timezone']+': '+('; '.join(a.astimezone(zone).strftime('%Y-%m-%d %H:%M')+' to '+
        b.astimezone(zone).strftime('%Y-%m-%d %H:%M') for a,b in expanded['intervals']))


def retry_series(session, actor, kind, key, fingerprint):
    if not isinstance(key,str) or not re.fullmatch('[0-9a-f]{32}',key):
        raise CalendarError('Refresh the form for a valid series submission identity.')
    series=session.scalar(select(ReservationSeries).where(ReservationSeries.submission_key==key))
    if not series:return None
    parent=session.get(StudentRoomRequest,series.room_request_id) if series.room_request_id is not None else session.get(BorrowRequest,series.borrow_request_id)
    owner=parent.organizer_id if isinstance(parent,StudentRoomRequest) else parent.borrower_id
    if owner!=actor or (kind=='room') != isinstance(parent,StudentRoomRequest) or series.fingerprint!=fingerprint:
        raise CalendarError('This submission identity belongs to a different recurring proposal. Refresh the form.')
    return parent.id


def store_series(session, parent, expanded, key, fingerprint, outcomes=None):
    record=ReservationSeries(room_request_id=parent.id if isinstance(parent,StudentRoomRequest) else None,
        borrow_request_id=parent.id if isinstance(parent,BorrowRequest) else None,
        start_date=expanded['startDate'],end_date=expanded['endDate'],start_minutes=expanded['startMinutes'],
        duration_minutes=expanded['durationMinutes'],weekdays=expanded['weekdays'],timezone=expanded['timezone'],
        submission_key=key,fingerprint=fingerprint)
    record.period_id=expanded['periodId']
    record.approval_mode=expanded['approvalMode']
    session.add(record);session.flush()
    if outcomes is not None and len(outcomes)!=len(expanded['intervals']):raise CalendarError('Occurrence preview does not match the submitted series.')
    session.add_all(ReservationOccurrence(series_id=record.id,ordinal=i,start_at=a,end_at=b,
        status='Unavailable' if outcomes and not outcomes[i-1]['feasible'] else 'Proposed',
        explanation='Unavailable in the submitted preview; staff must recheck.' if outcomes and not outcomes[i-1]['feasible'] else '')
        for i,(a,b) in enumerate(expanded['intervals'],1))
    session.flush()
    return record


def series_view(session, parent):
    record=series_for(session,parent)
    if record is None:return None
    rows=occurrences_for(session,record)
    return {'id':record.id,'periodId':record.period_id,'approvalMode':record.approval_mode,'summary':occurrence_summary(rows),
        'startDate':record.start_date,'endDate':record.end_date,
        'startTime':f'{record.start_minutes//60:02d}:{record.start_minutes%60:02d}',
        'weekdays':record.weekdays,'timezone':record.timezone,'duration':record.duration_minutes,
        'occurrences':[{'id':r.id,'ordinal':r.ordinal,'start':r.start_at,'end':r.end_at,'status':r.status,
                        'explanation':r.explanation,'decidedBy':r.decided_by,'decidedAt':r.decided_at,
                        'canReview':r.start_at>datetime.now(timezone.utc) and r.status in {'Proposed','Unavailable'},
                        'canCancel':r.start_at>datetime.now(timezone.utc) and r.status in {'Proposed','Unavailable','Reserved'}}
                       for r in rows]}


def overlapping_series(kind,start,end):
    column=ReservationSeries.room_request_id if kind=='room' else ReservationSeries.borrow_request_id
    return select(column).join(ReservationOccurrence,ReservationOccurrence.series_id==ReservationSeries.id).where(
        column.is_not(None),ReservationOccurrence.start_at<end,ReservationOccurrence.end_at>start)


def dated_occurrences(session,kind,keys):
    """Batch read-only projection of authoritative dates; no availability decisions."""
    column=ReservationSeries.room_request_id if kind=='room' else ReservationSeries.borrow_request_id
    grouped={}
    for key,row in session.execute(select(column,ReservationOccurrence).join(ReservationOccurrence,
            ReservationOccurrence.series_id==ReservationSeries.id).where(column.in_(keys)).order_by(ReservationOccurrence.ordinal)):
        grouped.setdefault(key,[]).append(row)
    return grouped
