"""Verify normalized teaching intervals against PostgreSQL and the real engines."""

from datetime import date, timedelta

from sqlalchemy import select

from postgres_fixtures import PostgresTestCase, ROOT
from test_appointments import START, seed_appointments
from web.academic_eligibility import EligibilityService
from web.account_service import AccountService
from web.allocation_workflow import execute_allocation
from web.appointment_service import AppointmentError, AppointmentService
from web.calendar_service import CalendarError
from web.engine_gateway import EngineGateway
from web.persistence.models import (AcademicPeriod, Appointment, Course, CourseSection, CourseSession, Enrollment,
    RequestEligibility, RoomReservation, StudentRoomRequest, TeachingAssignment)
from web.persistence.repository import Repository
from web.room_request_service import RoomRequestError, RoomRequestService
from web.teaching_calendar import assert_teaching_commitments_compatible
from web.university_calendar import UniversityCalendarService


class CourseAvailabilityTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        self.faculty = seed_appointments(self.database)
        account = AccountService(self.database)
        for actor in (1, 2, 3, 4):
            account.provision(actor, f"course-test-{actor}", "Fixture-password-for-2026", administrator=actor == 3)
        self.gateway = EngineGateway(ROOT)
        self.appointments = AppointmentService(self.database, self.gateway)
        self.rooms = RoomRequestService(self.database, self.gateway)
        self.rooms.configure_approver(3, self.faculty, 3)
        self.rooms.configure_room(3, 301, self.faculty, True, ["study"])
        with self.database.transaction() as session:
            period = AcademicPeriod(name="Teaching course integration test", start_date=date(2030, 1, 7),
                end_date=date(2030, 1, 31), timezone="Europe/Istanbul", is_semester=True)
            course = Course(code="BLG 100", title="Sample class")
            session.add_all([period, course])
            session.flush()
            self.period_id, self.course_id = period.id, course.id

    def seed_class(self, *, room_id=301, actor=2, enrolled=None):
        with self.database.transaction() as session:
            section = CourseSection(course_id=self.course_id, academic_period_id=self.period_id, crn="30303",
                quota=20, published_title="Sample class", branch="BLG", academic_level="LS",
                instruction_method="In person", source_kind="archive", source_url="https://example.invalid/course",
                publication_status="scheduled", published_schedule={}, excluded_dates=["2030-01-14"])
            session.add(section)
            session.flush()
            session.add(TeachingAssignment(section_id=section.id, ordinal=1, user_id=actor,
                                          published_name="Professor Ada"))
            if enrolled is not None:
                session.add(Enrollment(section_id=section.id, user_id=enrolled))
            session.add(CourseSession(section_id=section.id, ordinal=1, resource_id=room_id,
                building_code="BBB" if room_id else None, room_code="Z-17" if room_id else None,
                day=1, start_minutes=600, end_minutes=660, published_day="Pazartesi", published_start="10:00",
                published_end="10:59", published_building="BBB" if room_id else "--",
                published_room="Z-17" if room_id else "--"))
            assert_teaching_commitments_compatible(session)

    def room_values(self, start=START):
        return {"start": start, "duration": 60, "count": 10, "category": "study",
                "purpose": "Study group", "features": []}

    def test_course_room_blocks_real_engine_and_direct_booking(self):
        self.seed_class()
        result = self.rooms.recommend(1, self.room_values(), [])
        self.assertFalse(any(row["roomId"] == 301 for row in result["candidates"]))
        with self.assertRaises(RoomRequestError):
            self.rooms.submit(1, self.room_values(), [], 301)
        with self.database.transaction(read_only=True) as session:
            self.assertIsNone(session.scalar(select(StudentRoomRequest.id)))
        self.assertEqual(len(self.rooms.availability(1, 301, START.date())["busy"]), 1)
        next_week = START + timedelta(days=7)
        self.assertEqual(self.rooms.availability(1, 301, next_week.date())["busy"], [])
        self.assertGreater(self.rooms.submit(1, self.room_values(START + timedelta(hours=1)), [], 301), 0)

    def test_unresolved_room_still_blocks_professor_and_enrolled_student(self):
        self.seed_class(room_id=None, enrolled=4)
        with self.assertRaisesRegex(AppointmentError, "professor is unavailable"):
            self.appointments.submit(1, [2], [], "Course conflicts", 60, START, self.faculty)
        with self.assertRaisesRegex(AppointmentError, "organizing student is unavailable"):
            self.appointments.submit(4, [3], [], "Own timetable conflicts", 60, START, self.faculty)
        with self.database.transaction(read_only=True) as session:
            self.assertIsNone(session.scalar(select(Appointment.id)))
        self.assertGreater(self.appointments.submit(1, [2], [], "Recess", 60, START + timedelta(days=7), self.faculty), 0)
        self.assertGreater(self.appointments.submit(4, [2], [], "Adjacent", 60, START + timedelta(hours=1), self.faculty), 0)
        calendar = UniversityCalendarService(self.database)
        for actor in (2, 4):
            self.assertTrue(any(event["id"].startswith("course:") for event in calendar.load(
                actor, "day", START.date().isoformat())["events"]))
        self.assertFalse(any(event["id"].startswith("course:") for event in calendar.load(
            1, "day", START.date().isoformat())["events"]))

    def test_course_import_rejects_a_confirmed_classroom_conflict(self):
        request = self.rooms.submit(1, self.room_values(), [], 301)
        self.rooms.decide(request, 3, 1, True)
        with self.assertRaisesRegex(CalendarError, "confirmed classroom reservation"):
            self.seed_class()
        with self.database.transaction(read_only=True) as session:
            self.assertIsNone(session.scalar(select(CourseSession.id)))
            self.assertIsNotNone(session.scalar(select(RoomReservation.request_id)))

    def test_course_import_rejects_a_confirmed_appointment_conflict(self):
        appointment = self.appointments.submit(1, [2], [], "Approved review", 60, START, self.faculty)
        self.appointments.decide(appointment, 2, 1, True)
        with self.assertRaisesRegex(CalendarError, "confirmed appointment or room booking"):
            self.seed_class(room_id=None)
        self.assertEqual(self.appointments.detail(appointment, 2)["status"], "Confirmed")
        with self.database.transaction(read_only=True) as session:
            self.assertIsNone(session.scalar(select(CourseSession.id)))

    def approved_request(self, request):
        repository = Repository(self.database)
        key = repository.save_request(request)
        with self.database.transaction(read_only=True) as session:
            version = session.get(RequestEligibility, key).version
            period = session.get(AcademicPeriod, self.period_id)
        EligibilityService(self.database).decide(3, key, 1, version, True, "Reviewed course fixture")
        self.appointments.bind_legacy(period.name, period.start_date, period.end_date,
            request_id=key, week_start=period.start_date)
        return key

    def test_course_room_guard_preserves_the_previous_academic_publication(self):
        self.seed_class()
        repository = Repository(self.database)

        def approved_request(day):
            return self.approved_request({
                "type": "OneTime", "requesterId": 2, "spaceId": 301, "participantCount": 12,
                "title": "Academic review", "purpose": "Course overlap verification",
                "slots": [{"day": day, "startMinutes": 600, "endMinutes": 660}],
            })

        clear = approved_request(2)
        result = execute_allocation(repository, self.gateway)
        self.assertEqual([row["requestId"] for row in result["allocations"]], [clear])
        _, previous, active = repository.read_view()
        approved_request(1)
        with self.assertRaisesRegex(CalendarError, "conflicts with published teaching"):
            execute_allocation(repository, self.gateway)
        _, result, still_active = repository.read_view()
        self.assertEqual(still_active, active)
        self.assertEqual(result, previous)

    def test_academic_participant_guard_protects_enrollment_without_a_classroom(self):
        self.seed_class(room_id=None, enrolled=4)
        repository = Repository(self.database)
        self.approved_request({
            "type": "CommitteeMeeting", "requesterId": 2, "spaceId": 301, "participantCount": 3,
            "title": "Academic committee", "purpose": "Required participants must attend",
            "participants": [{"userId": 4, "role": "Member"}],
            "slots": [{"day": 1, "startMinutes": 600, "endMinutes": 660}],
        })
        with self.assertRaisesRegex(CalendarError, "required academic participant is teaching or enrolled"):
            execute_allocation(repository, self.gateway)
        _, _, active = repository.read_view()
        self.assertIsNone(active)
