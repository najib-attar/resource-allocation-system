"""Install the signed-off public teaching dataset in the owned ITU demo."""

from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
import hashlib
import random
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, or_, select

from ..room_calendar import assert_room_publication, valid_approvers
from ..teaching_calendar import assert_teaching_commitments_compatible, assert_teaching_participants_compatible
from .itu_demo import DATA, DEPARTMENTS, FACULTY, load_itu_schedule
from .itu_course_inputs import course_inputs
from .itu_resources import OCCUPANCY_REASON, catalog_manifest
from .models import (ROOM_CATEGORIES, AcademicPeriod, BusySlot, Course, CourseImport, CourseSection, CourseSession,
    Enrollment, LegacyCalendarBinding, OrganizationUnit, Resource, Role, RoomClosure, RoomPolicy, TeachingAssignment, User)
from .repository import state_row


COURSE_SEED = "itu_course_seed_2026_2027_fall.json"
ADDITIONAL_ROOMS = {"Z-23": (70, True), "122": (25, False)}


def _course_rooms(session, faculty, catalog):
    if faculty is None or faculty not in valid_approvers(session):
        raise ValueError("The ITU room catalog needs its existing faculty approver.")
    names = defaultdict(list)
    for resource in session.scalars(select(Resource).where(Resource.building == "BBB")):
        names[resource.name].append(resource)
    rooms = {}
    for item in catalog["resources"]:
        code = item.get("roomCode")
        if not code:
            continue
        matches = names[item["name"]]
        if len(matches) != 1:
            raise ValueError(f"Expected one existing BBB room for OBS identifier {code}.")
        rooms[code] = matches[0]
    next_order = session.scalar(select(func.max(Resource.source_order))) or 0
    for code, (capacity, enabled) in ADDITIONAL_ROOMS.items():
        name = f"BBB {code}"
        matches = names[name]
        if len(matches) > 1 or matches and (matches[0].type != "Classroom" or matches[0].capacity != capacity
                or (not enabled and matches[0].available)):
            raise ValueError(f"Existing {name} does not match the agreed classroom configuration.")
        if matches:
            policy = session.get(RoomPolicy, matches[0].id)
            if policy is None or policy.faculty_id != faculty or (not enabled and policy.enabled):
                raise ValueError(f"Existing {name} needs the agreed faculty and booking policy.")
            rooms[code] = matches[0]
            continue
        next_order += 1
        room = Resource(source_order=next_order, name=name, type="Classroom", capacity=capacity,
                        building="BBB", available=enabled, projector=True, whiteboard=True, computers=False)
        session.add(room)
        session.flush()
        session.add(RoomPolicy(resource_id=room.id, faculty_id=faculty, enabled=enabled, restricted=False,
                               categories=list(ROOM_CATEGORIES)))
        rooms[code] = room
    return rooms


def _overlap(left, right):
    return (left["day"] == right["day"] and left["start_minutes"] < right["end_minutes"]
            and right["start_minutes"] < left["end_minutes"])


def _enroll_demo_students(session, sections, persisted, schedule, rooms, seed):
    hints = defaultdict(set)
    for row in schedule["sections"]:
        for department, years in row["recommendedYears"].items():
            hints[row["section"]].update((department, year) for year in years)
    capacities = {room.id: room.capacity for room in rooms.values()}
    by_cohort, places = defaultdict(list), {}
    for row in sections:
        times = row["sessions"]
        if (row["academic_level"] != "LS" or not row["quota"] or not times
                or any(_overlap(slot, other) for i, slot in enumerate(times) for other in times[:i])):
            continue
        places[row["crn"]] = min([row["quota"], *(capacities[slot["resource_id"]] for slot in times
            if slot["resource_id"] in capacities)])
        for cohort in hints[row["crn"]]:
            by_cohort[cohort].append(row)

    names = {name: code for code, name in DEPARTMENTS.items()}
    students = session.execute(select(User, OrganizationUnit.name)
        .join(OrganizationUnit, OrganizationUnit.id == User.primary_unit_id)
        .join(Role, Role.id == User.primary_role_id).where(Role.name == "Student",
              User.student_no.like("ITU-DEMO-26-%"), OrganizationUnit.name.in_(names))
        .order_by(User.source_order)).all()
    rng, choices, assigned = random.Random(seed), {}, defaultdict(list)
    for user, unit in students:
        options = list(by_cohort[names[unit], user.year_level])
        rng.shuffle(options)
        choices[user.id] = options
    for _ in range(4):
        for user, _ in students:
            saved = assigned[user.id]
            for option in choices[user.id]:
                crn = option["crn"]
                if places[crn] == 0 or any(option["course_code"] == course["course_code"]
                        or any(_overlap(a, b) for a in option["sessions"] for b in course["sessions"]) for course in saved):
                    continue
                saved.append(option)
                places[crn] -= 1
                session.add(Enrollment(user_id=user.id, section_id=persisted[crn]))
                break
    return dict(students=len(students), enrolledStudents=sum(bool(rows) for rows in assigned.values()),
                enrollments=sum(map(len, assigned.values())),
                studentsWithoutVerifiedSections=sum(not rows for rows in assigned.values()))


def _retire_old_course_projections(session, term, resources):
    selectors = [BusySlot.reason.startswith("Published teaching: "),
                 BusySlot.reason.startswith("Simulated enrollment: ")]
    selectors.extend(BusySlot.reason.like(f"Simulated {dept} year % study session") for dept in DEPARTMENTS)
    bound = list(session.scalars(select(BusySlot.id).join(LegacyCalendarBinding,
        LegacyCalendarBinding.busy_slot_id == BusySlot.id)
        .where(LegacyCalendarBinding.period_id == term.id, or_(*selectors))))
    if session.scalar(select(LegacyCalendarBinding.id).where(LegacyCalendarBinding.busy_slot_id.in_(bound),
            LegacyCalendarBinding.period_id != term.id).limit(1)) is not None:
        raise ValueError("A legacy teaching block is referenced by another term. Existing schedules were preserved.")
    session.execute(delete(LegacyCalendarBinding).where(LegacyCalendarBinding.busy_slot_id.in_(bound)))
    session.execute(delete(BusySlot).where(BusySlot.id.in_(bound)))
    zone = ZoneInfo(term.timezone)
    holds = session.execute(delete(RoomClosure).where(RoomClosure.reason == OCCUPANCY_REASON,
        RoomClosure.resource_id.in_([room.id for room in resources.values()]),
        RoomClosure.start_at >= datetime.combine(term.start_date, time(), zone),
        RoomClosure.start_at < datetime.combine(term.end_date + timedelta(days=1), time(), zone))).rowcount
    return dict(personalSlots=len(bound), roomHolds=holds)


def install_itu_courses(database, directory=DATA, seed=42):
    schedule = load_itu_schedule(directory)
    period = schedule["academicPeriod"]
    attachment = directory / COURSE_SEED
    supplemental = next((directory / name for name in ("course_room_schedule.json", "room_schedule.json")
                         if (directory / name).is_file()), None)
    source_hash = hashlib.sha256(attachment.read_bytes()).hexdigest()
    supplemental_hash = hashlib.sha256(supplemental.read_bytes()).hexdigest() if supplemental else None
    catalog = catalog_manifest(directory, schedule)
    with database.transaction() as session:
        state = state_row(session, lock=True)
        term = session.scalar(select(AcademicPeriod).where(AcademicPeriod.name == period["name"],
            AcademicPeriod.start_date == date.fromisoformat(period["startDate"]),
            AcademicPeriod.end_date == date.fromisoformat(period["endDate"]),
            AcademicPeriod.timezone == period["timezone"], AcademicPeriod.is_semester.is_(True)))
        if term is None:
            raise ValueError("This profile does not contain the expected ITU Fall semester.")
        previous = session.get(CourseImport, term.id)
        if previous:
            if (previous.source_sha256, previous.supplement_sha256) != (source_hash, supplemental_hash):
                raise ValueError("This term already has an imported catalog. Existing courses were preserved.")
            return previous.report
        if session.scalar(select(CourseSection.id).where(CourseSection.academic_period_id == term.id).limit(1)) is not None:
            raise ValueError("This term contains unmanaged course sections. Existing courses were preserved.")

        faculty = session.scalar(select(OrganizationUnit.id).where(OrganizationUnit.name == FACULTY))
        rooms = _course_rooms(session, faculty, catalog)
        staff = [dict(id=identifier, name=name) for identifier, name in session.execute(
            select(User.id, User.name).join(Role, User.primary_role_id == Role.id)
            .where(Role.name.in_(("Instructor", "TeachingAssistant"))))]
        parsed = course_inputs(attachment, staff, {code: room.id for code, room in rooms.items()}, supplemental)
        if parsed["sourceSha256"] != source_hash or (supplemental and hashlib.sha256(
                supplemental.read_bytes()).hexdigest() != supplemental_hash):
            raise ValueError("A source file changed during import. Retry with stable input files.")

        courses = {row.code: row for row in session.scalars(select(Course))}
        sections = parsed["sections"]
        persisted, mismatches, unresolved_names = {}, [], Counter()
        for row in sections:
            code, crn = row["course_code"], row["crn"]
            course = courses.get(code)
            if course is None:
                course = courses[code] = Course(code=code, title=row["course_name"])
                session.add(course)
                session.flush()
            section = CourseSection(course_id=course.id, academic_period_id=term.id, crn=crn,
                published_title=row["course_name"], branch=row["branch"], academic_level=row["academic_level"],
                instruction_method=row["instruction_method"] or "", quota=row["quota"],
                source_kind="archive" if row["source_kind"] == "archive" else "obs", source_url=row["source_url"],
                publication_status="scheduled" if row["sessions"] else "unpublished",
                published_schedule=row["published_schedule"], excluded_dates=period["recessDates"])
            session.add(section)
            session.flush()
            persisted[crn] = section.id
            for ordinal, person in enumerate(row["instructors"], 1):
                session.add(TeachingAssignment(section_id=section.id, ordinal=ordinal,
                    published_name=person["name"], user_id=person["user_id"]))
                if person["user_id"] is None:
                    unresolved_names[person["name"]] += 1
            for slot in row["sessions"]:
                session.add(CourseSession(section_id=section.id, ordinal=slot["ordinal"],
                    resource_id=slot["resource_id"], building_code=slot["building"], room_code=slot["room"],
                    day=slot["day"], start_minutes=slot["start_minutes"], end_minutes=slot["end_minutes"],
                    published_day=slot["day_published"], published_start=slot["start_time_published"],
                    published_end=slot["end_time_published"], published_building=slot["building_published"],
                    published_room=slot["room_published"],
                    valid_until=date.fromisoformat(slot["valid_until"]) if slot["valid_until"] else None))
                room = rooms.get(slot["room"]) if slot["resource_id"] else None
                if room and row["quota"] is not None and row["quota"] > room.capacity:
                    mismatches.append(dict(crn=crn, course=code, session=slot["ordinal"], room=room.name,
                                           quota=row["quota"], demonstrationCapacity=room.capacity))

        students = _enroll_demo_students(session, sections, persisted, schedule, rooms, seed)
        retired = _retire_old_course_projections(session, term, rooms)
        session.flush()
        assert_teaching_commitments_compatible(session)
        assert_room_publication(session, state.active_run_id)
        assert_teaching_participants_compatible(session, state.active_run_id)
        state.input_revision += 1
        state.calendar_revision += 1
        report = dict(term=parsed["term"], timezone=parsed["timezone"], sourceSha256=source_hash,
            supplementalSha256=supplemental_hash, primary=parsed["primaryCounts"],
            sectionCount=len(sections), courseCount=len({row["course_code"] for row in sections}),
            weeklySessions=sum(len(row["sessions"]) for row in sections), supplementalSections=parsed["supplementalCount"],
            unresolvedTeachers=dict(unresolved_names), enrollment=students, retiredProjections=retired,
            quotaDiscrepancies=mismatches, supplementalConflicts=parsed["supplementalConflicts"],
            instructorAliases=parsed.get("instructorAliases", {}),
            resourceCount=session.scalar(select(func.count()).select_from(Resource)),
            addedClassrooms={code: dict(id=rooms[code].id, capacity=seats, provisional=not enabled)
                             for code, (seats, enabled) in ADDITIONAL_ROOMS.items()})
        session.add(CourseImport(academic_period_id=term.id, source_sha256=source_hash,
            supplement_sha256=supplemental_hash, provenance=dict(archive=parsed["provenance"],
                supplemental=parsed["supplementalSources"]), report=report))
        return report
