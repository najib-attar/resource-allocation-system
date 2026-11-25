"""Actual Flask pages over persisted course, teaching and enrollment relationships."""

from datetime import date, timedelta

from sqlalchemy import select

from auth_fixtures import authorized_client
from postgres_fixtures import PostgresTestCase
from test_appointments import START, seed_appointments
from web import app as web_app
from web.account_service import AccountService
from web.persistence.models import (AcademicPeriod, Course, CourseSection, CourseSession, Enrollment,
                                     Resource, Role, RoomClosure, RoomPolicy, TeachingAssignment, User)


class CoursePageTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        faculty_id = seed_appointments(self.database)
        with self.database.transaction() as session:
            room = session.get(Resource, 301)
            room.name, room.building, room.type = "BBB Z-17", "BBB", "Classroom"
            session.add(Resource(id=302, source_order=2, name="Restricted classroom", type="Classroom",
                                 building="BBB", capacity=20))
            session.flush()
            for key in (301, 302):
                session.add(RoomPolicy(resource_id=key, faculty_id=faculty_id, enabled=True, restricted=key == 302))
            session.add(RoomClosure(resource_id=301, start_at=START + timedelta(hours=5),
                                    end_at=START + timedelta(hours=6), reason="Private maintenance information"))
            staff_role = session.scalar(select(Role.id).where(Role.name == "Staff"))
            session.get(User, 5).primary_role_id = staff_role
            period = AcademicPeriod(name="Synthetic course term", start_date=date(2030, 1, 7),
                end_date=date(2030, 1, 31), timezone="Europe/Istanbul", is_semester=True)
            first, second = Course(code="BLG 210", title="Interfaces"), Course(code="BLG 220", title="Research Methods")
            session.add_all([period, first, second])
            session.flush()
            self.catalog_course_id = first.id
            known = self.section(first, period, "12345", "scheduled")
            unscheduled = self.section(first, period, "12346", "unpublished")
            external = self.section(second, period, "12347", "scheduled")
            session.add_all([known, unscheduled, external])
            session.flush()
            for ordinal, teacher, name in ((1, 2, "Ada Published"), (2, 3, "Grace Published")):
                session.add(TeachingAssignment(section_id=known.id, ordinal=ordinal, user_id=teacher,
                                               published_name=name))
            session.add(TeachingAssignment(section_id=external.id, ordinal=1, user_id=None,
                                           published_name="Public External Teacher"))
            session.add_all([Enrollment(section_id=known.id, user_id=1), Enrollment(section_id=external.id, user_id=4)])
            for ordinal, day, room_id, building, room_code in ((1, 1, 301, "BBB", "Z-17"),
                    (2, 3, None, "BBB", None), (3, 4, 302, "BBB", "302")):
                session.add(self.meeting(known.id, ordinal, day, room_id, building, room_code))
            session.add(self.meeting(external.id, 1, 2, None, "MDB", "204"))

        for actor in range(1, 6):
            AccountService(self.database).provision(actor, f"course-page-{actor}", "Course-fixture-only")
        self.configure_web()

    @staticmethod
    def section(course, period, crn, status):
        return CourseSection(course_id=course.id, academic_period_id=period.id, crn=crn,
            published_title=course.title, branch="BLG", academic_level="LS", instruction_method="In person",
            quota=40, source_kind="archive", source_url="https://example.invalid/course",
            publication_status=status, published_schedule={}, excluded_dates=["2030-01-14"])

    @staticmethod
    def meeting(section_id, ordinal, day, room_id, building, room_code):
        return CourseSession(section_id=section_id, ordinal=ordinal, resource_id=room_id,
            building_code=building, room_code=room_code, day=day, start_minutes=600, end_minutes=660,
            published_day={1: "Pazartesi", 2: "Salı", 3: "Çarşamba", 4: "Perşembe"}[day],
            published_start="10:00", published_end="10:59", published_building=building,
            published_room=room_code or "--")

    def page(self, actor, path):
        response = authorized_client(web_app.app, actor).get(path)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        return response.get_data(as_text=True)

    def test_catalogue_search_and_section_detail_exposes_only_public_metadata(self):
        self.assertEqual(web_app.app.test_client().get("/courses/").status_code, 302)
        search = self.page(1, "/courses/?q=12346")
        self.assertIn("BLG 210", search)
        self.assertNotIn("BLG 220", search)
        detail = self.page(1, f"/courses/{self.catalog_course_id}")
        for item in ("CRN 12345", "CRN 12346", "Ada Published", "Grace Published", "10:59",
                     "Classroom unspecified", "No teaching time was published", "Quota exceeds 20 configured seats"):
            self.assertIn(item, detail)
        self.assertNotIn("/courses/rooms/302", detail)
        self.assertNotIn("Student Noor", detail)

    def test_my_courses_show_personal_enrollments_and_shared_teaching_assignments(self):
        student = self.page(1, "/courses/mine?date=2030-01-07&user_id=4")
        self.assertIn("Weekly course schedule", student)
        self.assertIn("CRN 12345", student)
        self.assertNotIn("CRN 12347", student)
        external = self.page(4, "/courses/mine?date=2030-01-07")
        self.assertIn("MDB 204", external)
        self.assertIn("External classroom", external)
        self.assertNotIn("CRN 12345", external)
        for professor in (2, 3):
            teaching = self.page(professor, "/courses/mine?date=2030-01-07")
            self.assertIn("Weekly teaching schedule", teaching)
            self.assertIn("CRN 12345", teaching)
            self.assertIn("BBB Z-17", teaching)
        self.assertEqual(authorized_client(web_app.app, 5).get("/courses/mine").status_code, 403)

    def test_course_calendar_download_is_private_and_tracks_the_selected_week(self):
        with self.database.transaction() as session:
            external = session.scalar(select(CourseSection.id).where(CourseSection.crn == "12347"))
            session.add(TeachingAssignment(section_id=external, ordinal=2, user_id=1,
                                           published_name="Other role"))
            session.add(Enrollment(section_id=external, user_id=2))
        route = "/courses/mine/calendar.ics"
        self.assertEqual(web_app.app.test_client().get(route).status_code, 302)
        self.assertEqual(authorized_client(web_app.app, 5).get(route).status_code, 403)
        student = authorized_client(web_app.app, 1)
        path = route + "?date=2030-01-08&user_id=4"
        result = student.get(path)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.mimetype, "text/calendar")
        self.assertEqual(result.headers["Cache-Control"], "private, no-store")
        self.assertEqual(result.headers["Content-Disposition"],
                         'attachment; filename="campus-space-courses-2030-01-07.ics"')
        lines = result.get_data(as_text=True).split("\r\n")
        self.assertEqual(lines.count("BEGIN:VEVENT"), 3)
        self.assertEqual(lines.count("CLASS:PRIVATE"), 3)
        self.assertIn("DTSTART:20300107T070000Z", lines)
        self.assertIn("DTEND:20300107T080000Z", lines)
        self.assertEqual([line for line in lines if line.startswith("LOCATION:")], ["LOCATION:BBB Z-17"])
        for private in ("CRN 12347", "Ada Published", "Grace Published", "Other role", "Private maintenance"):
            self.assertNotIn(private, result.get_data(as_text=True))
        uids = [line for line in lines if line.startswith("UID:")]
        self.assertEqual(len(set(uids)), 3)
        repeat = student.get(path).get_data(as_text=True).split("\r\n")
        self.assertEqual([line for line in repeat if line.startswith("UID:")], uids)
        self.assertNotIn("20300114T070000Z", self.page(1, route + "?date=2030-01-14"))
        self.assertIn("LOCATION:MDB 204", self.page(4, path))
        self.assertNotIn("CRN 12347", self.page(2, path))
        self.assertIn("/courses/mine/calendar.ics?date=2030-01-08", self.page(1, "/courses/mine?date=2030-01-08"))
        self.assertNotIn("Download this week", self.page(1, "/courses/mine?date=2030-02-04"))
        self.assertEqual(student.get(route + "?date=2030-02-04").status_code, 404)
        self.assertEqual(student.get(route + "?date=invalid").status_code, 400)

    def test_course_calendar_keeps_unicode_and_escapes_text_before_folding(self):
        title = "Ç" * 50 + ", etüt; C:\\ders\r\nLOCATION:Unexpected"
        with self.database.transaction() as session:
            section = session.scalar(select(CourseSection).where(CourseSection.crn == "12345"))
            section.published_title = title
        data = authorized_client(web_app.app, 1).get("/courses/mine/calendar.ics?date=2030-01-07").data
        lines = data.split(b"\r\n")
        self.assertTrue(all(len(line) <= 75 for line in lines))
        unfolded = data.replace(b"\r\n ", b"").decode("utf-8")
        expected = "SUMMARY:BLG 210 · " + "Ç" * 50 + r"\, etüt\; C:\\ders\nLOCATION:Unexpected (CRN 12345)"
        self.assertIn(expected, unfolded.split("\r\n"))
        self.assertNotIn("LOCATION:Unexpected", unfolded.split("\r\n"))

    def test_room_week_combines_occupied_and_available_intervals_without_leaking_private_titles(self):
        classroom = "/courses/rooms/301?date=2030-01-07"
        week = self.page(1, classroom)
        for item in ("BBB Z-17", "Ada Published", "Grace Published", ">Occupied<", ">Available<", "15:00"):
            self.assertIn(item, week)
        self.assertNotIn("Private maintenance information", week)
        self.assertNotIn("CRN 12345", self.page(1, "/courses/rooms/301?date=2030-01-14"))
        directory = self.page(1, "/courses/rooms")
        self.assertNotIn("Restricted classroom", directory)
        self.assertEqual(authorized_client(web_app.app, 1).get("/courses/rooms/302").status_code, 403)
        self.assertEqual(authorized_client(web_app.app, 1).get("/rooms/availability/302").status_code, 403)
