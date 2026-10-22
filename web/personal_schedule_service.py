"""One authenticated user's dated timetable, projected from authoritative records."""

import calendar
from datetime import date, datetime, time, timedelta, timezone
import re

from sqlalchemy import and_, or_, select

from .calendar_service import CalendarError, aware, legacy_intervals, local_instant, university_zone
from .persistence.models import Appointment, AppointmentInvitation, AppointmentProfessor, CalendarBlock, User, StudentRoomRequest, RoomInvitation, Resource, RoomReservation
from .persistence.repository import state_row


def select_calendar(month=None, week=None, now=None):
    zone = university_zone()
    today = aware(now or datetime.now(timezone.utc)).astimezone(zone).date()
    try:
        selected_day = date.fromisoformat(week) if week is not None else today
        value = month if month is not None else selected_day.strftime("%Y-%m")
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}", value):
            raise ValueError()
        first = date.fromisoformat(value + "-01")
        if not 1970 <= first.year <= 2099:
            raise ValueError()
        last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
        weeks = [row[0] for row in calendar.Calendar().monthdatescalendar(first.year, first.month)]
        selected_week = selected_day - timedelta(days=selected_day.weekday())
        if week is not None and selected_week not in weeks:
            raise ValueError()
        if selected_week not in weeks:
            selected_week = weeks[0]
    except (TypeError, ValueError, OverflowError) as error:
        raise CalendarError("Choose a valid month and a week belonging to that month (1970-2099).") from error
    # Read-only month padding can cross the engine's date range; bookings cannot.
    start = local_instant(datetime.combine(selected_week, time()), zone, check_range=False)
    end = local_instant(datetime.combine(selected_week + timedelta(days=7), time()), zone, check_range=False)
    return {"month": value, "monthTitle": first.strftime("%B %Y"), "monthStart": first, "monthEnd": last,
            "weeks": weeks, "weekStart": selected_week, "weekEnd": selected_week + timedelta(days=6),
            "start": start, "end": end, "zone": zone.key, "today": today}


def read_schedule(session, actor, selection):
    """Used inside the caller's snapshot, including the student Home transaction."""
    if type(actor) is not int or actor <= 0:
        raise PermissionError("An active university identity is required.")
    user = session.get(User, actor)
    if user is None or user.status.casefold() != "active":
        raise PermissionError("An active university identity is required.")
    start, end = selection["start"], selection["end"]
    zone = university_zone()
    query = select(Appointment, AppointmentProfessor.user_id).outerjoin(AppointmentProfessor, and_(
        AppointmentProfessor.appointment_id == Appointment.id, AppointmentProfessor.user_id == actor)).outerjoin(
        AppointmentInvitation, and_(AppointmentInvitation.appointment_id == Appointment.id, AppointmentInvitation.user_id == actor))
    query = query.where(or_(Appointment.organizer_id == actor, AppointmentProfessor.user_id == actor,
                           AppointmentInvitation.status == "Invited"), Appointment.status == "Confirmed",
                        Appointment.start_at < end, Appointment.end_at > start).order_by(Appointment.start_at, Appointment.id)
    events = [{"start": row.start_at.astimezone(zone), "end": row.end_at.astimezone(zone), "title": row.purpose,
               "kind": "Appointment" if row.organizer_id == actor or professor_id == actor else "Optional invitation",
               "appointmentId": row.id} for row, professor_id in session.execute(query)]
    room_query = select(StudentRoomRequest, Resource.name,RoomReservation).join(Resource,Resource.id == StudentRoomRequest.resource_id).join(
        RoomReservation,RoomReservation.request_id==StudentRoomRequest.id).outerjoin(
        RoomInvitation,and_(RoomInvitation.request_id == StudentRoomRequest.id,RoomInvitation.user_id == actor)).where(
        StudentRoomRequest.status == 'Confirmed',RoomReservation.start_at < end,RoomReservation.end_at > start,
        or_(StudentRoomRequest.organizer_id == actor,RoomInvitation.status == 'Accepted')).order_by(StudentRoomRequest.start_at,StudentRoomRequest.id)
    events += [{'start':booking.start_at.astimezone(zone),'end':booking.end_at.astimezone(zone),'title':row.purpose+' - '+room_name,
                'kind':'Room booking' if row.organizer_id == actor else 'Optional invitation','appointmentId':None,'roomRequestId':row.id}
               for row,room_name,booking in session.execute(room_query)]
    blocks = list(session.scalars(select(CalendarBlock).where(CalendarBlock.user_id == actor).order_by(CalendarBlock.start_at, CalendarBlock.id)))
    events += [{"start": row.start_at.astimezone(zone), "end": row.end_at.astimezone(zone),
                "title": row.reason or "Personal blocked time", "kind": "Personal block", "appointmentId": None}
               for row in blocks if row.start_at < end and row.end_at > start]
    intervals, unresolved = legacy_intervals(session, [actor], start, end, state_row(session).active_run_id, include_details=True)
    events += [{"start": datetime.fromtimestamp(row["start"], zone), "end": datetime.fromtimestamp(row["end"], zone),
                "title": row["title"], "kind": "University", "appointmentId": None} for row in intervals]
    events.sort(key=lambda row: (row["start"], row["end"], row["kind"], row["appointmentId"] or 0))
    days = []
    for offset in range(5):
        day = selection["weekStart"] + timedelta(days=offset)
        day_start = local_instant(datetime.combine(day, time()), zone, check_range=False)
        day_end = local_instant(datetime.combine(day + timedelta(days=1), time()), zone, check_range=False)
        entries = [row for row in events if row["start"] < day_end and row["end"] > day_start]
        days.append({"date": day, "entries": entries, "outsideMonth": day.month != selection["monthStart"].month})
    first_hour, last_hour = 8, 18
    for day in days:
        for item in day["entries"]:
            first_hour = min(first_hour, item["start"].hour if item["start"].date() == day["date"] else 0)
            last_hour = max(last_hour, (item["end"].hour + bool(item["end"].minute)) if item["end"].date() == day["date"] else 24)
    rows = []
    for hour in range(first_hour, last_hour):
        cells = []
        for day in days:
            a = local_instant(datetime.combine(day["date"], time()) + timedelta(hours=hour), zone, check_range=False)
            b = local_instant(datetime.combine(day["date"], time()) + timedelta(hours=hour + 1), zone, check_range=False)
            entries = [{**item, "continues": item["start"] < a} for item in day["entries"] if item["start"] < b and item["end"] > a]
            cells.append({"entries": entries, "outsideMonth": day["outsideMonth"]})
        rows.append({"label": f"{hour:02d}:00", "cells": cells})
    weekend_start = local_instant(datetime.combine(selection["weekStart"] + timedelta(days=5), time()), zone, check_range=False)
    weekend = [row for row in events if row["start"] < end and row["end"] > weekend_start]
    return {**selection, "days": days, "rows": rows, "weekend": weekend, "unresolved": bool(unresolved),
            "blocks": [{"id": row.id, "start": row.start_at, "end": row.end_at, "reason": row.reason} for row in blocks]}


class PersonalScheduleService:
    def __init__(self, database):
        self.database = database

    def load(self, actor, month=None, week=None, now=None):
        selection = select_calendar(month, week, now)
        with self.database.transaction(read_only=True) as session:
            return read_schedule(session, actor, selection)
