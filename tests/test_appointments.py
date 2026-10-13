"""Real-engine, real-PostgreSQL acceptance for the complete appointment lifecycle."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import multiprocessing
import secrets
import re
from unittest import mock
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from auth_fixtures import authorized_client
from postgres_fixtures import PostgresTestCase, ROOT
from web import app as web_app
from web.account_service import AccountService
from web.appointment_service import AppointmentError, AppointmentService
from web.calendar_service import CalendarError, expand_weekly, local_instant
from web.engine_gateway import EngineGateway, EngineIntegrationError, validate_appointment_result
from web.persistence.database import Database
from web.persistence.importer import populate_empty_database
from web.persistence.models import (Appointment, AppointmentCommitment, BusySlot, OrganizationUnit, ProfessorAvailability, User)
from runtime_file_guard import forbid_runtime_files


START = datetime(2030, 1, 7, 7, tzinfo=timezone.utc)  # Explicit fictional Monday 10:00 Istanbul.


def confirm_process(url, appointment_id, queue):
    database = Database(url)
    try:
        AppointmentService(database, EngineGateway(ROOT)).decide(appointment_id, 2, 1, True)
        queue.put("confirmed")
    except AppointmentError:
        queue.put("conflict")
    finally:
        database.dispose()


def seed_appointments(database):
    people = [(1, "Student", "Student Mira"), (2, "Instructor", "Professor Ada"),
              (3, "Instructor", "Professor Grace"), (4, "Student", "Student Noor"),
              (5, "Student", "Student Kai"), (6, "Student", "Student Lia")]
    snapshot = {"protocolVersion": 1, "runId": "appointment-fixture", "strategy": "greedy", "users": [],
                "spaces": [{"id": 301, "type": "MeetingRoom", "name": "M301", "capacity": 20, "building": "Main", "available": True,
                            "features": {"projector": False, "whiteboard": False, "computers": False}}], "requests": [], "busySlots": []}
    for uid, role, name in people:
        snapshot["users"].append({"id": uid, "role": role, "name": name, "assignedRoles": [], "primaryUnit": "",
                                  "status": "active", "email": "", "yearLevel": 0,
                                  **{key: "" for key in ("studentNo", "program", "title", "officeRoom", "assistantType", "jobTitle", "adminLevel")}})
    populate_empty_database(database, snapshot)
    with database.transaction() as session:
        faculty = OrganizationUnit(name="Fictional Engineering Faculty", unit_type="Faculty")
        session.add(faculty)
        session.flush()
        department = OrganizationUnit(name="Fictional Computing Department", unit_type="Department", parent_id=faculty.id)
        session.add(department)
        session.flush()
        for uid in (2, 3):
            session.get(User, uid).primary_unit_id = department.id
            session.add(ProfessorAvailability(user_id=uid, day=1, start_minutes=540, end_minutes=1020,
                        valid_from=date(2030, 1, 1), valid_until=date(2030, 1, 31), timezone="Europe/Istanbul", excluded_dates=[]))
        return faculty.id


class AppointmentFixture(PostgresTestCase):
    def setUp(self):
        super().setUp()
        self.faculty = seed_appointments(self.database)
        self.service = AppointmentService(self.database, EngineGateway(ROOT))

    def submit(self, organizer=1, professors=(2,), invitees=(), start=START):
        return self.service.submit(organizer, list(professors), list(invitees), "Fictional project review", 60, start, self.faculty)


class AppointmentWorkflowTests(AppointmentFixture):
    def test_all_four_participant_configurations(self):
        for professors, invitees in [((2,), ()), ((2, 3), ()), ((2,), (4, 5)), ((2, 3), (4, 5))]:
            with self.subTest(professors=professors, invitees=invitees):
                pid = self.submit(professors=professors, invitees=invitees)
                for professor in professors:
                    self.service.decide(pid, professor, 1, True)
                self.assertEqual(self.service.detail(pid, 1)["status"], "Confirmed")
                with self.database.transaction(read_only=True) as session:
                    commitments = list(session.scalars(select(AppointmentCommitment).where(AppointmentCommitment.appointment_id == pid)))
                    self.assertEqual({row.user_id for row in commitments}, {1, *professors})
                self.service.cancel(pid, 1, 1)

    def test_pending_reserves_nothing_and_unanimous_approval_is_required(self):
        pid = self.submit(professors=(2, 3))
        self.service.decide(pid, 2, 1, True)
        self.assertEqual(self.service.detail(pid, 1)["status"], "Pending Approval")
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(AppointmentCommitment)), 0)
        self.service.decide(pid, 3, 1, True)
        self.assertEqual(self.service.detail(pid, 1)["status"], "Confirmed")

    def test_professor_rejection_prevents_confirmation(self):
        pid = self.submit(professors=(2, 3))
        self.service.decide(pid, 2, 1, False)
        with self.assertRaises(AppointmentError):
            self.service.decide(pid, 3, 1, True)
        self.assertEqual(self.service.detail(pid, 1)["status"], "Declined")
        expired = self.submit(start=START + timedelta(hours=1))
        with self.database.transaction() as session:
            row = session.get(Appointment, expired)
            row.start_at = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(days=1)
            row.end_at = row.start_at + timedelta(hours=1)
        self.service.decide(expired, 2, 1, False)
        self.assertEqual(self.service.detail(expired, 1)["status"], "Declined")

    def test_invitation_decline_and_unanswered_invites_do_not_block(self):
        pid = self.submit(invitees=(4, 5))
        self.service.decline_invitation(pid, 4)
        self.service.decide(pid, 2, 1, True)
        item = self.service.detail(pid, 2)
        self.assertEqual(item["status"], "Confirmed")
        self.assertEqual([row["status"] for row in item["invitations"]], ["Declined", "Invited"])
        with self.assertRaises(PermissionError):
            self.service.decline_invitation(pid, 1)

    def test_time_change_clears_every_professor_approval(self):
        pid = self.submit(professors=(2, 3))
        self.service.decide(pid, 2, 1, True)
        self.service.reschedule(pid, 1, 1, START + timedelta(hours=1))
        item = self.service.detail(pid, 1)
        self.assertEqual(item["revision"], 2)
        self.assertEqual([row["decision"] for row in item["professors"]], ["Pending", "Pending"])
        with self.assertRaises(AppointmentError):
            self.service.decide(pid, 3, 1, True)
        self.service.decide(pid, 2, 2, True)
        self.service.decide(pid, 3, 2, True)
        self.assertEqual(self.service.detail(pid, 1)["status"], "Confirmed")

    def test_cancellation_releases_time_and_records_history(self):
        pid = self.submit()
        self.service.decide(pid, 2, 1, True)
        with self.assertRaises(AppointmentError):
            self.submit(organizer=4)
        self.service.cancel(pid, 2, 1)
        second = self.submit(organizer=4)
        self.service.decide(second, 2, 1, True)
        self.assertEqual(self.service.detail(second, 4)["status"], "Confirmed")
        self.assertIn("released", self.service.detail(pid, 1)["history"][-1])

    def test_organizer_and_professor_blocks_are_mandatory_optional_students_are_not(self):
        self.service.block(4, START, START + timedelta(hours=1))
        pid = self.submit(invitees=(4,))
        self.service.decide(pid, 2, 1, True)
        self.service.cancel(pid, 1, 1)
        self.service.block(1, START, START + timedelta(hours=1))
        with self.assertRaisesRegex(AppointmentError, "organizing student"):
            self.submit()
        with self.assertRaises(AppointmentError):
            self.submit(start=START + timedelta(hours=8))

    def test_blocks_added_while_pending_are_rechecked_before_confirmation(self):
        pid = self.submit()
        self.service.block(2, START, START + timedelta(hours=1))
        with self.assertRaises(AppointmentError):
            self.service.decide(pid, 2, 1, True)
        self.assertEqual(self.service.detail(pid, 1)["status"], "Pending Approval")

    def test_recommendations_are_feasible_and_rank_invitee_then_preference_then_time(self):
        self.service.block(4, START, START + timedelta(hours=1))
        result, _ = self.service.evaluate(1, [2, 3], [4], 60, START, START + timedelta(hours=4), preferred=START)
        first = result["recommendations"][0]
        self.assertEqual(first["start"], int((START + timedelta(hours=1)).timestamp()))
        for row in result["recommendations"]:
            a, b = datetime.fromtimestamp(row["start"], timezone.utc), datetime.fromtimestamp(row["end"], timezone.utc)
            check, _ = self.service.evaluate(1, [2, 3], [4], 60, a, b, (a, b))
            self.assertTrue(check["feasible"])

    def test_legacy_calendar_must_be_explicit_and_only_applies_in_its_period(self):
        with self.database.transaction() as session:
            busy = BusySlot(user_id=1, source_order=1, day=1, start_minutes=600, end_minutes=660, reason="Legacy class")
            session.add(busy)
            session.flush()
            busy_id = busy.id
        with self.assertRaisesRegex(AppointmentError, "undated university"):
            self.submit()
        self.service.bind_legacy("Explicit fictional January 2030", date(2030, 1, 1), date(2030, 1, 31), busy_id=busy_id,
                                 week_start=date(2030, 1, 7), exclusions=["2030-01-07"])
        self.submit()  # Specific exception excludes the bounded planning week commitment.
        self.submit(start=START + timedelta(days=7))
        with self.database.transaction() as session:
            busy = BusySlot(user_id=1, source_order=2, day=3, start_minutes=600, end_minutes=660, reason="First partial semester week")
            session.add(busy)
            session.flush()
            busy_id = busy.id
            session.add(ProfessorAvailability(user_id=2, day=3, start_minutes=540, end_minutes=1020,
                valid_from=date(2030, 1, 1), valid_until=date(2030, 1, 31), timezone="Europe/Istanbul", excluded_dates=[]))
        self.service.bind_legacy("Fictional semester starting Tuesday", date(2030, 1, 8), date(2030, 1, 31),
                                 busy_id=busy_id, week_start=date(2030, 1, 7))
        with self.assertRaisesRegex(AppointmentError, "organizing student"):
            self.submit(start=START + timedelta(days=2))
        self.submit(start=START + timedelta(days=9))

    def test_faculty_roles_and_private_appointment_ownership_are_enforced(self):
        self.assertEqual(len(self.service.directory()["professors"]), 2)
        with self.assertRaises(AppointmentError):
            self.service.submit(1, [2], [], "Purpose", 60, START, 999)
        with self.assertRaises(AppointmentError):
            self.service.submit(2, [3], [], "Purpose", 60, START)
        pid = self.submit(invitees=(4,))
        for action in [lambda: self.service.detail(pid, 6), lambda: self.service.decide(pid, 4, 1, True),
                       lambda: self.service.cancel(pid, 4, 1), lambda: self.service.reschedule(pid, 2, 1, START + timedelta(hours=1))]:
            with self.assertRaises(PermissionError):
                action()

    def test_confirmation_is_safe_across_two_worker_processes(self):
        ids = [self.submit(organizer=actor) for actor in (1, 4)]
        context = multiprocessing.get_context("spawn")
        queue = context.Queue()
        workers = [context.Process(target=confirm_process, args=(self.url, pid, queue)) for pid in ids]
        try:
            for worker in workers:
                worker.start()
            results = [queue.get(timeout=40) for _ in workers]
            for worker in workers:
                worker.join(10)
                self.assertEqual(worker.exitcode, 0)
            self.assertEqual(sorted(results), ["confirmed", "conflict"])
            with self.database.transaction(read_only=True) as session:
                self.assertEqual(session.scalar(select(func.count()).select_from(AppointmentCommitment)), 2)
        finally:
            for worker in workers:
                if worker.is_alive():
                    worker.terminate()
                worker.join(5)
            queue.close()

    def test_failed_engine_does_not_save_a_partial_appointment(self):
        with mock.patch.object(self.service.gateway, "execute_appointment", side_effect=EngineIntegrationError("timeout")):
            with self.assertRaises(EngineIntegrationError):
                self.submit()
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Appointment)), 0)

    def test_confirmed_commitments_cannot_be_invalidated_by_new_blocks_or_removed_hours(self):
        pid = self.submit()
        self.service.decide(pid, 2, 1, True)
        with self.assertRaises(CalendarError):
            self.service.block(2, START, START + timedelta(hours=1))
        hours = self.service.availability_for(2)["hours"][0]["id"]
        with self.assertRaises(AppointmentError):
            self.service.remove_hours(2, hours)

    def test_database_rejects_incomplete_confirmation_and_pending_reservations(self):
        pid = self.submit()
        with self.assertRaises(IntegrityError):
            with self.database.transaction() as session:
                session.get(Appointment, pid).status = "Confirmed"
        with self.assertRaises(IntegrityError):
            with self.database.transaction() as session:
                session.add(AppointmentCommitment(appointment_id=pid, user_id=1, start_at=START, end_at=START + timedelta(hours=1)))
        self.assertEqual(self.service.detail(pid, 1)["status"], "Pending Approval")

    def test_old_availability_snapshot_cannot_confirm_after_calendar_change(self):
        pid = self.submit()
        execute = self.service.gateway.execute_appointment
        def changed(snapshot):
            result = execute(snapshot)
            self.service.block(2, START, START + timedelta(hours=1))
            return result
        with mock.patch.object(self.service.gateway, "execute_appointment", side_effect=changed):
            with self.assertRaisesRegex(AppointmentError, "changed during evaluation"):
                self.service.decide(pid, 2, 1, True)
        self.assertEqual(self.service.detail(pid, 1)["professors"][0]["decision"], "Pending")

    def test_dated_university_publication_cannot_conflict_with_confirmed_appointment(self):
        from web.persistence.repository import Repository
        from web.allocation_workflow import execute_allocation
        repository = Repository(self.database)
        request_id = repository.save_request({"type": "OneTime", "requesterId": 2, "spaceId": 301,
            "participantCount": 2, "title": "Fictional Monday commitment", "purpose": "Meeting",
            "slots": [{"day": 1, "startMinutes": 600, "endMinutes": 660}]})
        self.service.bind_legacy("Fictional January 2030", date(2030, 1, 1), date(2030, 1, 31), request_id=request_id)
        pid = self.submit()
        self.service.decide(pid, 2, 1, True)
        with self.assertRaisesRegex(CalendarError, "conflicts with a confirmed"):
            execute_allocation(repository, EngineGateway(ROOT))
        self.assertIsNone(repository.read_view()[2])
        self.assertEqual(self.service.detail(pid, 1)["status"], "Confirmed")


class CalendarRepresentationTests(PostgresTestCase):
    def test_istanbul_configuration_and_midnight_half_open_intervals(self):
        self.assertEqual(local_instant("2030-01-07T10:00"), START)
        values = expand_weekly(1, 1380, 1440, date(2030, 1, 7), date(2030, 1, 7), "Europe/Istanbul",
                              START, START + timedelta(days=1))
        self.assertEqual(values[0][1].astimezone(ZoneInfo("Europe/Istanbul")).date(), date(2030, 1, 8))

    def test_nonexistent_and_ambiguous_local_times_are_not_guessed(self):
        zone = ZoneInfo("America/New_York")
        for value in ("2030-03-10T02:30", "2030-11-03T01:30", "bad", "2030-01-01T10:00+03:00", "9999-12-31T10:00"):
            with self.assertRaises(CalendarError):
                local_instant(value, zone)


class AppointmentWebTests(AppointmentFixture):
    def setUp(self):
        super().setUp()
        self.client = self.configure_web()
        self.accounts = AccountService(self.database)
        for uid in (2, 3, 4, 6):
            self.accounts.provision(uid, f"fixture-{uid}", secrets.token_urlsafe(24))

    def test_every_new_view_and_submission_works_without_runtime_csv(self):
        with forbid_runtime_files():
            for route in ("/appointments/", "/appointments/new", "/appointments/calendar", "/appointments/calendar-setup"):
                self.assertEqual(self.client.get(route).status_code, 200)
            response = self.client.post("/appointments/new", data={"facultyId": self.faculty, "professorIds": [2, 3],
                "invitedIds": [4], "duration": 60, "purpose": "Web appointment", "start": "2030-01-07T10:00"})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(self.client.get(response.location).status_code, 200)
            for uid in (2, 3):
                professor = authorized_client(web_app.app, uid)
                self.assertEqual(professor.get("/appointments/availability").status_code, 200)
                self.assertEqual(professor.post(response.location + "/decision", data={"revision": 1, "decision": "approve"}).status_code, 302)
            self.assertIn(b"Web appointment", self.client.get("/appointments/calendar?from=2030-01-07").data)

    def test_login_csrf_revocation_and_schedule_privacy(self):
        anonymous = web_app.app.test_client()
        self.assertEqual(anonymous.get("/appointments/").status_code, 302)
        self.assertEqual(anonymous.get("/login").status_code, 200)
        self.assertEqual(anonymous.post("/login", data={"username": "wrong", "password": "wrong"}).status_code, 400)
        invited = authorized_client(web_app.app, 4)
        self.assertEqual(invited.get("/schedules?type=user&id=2").status_code, 403)
        self.assertEqual(invited.get("/raw-data").status_code, 403)
        self.assertEqual(invited.client.post("/appointments/calendar", data={"action": "block"}).status_code, 400)
        pid = self.submit()
        outsider = authorized_client(web_app.app, 6)
        self.assertEqual(outsider.get(f"/appointments/{pid}").status_code, 403)
        self.accounts.revoke(4)
        self.assertEqual(invited.get("/appointments/").status_code, 302)

    def test_password_login_logout_and_cookie_security_roundtrip(self):
        password = secrets.token_urlsafe(24)
        self.accounts.provision(4, "fixture-4", password, reset=True)
        client = web_app.app.test_client()
        response = client.get("/login")
        token = re.search(r'name="csrf_token" value="([^"]+)"', response.get_data(as_text=True)).group(1)
        response = client.post("/login", data={"username": "fixture-4", "password": password, "csrf_token": token})
        self.assertEqual(response.status_code, 302)
        self.assertIn("HttpOnly", response.headers["Set-Cookie"])
        self.assertIn("SameSite=Lax", response.headers["Set-Cookie"])
        self.assertEqual(client.get("/appointments/").status_code, 200)
        with client.session_transaction() as session:
            self.assertEqual(session["user_id"], 4)
            token = session["csrf"]
        self.assertEqual(client.post("/logout", data={"csrf_token": token}).status_code, 302)
        self.assertEqual(client.get("/appointments/").status_code, 302)

    def test_time_recommendation_endpoint_and_invalid_selection_explanations(self):
        form = {"facultyId": self.faculty, "professorIds": [2, 3], "duration": 60,
                "fromDate": "2030-01-07", "untilDate": "2030-01-07", "preferredStart": "2030-01-07T10:00"}
        response = self.client.post("/appointments/times", data=form)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["items"][0]["localStart"], "2030-01-07T10:00")
        response = self.client.post("/appointments/new", data={"facultyId": self.faculty, "professorIds": [2],
            "duration": 60, "purpose": "Invalid time", "start": "2030-01-07T22:00"})
        self.assertEqual(response.status_code, 409)
        self.assertIn(b"published appointment hours", response.data)
        form["untilDate"] = "9999-12-31"
        self.assertEqual(self.client.post("/appointments/times", data=form).status_code, 409)

    def test_invitation_reschedule_approval_and_cancel_routes_preserve_revision_rules(self):
        pid = self.submit(professors=(2, 3), invitees=(4,))
        path = f"/appointments/{pid}"
        invited = authorized_client(web_app.app, 4)
        self.assertEqual(invited.post(path + "/decline-invitation").status_code, 302)
        self.assertEqual(invited.post(path + "/cancel", data={"revision": 1}).status_code, 403)
        self.assertEqual(self.client.post(path + "/reschedule", data={"revision": 1, "start": "2030-01-07T11:00"}).status_code, 302)
        for uid in (2, 3):
            professor = authorized_client(web_app.app, uid)
            self.assertEqual(professor.post(path + "/decision", data={"revision": 1, "decision": "approve"}).status_code, 409)
            self.assertEqual(professor.post(path + "/decision", data={"revision": 2, "decision": "approve"}).status_code, 302)
        self.assertEqual(self.service.detail(pid, 1)["status"], "Confirmed")
        self.assertEqual(professor.post(path + "/cancel", data={"revision": 2}).status_code, 302)
        self.assertEqual(self.service.detail(pid, 1)["status"], "Cancelled")
