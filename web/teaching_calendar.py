"""Project normalized, published teaching sessions into dated commitments."""

from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func, select, union

from .calendar_service import CalendarError, epoch, expand_weekly
from .persistence.models import (AcademicPeriod, Allocation, AllocationParticipant, AppointmentCommitment,
    Course, CourseSection, CourseSession, Enrollment, LegacyCalendarBinding, Resource,
    RoomOrganizerCommitment, RoomReservation, TeachingAssignment)


def _personal_sections(people):
    return union(select(TeachingAssignment.section_id, TeachingAssignment.user_id).where(
        TeachingAssignment.user_id.in_(people)), select(Enrollment.section_id, Enrollment.user_id).where(
        Enrollment.user_id.in_(people))).subquery()


def _sessions(start, end):
    # Use a day of padding for local periods near a UTC date boundary.
    return (select(CourseSession, CourseSection, Course, AcademicPeriod, Resource)
        .join(CourseSection, CourseSection.id == CourseSession.section_id)
        .join(Course, Course.id == CourseSection.course_id)
        .join(AcademicPeriod, AcademicPeriod.id == CourseSection.academic_period_id)
        .outerjoin(Resource, Resource.id == CourseSession.resource_id)
        .where(AcademicPeriod.start_date <= end.date() + timedelta(days=1),
               AcademicPeriod.end_date >= start.date() - timedelta(days=1))
        .order_by(CourseSession.day, CourseSession.start_minutes, CourseSession.id))


def _expand(class_session, section, period, start, end):
    last = min(period.end_date, class_session.valid_until) if class_session.valid_until else period.end_date
    return expand_weekly(class_session.day, class_session.start_minutes, class_session.end_minutes,
        period.start_date, last, period.timezone, start, end, section.excluded_dates)


def teaching_occurrences(session, start, end, *, people=None, room_ids=None):
    """Yield course records and their explicit occurrence instants within a horizon."""
    query = _sessions(start, end)
    if people is not None:
        links = _personal_sections(people)
        query = query.where(CourseSection.id.in_(select(links.c.section_id)))
    if room_ids is not None:
        query = query.where(CourseSession.resource_id.in_(room_ids))
    for class_session, section, course, period, room in session.execute(query):
        for a, b in _expand(class_session, section, period, start, end):
            yield class_session, section, course, period, room, a, b


def person_teaching_intervals(session, people, start, end, include_details=False):
    links = _personal_sections(people)
    query = _sessions(start, end).join(links, links.c.section_id == CourseSection.id).add_columns(links.c.user_id)
    values = []
    for class_session, section, course, period, _, user_id in session.execute(query):
        title = f"{course.code} · {course.title}"
        values.extend({"userId": user_id, "start": epoch(a), "end": epoch(b),
                       **({"title": title} if include_details else {})}
                      for a, b in _expand(class_session, section, period, start, end))
    return values


def teaching_room_intervals(session, room_ids, start, end):
    return [{"resourceId": room.id, "start": epoch(a), "end": epoch(b)}
            for _, _, _, _, room, a, b in teaching_occurrences(session, start, end, room_ids=room_ids)]


def _term_horizon(periods):
    start = datetime.combine(min(first for _, first, _ in periods) - timedelta(days=1), time(), timezone.utc)
    end = datetime.combine(max(last for _, _, last in periods) + timedelta(days=2), time(), timezone.utc)
    return start, end


def teaching_room_bounds(session, room_ids):
    """Room IDs and total UTC horizon for terms with linked teaching sessions."""
    query = (select(CourseSession.resource_id, func.min(AcademicPeriod.start_date), func.max(AcademicPeriod.end_date))
        .join(CourseSection, CourseSection.id == CourseSession.section_id)
        .join(AcademicPeriod, AcademicPeriod.id == CourseSection.academic_period_id)
        .where(CourseSession.resource_id.in_(room_ids)).group_by(CourseSession.resource_id))
    periods = session.execute(query).all()
    if not periods:
        return set(), None, None
    start, end = _term_horizon(periods)
    return {resource_id for resource_id, _, _ in periods}, start, end


def overlaps_intervals(values, protected, identity):
    by_id = {}
    for row in protected:
        by_id.setdefault(row[identity], []).append((row["start"], row["end"]))
    return any(a < row["end"] and b > row["start"]
               for row in values for a, b in by_id.get(row[identity], ()))


def assert_teaching_commitments_compatible(session):
    """Reject imports that would silently invalidate existing confirmed commitments."""
    commitments = [row for model in (AppointmentCommitment, RoomOrganizerCommitment)
                   for row in session.scalars(select(model))]
    if commitments:
        intervals = person_teaching_intervals(session, {row.user_id for row in commitments},
            min(row.start_at for row in commitments), max(row.end_at for row in commitments))
        protected = [{"userId": row.user_id, "start": row.start_at.timestamp(), "end": row.end_at.timestamp()}
                     for row in commitments]
        if overlaps_intervals(intervals, protected, "userId"):
            raise CalendarError("Published teaching conflicts with a confirmed appointment or room booking.")

    reservations = list(session.scalars(select(RoomReservation)))
    if reservations:
        teaching = teaching_room_intervals(session, {row.resource_id for row in reservations},
            min(row.start_at for row in reservations), max(row.end_at for row in reservations))
        protected = [{"resourceId": row.resource_id, "start": epoch(row.start_at), "end": epoch(row.end_at)}
                     for row in reservations]
        if overlaps_intervals(teaching, protected, "resourceId"):
            raise CalendarError("Published teaching conflicts with a confirmed classroom reservation.")


def assert_teaching_participants_compatible(session, run_id):
    """Protect dated required academic participants before publication or import."""
    if run_id is None:
        return
    attendee_query = (select(Allocation, AllocationParticipant.user_id)
        .join(AllocationParticipant, AllocationParticipant.allocation_id == Allocation.id)
        .where(Allocation.run_id == run_id))
    attendees = session.execute(attendee_query).all()
    if not attendees:
        return
    links = _personal_sections({actor for _, actor in attendees})
    periods = session.execute(select(links.c.user_id, func.min(AcademicPeriod.start_date),
        func.max(AcademicPeriod.end_date)).select_from(links)
        .join(CourseSection, CourseSection.id == links.c.section_id)
        .join(CourseSession, CourseSession.section_id == CourseSection.id)
        .join(AcademicPeriod, AcademicPeriod.id == CourseSection.academic_period_id)
        .group_by(links.c.user_id)).all()
    if not periods:
        return
    known = {actor for actor, _, _ in periods}
    start, end = _term_horizon(periods)

    bookings, choices = [], {}
    request_ids = {row.request_id for row, actor in attendees if actor in known}
    for binding, period in session.execute(select(LegacyCalendarBinding, AcademicPeriod)
            .join(AcademicPeriod, AcademicPeriod.id == LegacyCalendarBinding.period_id)
            .where(LegacyCalendarBinding.request_id.in_(request_ids))):
        choices.setdefault(binding.request_id, []).append((binding, period))
    if request_ids.difference(choices):
        raise CalendarError("A required academic participant has published teaching. Configure explicit calendar bindings before publishing.")
    for row, actor in attendees:
        if actor not in known:
            continue
        for binding, period in choices[row.request_id]:
            bookings.extend({"userId": actor, "start": epoch(a), "end": epoch(b)} for a, b in
                expand_weekly(row.day, row.start_minutes, row.end_minutes, period.start_date, period.end_date,
                              period.timezone, start, end, binding.excluded_dates, binding.week_start))
    if bookings:
        teaching = person_teaching_intervals(session, known,
            datetime.fromtimestamp(min(row["start"] for row in bookings), timezone.utc),
            datetime.fromtimestamp(max(row["end"] for row in bookings), timezone.utc))
        if overlaps_intervals(bookings, teaching, "userId"):
            raise CalendarError("A required academic participant is teaching or enrolled at this time. Previous results remain active.")
