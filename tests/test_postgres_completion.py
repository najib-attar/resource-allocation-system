"""Final hierarchy, subtype, retry and retained-result integrity regressions."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock
import re
import multiprocessing
import threading
import uuid

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from postgres_fixtures import PostgresTestCase, ROOT
from test_postgres_import import copy_inputs
from test_postgres_workflow import new_request
from web.allocation_workflow import execute_allocation
from web.engine_gateway import EngineGateway
from web.persistence.demo import demo_snapshot
from web.persistence.database import Database
from web.persistence.importer import ImportValidationError, import_csv, populate_empty_database
from web.persistence.models import AllocationRun, ApplicationState, ExamDetails, OrganizationUnit, RequestHistory, RequestParticipant, RequestSlot, ResourceRequest
from web.persistence.repository import PersistenceError, Repository, validate_unit_hierarchy


def retry_save_process(url, start, output, key):
    database = Database(url)
    try:
        output.put(("ready", None))
        if not start.wait(15):
            raise RuntimeError("No start signal")
        output.put(("saved", Repository(database).save_request(new_request(), submission_key=key)))
    finally:
        database.dispose()


class HierarchyValidationTests(TestCase):
    def test_long_forests_and_unknown_parents_are_validated_without_recursion(self):
        validate_unit_hierarchy({index: index + 1 if index < 10000 else None for index in range(10001)})
        with self.assertRaisesRegex(PersistenceError, "unknown parent"):
            validate_unit_hierarchy({"A": "Missing"})
        with self.assertRaisesRegex(PersistenceError, "cycle"):
            validate_unit_hierarchy({"A": "B", "B": "A"})


class HierarchyInitializationTests(PostgresTestCase):
    def test_multi_unit_cycle_is_rejected_without_partial_seed(self):
        snapshot, units = demo_snapshot(41)
        names = list(units)[:3]
        for index, name in enumerate(names):
            units[name]["parent"] = names[(index + 1) % len(names)]
        with self.assertRaisesRegex(ImportValidationError, "cycle"):
            populate_empty_database(self.database, snapshot, units)
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(OrganizationUnit)), 0)
            self.assertEqual(session.get(ApplicationState, 1).input_revision, 0)


class PostgresCompletionTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        with TemporaryDirectory() as directory:
            copy_inputs(Path(directory))
            import_csv(self.database, directory)
        self.repository = Repository(self.database)

    def test_corrupt_hierarchy_is_rejected_before_snapshot_or_engine_execution(self):
        with self.database.transaction() as session:
            units = list(session.scalars(select(OrganizationUnit).limit(2)))
            units[0].parent_id, units[1].parent_id = units[1].id, units[0].id
        with self.assertRaisesRegex(PersistenceError, "cycle"):
            self.repository.start_run()
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(AllocationRun)), 0)

    def test_deleting_required_occurrences_fails_at_commit(self):
        with self.assertRaises(IntegrityError):
            with self.database.transaction() as session:
                session.execute(delete(RequestSlot).where(RequestSlot.request_id == 1))
        self.assertTrue(self.repository.snapshot()["requests"][0]["slots"])

    def test_multiple_slots_on_nonrecurring_request_are_rejected(self):
        with self.assertRaises(IntegrityError):
            with self.database.transaction() as session:
                session.add(RequestSlot(request_id=1, ordinal=2, day=2, start_minutes=540, end_minutes=600))

    def test_exam_details_are_required_only_for_exams(self):
        exam_id = next(item["id"] for item in self.repository.snapshot()["requests"] if item["type"] == "Exam")
        with self.assertRaises(IntegrityError):
            with self.database.transaction() as session:
                session.execute(delete(ExamDetails).where(ExamDetails.request_id == exam_id))
        with self.assertRaises(IntegrityError):
            with self.database.transaction() as session:
                session.add(ExamDetails(request_id=1))

    def test_participants_cannot_be_attached_to_noncommittee_requests(self):
        with self.assertRaises(IntegrityError):
            with self.database.transaction() as session:
                session.add(RequestParticipant(request_id=1, user_id=2, ordinal=1, role="test"))

    def test_deferred_validation_allows_atomic_slot_replacement(self):
        with self.database.transaction() as session:
            session.execute(delete(RequestSlot).where(RequestSlot.request_id == 1))
            session.flush()
            session.add(RequestSlot(request_id=1, ordinal=1, day=5, start_minutes=540, end_minutes=600))
        self.assertEqual(self.repository.snapshot()["requests"][0]["slots"][0]["day"], 5)

    def test_atomic_subtype_transition_preserves_completeness(self):
        with self.database.transaction() as session:
            session.execute(update(ResourceRequest).where(ResourceRequest.id == 1).values(type="Exam"))
            session.add(ExamDetails(request_id=1, course_code="DEMO", can_split=False))
        self.assertEqual(self.repository.snapshot()["requests"][0]["exam"]["courseCode"], "DEMO")
        with self.database.transaction() as session:
            session.execute(update(ResourceRequest).where(ResourceRequest.id == 1).values(type="OneTime"))
            session.execute(delete(ExamDetails).where(ExamDetails.request_id == 1))
        self.assertNotIn("exam", self.repository.snapshot()["requests"][0])

    def test_all_migration_owned_subtype_triggers_are_installed(self):
        with self.database.transaction(read_only=True) as session:
            rows = list(session.execute(text("SELECT t.tgname, t.tgdeferrable, t.tginitdeferred FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid WHERE c.relnamespace=current_schema()::regnamespace AND NOT t.tgisinternal")))
        expected = {table + "_subtype_complete": (True, True) for table in
                    ("resource_request", "request_slot", "exam_details", "request_participant")}
        expected.update({table + "_shape_lock": (False, False) for table in ("request_slot", "exam_details", "request_participant")})
        expected.update({table + "_aggregate_complete": (True, True) for table in
                         ("appointment", "appointment_professor", "appointment_invitation", "appointment_commitment")})
        expected.update({table + "_shape_lock": (False, False) for table in
                         ("appointment_professor", "appointment_invitation", "appointment_commitment")})
        expected.update({table + "_complete": (True, True) for table in
                         ("student_room_request", "room_invitation", "room_reservation", "room_organizer_commitment")})
        expected.update({table + "_shape_lock": (False, False) for table in
                         ("room_invitation", "room_reservation", "room_organizer_commitment")})
        expected.update({name: (False, False) for name in
                         ("room_policy_faculty", "faculty_room_approver_faculty",
                          "appointment_room_person_overlap", "room_appointment_person_overlap")})
        expected.update({table + '_faculty': (False, False) for table in
                         ('equipment_type', 'equipment_custodian', 'borrow_request')})
        expected.update({table + '_shape': (True, True) for table in
                         ('borrow_request', 'borrow_item', 'equipment_reservation')})
        self.assertEqual({row[0]: (row[1], row[2]) for row in rows}, expected)

    def test_concurrent_child_deletions_cannot_leave_empty_recurring_request(self):
        item = next(item for item in self.repository.snapshot()["requests"] if item["type"] == "Recurring" and len(item["slots"]) == 2)
        for isolation in ("READ COMMITTED", "REPEATABLE READ"):
            barrier = threading.Barrier(2)
            def remove_slot(ordinal):
                try:
                    with self.database.engine.connect().execution_options(isolation_level=isolation) as connection:
                        with connection.begin():
                            connection.execute(select(ResourceRequest.id).where(ResourceRequest.id == item["id"]))
                            barrier.wait(timeout=10)
                            connection.execute(delete(RequestSlot).where(RequestSlot.request_id == item["id"], RequestSlot.ordinal == ordinal))
                    return True
                except DBAPIError:
                    return False
            with self.subTest(isolation=isolation), ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(remove_slot, (1, 2)))
                self.assertEqual(sum(outcomes), 1)
            with self.database.transaction() as session:
                existing = set(session.scalars(select(RequestSlot.ordinal).where(RequestSlot.request_id == item["id"])))
                for ordinal, slot in enumerate(item["slots"], 1):
                    if ordinal not in existing:
                        session.add(RequestSlot(request_id=item["id"], ordinal=ordinal, day=slot["day"],
                                                start_minutes=slot["startMinutes"], end_minutes=slot["endMinutes"]))

    def test_saved_retry_reuses_id_history_and_revision(self):
        key = uuid.uuid4().hex
        first = self.repository.save_request(new_request(), submission_key=key)
        with self.database.transaction(read_only=True) as session:
            revision = session.get(ApplicationState, 1).input_revision
        before = self.repository.snapshot()
        self.assertEqual(self.repository.save_request(new_request(), submission_key=key), first)
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(RequestHistory).where(RequestHistory.request_id == first)), 1)
            self.assertEqual(session.get(ApplicationState, 1).input_revision, revision)
        after = self.repository.snapshot()
        before.pop("runId"); after.pop("runId")
        self.assertEqual(after, before)

    def test_concurrent_identical_retries_create_only_one_request(self):
        key = uuid.uuid4().hex
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(lambda _: self.repository.save_request(new_request(), submission_key=key), range(2)))
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(len(self.repository.snapshot()["requests"]), 15)

    def test_identical_retries_across_processes_create_only_one_request(self):
        context = multiprocessing.get_context("spawn")
        start, output = context.Event(), context.Queue()
        key = uuid.uuid4().hex
        processes = [context.Process(target=retry_save_process, args=(self.url, start, output, key)) for _ in range(2)]
        try:
            for process in processes:
                process.start()
            self.assertEqual([output.get(timeout=20)[0] for _ in processes], ["ready", "ready"])
            start.set()
            results = [output.get(timeout=20) for _ in processes]
            self.assertEqual(results[0], results[1])
            self.assertEqual(results[0][0], "saved")
            for process in processes:
                process.join(20)
                self.assertEqual(process.exitcode, 0)
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                process.join(5)
            output.close()

    def test_reused_key_with_changed_content_is_rejected(self):
        key = uuid.uuid4().hex
        self.repository.save_request(new_request(), submission_key=key)
        with self.assertRaisesRegex(PersistenceError, "different"):
            self.repository.save_request(new_request("Changed"), submission_key=key)
        self.assertEqual(len(self.repository.snapshot()["requests"]), 15)

    def test_failed_save_does_not_consume_retry_key(self):
        key = uuid.uuid4().hex
        with mock.patch("web.persistence.repository.insert_request", side_effect=PersistenceError("test rollback")):
            with self.assertRaises(PersistenceError):
                self.repository.save_request(new_request(), submission_key=key)
        self.assertGreater(self.repository.save_request(new_request(), submission_key=key), 45)

    def test_invalid_submission_key_is_rejected_without_saving(self):
        for key in ("bad", "A" * 32, 123):
            with self.subTest(key=key), self.assertRaisesRegex(PersistenceError, "Invalid submission key"):
                self.repository.save_request(new_request(), submission_key=key)
        self.assertEqual(len(self.repository.snapshot()["requests"]), 14)

    def test_web_form_retry_preserves_one_saved_request(self):
        client = self.configure_web()
        page = client.get("/add-request").get_data(as_text=True)
        key = re.search(r'name="submissionKey" value="([0-9a-f]{32})"', page).group(1)
        form = {"requestType": "OneTime", "userId": "1", "spaceId": "101", "participantCount": "5",
                "day": "5", "startTime": "15:00", "endTime": "16:00", "title": "Retry",
                "purpose": "Meeting", "submitAction": "save", "submissionKey": key}
        first = client.post("/add-request", data=form)
        second = client.post("/add-request", data=form)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.location, first.location)
        self.assertEqual(len(self.repository.snapshot()["requests"]), 15)
        form["title"] = "Different"
        self.assertEqual(client.post("/add-request", data=form).status_code, 409)

    def test_failed_run_retry_does_not_save_twice(self):
        client = self.configure_web()
        form = {"requestType": "OneTime", "userId": "1", "spaceId": "101", "participantCount": "5",
                "day": "5", "startTime": "15:00", "endTime": "16:00", "title": "Retry run",
                "purpose": "Meeting", "submitAction": "save_run", "submissionKey": uuid.uuid4().hex}
        with mock.patch("web.app.run_backend_allocation", return_value={"status": "error", "message": "Engine timeout"}):
            self.assertEqual(client.post("/add-request", data=form).status_code, 302)
        response = client.post("/add-request", data=form)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(self.repository.snapshot()["requests"]), 15)
        self.assertIsNotNone(self.repository.read_view()[2])

    def test_abandoned_run_and_new_publication_do_not_delete_history(self):
        abandoned_id, _ = self.repository.start_run()
        execute_allocation(self.repository, EngineGateway(ROOT))
        first_id = self.repository.read_view()[2]
        execute_allocation(self.repository, EngineGateway(ROOT))
        self.repository.fail_run(first_id, "late retry must not change success")
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.get(AllocationRun, abandoned_id).status, "running")
            self.assertEqual(session.get(AllocationRun, first_id).status, "success")
            self.assertEqual(session.scalar(select(func.count()).select_from(AllocationRun)), 3)
