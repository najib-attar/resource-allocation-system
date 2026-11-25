"""Read-only catalogue, personal teaching and classroom timetable queries."""

from collections import defaultdict
from datetime import datetime, time, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select

from .persistence.models import (AcademicPeriod, Course, CourseSection, CourseSession, Enrollment, Resource,
                                 TeachingAssignment)
from .room_request_service import room_availability, room_availability_query
from .teaching_calendar import teaching_occurrences
from .university_calendar import selection


def _source_link(value):
    if not value:
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    return value if parsed.scheme == "https" and parsed.hostname and not parsed.username else None


def _classroom_scope():
    return or_(Resource.type == "Classroom", select(CourseSession.id)
               .where(CourseSession.resource_id == Resource.id).exists())


def _room_ids(session, actor):
    return set(session.scalars(room_availability_query(session, actor).with_only_columns(Resource.id)))


def _teachers(session, section_ids):
    result = defaultdict(list)
    rows = session.execute(select(TeachingAssignment.section_id, TeachingAssignment.published_name)
                           .where(TeachingAssignment.section_id.in_(section_ids))
                           .order_by(TeachingAssignment.ordinal))
    for section_id, name in rows:
        result[section_id].append(name)
    return result


def _location(meeting, room, allowed_rooms):
    if room is not None:
        return room.name, room.id if room.id in allowed_rooms else None
    if meeting.building_code and not meeting.room_code:
        return f"{meeting.building_code} · Classroom unspecified", None
    published = " ".join(value for value in (meeting.building_code, meeting.room_code) if value and value != "--")
    return published or "Classroom unspecified", None


def _details(session, query, allowed_rooms):
    rows = list(session.execute(query.select_from(CourseSection).join(Course, Course.id == CourseSection.course_id)
        .join(AcademicPeriod, AcademicPeriod.id == CourseSection.academic_period_id)
        .order_by(AcademicPeriod.start_date.desc(), Course.code, CourseSection.crn)))
    section_ids = [section.id for section, _, _ in rows]
    teachers = _teachers(session, section_ids)
    meetings = defaultdict(list)
    for meeting, room in session.execute(select(CourseSession, Resource)
            .outerjoin(Resource, Resource.id == CourseSession.resource_id)
            .where(CourseSession.section_id.in_(section_ids)).order_by(CourseSession.ordinal)):
        location, room_id = _location(meeting, room, allowed_rooms)
        meetings[meeting.section_id].append({"day": meeting.published_day, "start": meeting.published_start,
            "end": meeting.published_end, "location": location, "room_id": room_id,
            "capacity": room.capacity if room_id is not None else None, "external": meeting.building_code == "MDB"})
    return [{"id": section.id, "course": course, "title": section.published_title, "crn": section.crn,
             "term": period.name, "branch": section.branch, "level": section.academic_level,
             "instruction": section.instruction_method, "quota": section.quota,
             "source": _source_link(section.source_url), "source_kind": section.source_kind,
             "teachers": teachers[section.id], "meetings": meetings[section.id]} for section, course, period in rows]


def _weekly_classes(session, week, allowed_rooms, **scope):
    occurrences = list(teaching_occurrences(session, week["start"], week["end"], **scope))
    teachers = _teachers(session, {section.id for _, section, *_ in occurrences})
    days = defaultdict(list)
    zone = ZoneInfo(week["zone"])
    for meeting, section, course, _, room, start, end in sorted(
            occurrences, key=lambda row: (row[5], row[2].code, row[1].crn)):
        start, end = start.astimezone(zone), end.astimezone(zone)
        location, room_id = _location(meeting, room, allowed_rooms)
        days[start.date()].append({"id": section.id, "course": course, "title": section.published_title,
            "crn": section.crn, "teachers": teachers[section.id], "location": location, "room_id": room_id,
            "start": start, "end": end})
    return dict(days)


def _room_periods(room, dates):
    """Clip occupied blocks to each local calendar day and show their complement."""
    zone = ZoneInfo(room["zone"])
    result = {}
    for day in dates:
        first = datetime.combine(day, time(), zone)
        last = datetime.combine(day + timedelta(days=1), time(), zone)
        occupied = []
        for interval in room["busy"]:
            start, end = max(first, interval["start"]), min(last, interval["end"])
            if start >= end:
                continue
            if occupied and start <= occupied[-1][1]:
                occupied[-1] = (occupied[-1][0], max(end, occupied[-1][1]))
            else:
                occupied.append((start, end))
        periods = []
        cursor = first
        free_allowed = room["enabled"] and not room["unresolved"]
        for start, end in occupied:
            if free_allowed and cursor < start:
                periods.append((cursor, start, False))
            periods.append((start, end, True))
            cursor = end
        if free_allowed and cursor < last:
            periods.append((cursor, last, False))
        result[day] = periods
    return result


class CourseService:
    def __init__(self, database):
        self.database = database

    def catalog(self, search):
        query = (select(Course.id, Course.code, Course.title, func.count(CourseSection.id).label("sections"))
                 .join(CourseSection, CourseSection.course_id == Course.id).group_by(Course.id).order_by(Course.code))
        if search:
            matching_sections = select(CourseSection.course_id).where(or_(
                CourseSection.crn.icontains(search, autoescape=True),
                CourseSection.published_title.icontains(search, autoescape=True))).correlate(None)
            query = query.where(or_(Course.code.icontains(search, autoescape=True),
                Course.title.icontains(search, autoescape=True), Course.id.in_(matching_sections)))
        with self.database.transaction(read_only=True) as session:
            return list(session.execute(query))

    def detail(self, actor, course_id):
        query = select(CourseSection, Course, AcademicPeriod).where(CourseSection.course_id == course_id)
        with self.database.transaction(read_only=True) as session:
            return _details(session, query, _room_ids(session, actor))

    def personal(self, actor, role, date):
        if role == "Student":
            owned = select(Enrollment.section_id).where(Enrollment.user_id == actor)
        elif role == "Instructor":
            owned = select(TeachingAssignment.section_id).where(TeachingAssignment.user_id == actor)
        else:
            raise PermissionError("My Courses is available to students and instructors.")
        week = selection("week", date)
        query = select(CourseSection, Course, AcademicPeriod).where(CourseSection.id.in_(owned))
        with self.database.transaction(read_only=True) as session:
            allowed_rooms = _room_ids(session, actor)
            sections = _details(session, query, allowed_rooms)
            days = _weekly_classes(session, week, allowed_rooms, people=[actor])
        return {"sections": sections, "week": week, "classes": days}

    def rooms(self, actor):
        with self.database.transaction(read_only=True) as session:
            query = room_availability_query(session, actor).where(_classroom_scope()).order_by(Resource.building,
                Resource.name)
            return [{"id": room.id, "name": room.name, "building": room.building, "capacity": room.capacity,
                "enabled": bool(policy and policy.enabled and room.available)} for room, policy in session.execute(query)]

    def room(self, actor, room_id, date):
        week = selection("week", date)
        with self.database.transaction(read_only=True) as session:
            room = room_availability(session, actor, room_id, week["start"], week["end"])
            days = _weekly_classes(session, week, {room_id}, room_ids=[room_id])
        return {"room": room, "week": week, "classes": days, "periods": _room_periods(room, week["dates"])}
