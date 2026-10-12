from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest import mock
import multiprocessing
import threading
import time

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from engine_json_fixtures import fake_result
from postgres_fixtures import PostgresTestCase, ROOT
from test_postgres_import import copy_inputs
from web.allocation_workflow import execute_allocation
from web.engine_gateway import EngineGateway, EngineIntegrationError
from web.persistence.database import Database, DatabaseBusy
from web.persistence.importer import import_csv
from web.persistence.models import Allocation, AllocationRun, ApplicationState, RequestDecision
from web.persistence.repository import Repository, StaleRun, state_row


def new_request(title="Saved", committee=True):
    item = {"type": "CommitteeMeeting" if committee else "OneTime", "requesterId": 2, "spaceId": 301,
            "participantCount": 5, "title": title, "purpose": "Meeting",
            "slots": [{"day": 5, "startMinutes": 900, "endMinutes": 960}]}
    if committee:
        item["participants"] = [{"userId": 2, "role": title}]
    return item


def concurrent_save_process(url, start, output, title):
    database = Database(url)
    try:
        output.put(("ready", None))
        if not start.wait(10):
            raise RuntimeError("No start signal")
        output.put(("saved", Repository(database).save_request(new_request(title))))
    finally:
        database.dispose()


def hold_database_lock_process(url, ready):
    database = Database(url)
    with database.transaction() as session:
        state_row(session, lock=True)
        ready.set()
        time.sleep(60)


class PostgresWorkflowTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.data = Path(temporary.name)
        copy_inputs(self.data)
        import_csv(self.database, self.data)
        self.repository = Repository(self.database)

    def publish_fake(self, marker="old"):
        run_id, snapshot = self.repository.start_run()
        result = fake_result(snapshot, marker)
        self.repository.publish_run(run_id, result, {})
        return run_id, result

    def test_real_engine_all_five_strategies_persist_and_round_trip_exact_json(self):
        for strategy in ("greedy", "priority", "multi_room_exam_greedy", "multi_room_exam_best_fit", "shared_room_exam_best_fit"):
            with self.subTest(strategy=strategy):
                self.repository.set_strategy(strategy)
                result = execute_allocation(self.repository, EngineGateway(ROOT))
                live, document, run_id = self.repository.read_view()
                self.assertEqual(document["result"], result)
                self.assertEqual(document["snapshot"]["strategy"], strategy)
                self.assertTrue(document["build"]["binary_sha256"])
                with self.database.transaction(read_only=True) as session:
                    self.assertEqual(session.scalar(select(func.count()).select_from(RequestDecision).where(RequestDecision.run_id == run_id)), 14)

    def test_two_threads_save_unique_ids_and_correct_participants(self):
        start = threading.Barrier(2)
        def save(title):
            start.wait(5)
            return self.repository.save_request(new_request(title))
        with ThreadPoolExecutor(2) as pool:
            ids = list(pool.map(save, ["Thread A", "Thread B"]))
        self.assertEqual(len(set(ids)), 2)
        snapshot = self.repository.snapshot()
        for item in snapshot["requests"][-2:]:
            self.assertEqual(item["participants"], [{"userId": 2, "role": item["title"]}])

    def test_two_processes_save_unique_ids_and_correct_participants(self):
        context = multiprocessing.get_context("spawn")
        start, output = context.Event(), context.Queue()
        processes = [context.Process(target=concurrent_save_process, args=(self.url, start, output, title))
                     for title in ("Process A", "Process B")]
        try:
            for process in processes:
                process.start()
            self.assertEqual([output.get(timeout=20)[0] for _ in processes], ["ready", "ready"])
            start.set()
            responses = [output.get(timeout=20) for _ in processes]
            self.assertTrue(all(kind == "saved" for kind, _ in responses))
            self.assertEqual(len({value for _, value in responses}), 2)
            for process in processes:
                process.join(10)
                self.assertEqual(process.exitcode, 0)
            for item in self.repository.snapshot()["requests"][-2:]:
                self.assertEqual(item["participants"][0]["role"], item["title"])
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                process.join(5)
            output.close()

    def test_changed_inputs_reject_publication_and_preserve_saved_request(self):
        previous, _ = self.publish_fake()
        run_id, snapshot = self.repository.start_run()
        saved = self.repository.save_request(new_request())
        with self.assertRaisesRegex(StaleRun, "Inputs changed"):
            self.repository.publish_run(run_id, fake_result(snapshot), {})
        live, document, active = self.repository.read_view()
        self.assertEqual(active, previous)
        self.assertIn(saved, [item["id"] for item in live["requests"]])
        self.assertNotIn(saved, [item["requestId"] for item in document["result"]["requestResults"]])

    def test_older_run_cannot_replace_a_newer_completed_run(self):
        old, old_snapshot = self.repository.start_run()
        newer, snapshot = self.repository.start_run()
        self.repository.publish_run(newer, fake_result(snapshot, "newer"), {})
        with self.assertRaisesRegex(StaleRun, "newer allocation run"):
            self.repository.publish_run(old, fake_result(old_snapshot, "older"), {})
        self.assertEqual(self.repository.read_view()[2], newer)

    def test_backend_error_and_timeout_preserve_last_successful_results(self):
        previous, _ = self.publish_fake()
        saved = self.repository.save_request(new_request())
        for message in ("Backend exit 9", "Backend timed out"):
            with self.subTest(message=message):
                gateway = mock.Mock()
                gateway.execute.side_effect = EngineIntegrationError(message)
                with self.assertRaisesRegex(EngineIntegrationError, message):
                    execute_allocation(self.repository, gateway)
                self.assertEqual(self.repository.read_view()[2], previous)
        self.assertIn(saved, [item["id"] for item in self.repository.snapshot()["requests"]])

    def test_partial_database_publication_rolls_back_all_output_records(self):
        previous, _ = self.publish_fake()
        run_id, snapshot = self.repository.start_run()
        result, metadata = EngineGateway(ROOT).execute(snapshot)
        committee = next(item for item in result["allocations"] if item["requiredParticipantIds"])
        committee["requiredParticipantIds"] = [999999]
        with self.assertRaises(IntegrityError):
            self.repository.publish_run(run_id, result, metadata)
        self.assertEqual(self.repository.read_view()[2], previous)
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(RequestDecision).where(RequestDecision.run_id == run_id)), 0)
            self.assertEqual(session.scalar(select(func.count()).select_from(Allocation).where(Allocation.run_id == run_id)), 0)

    def test_saved_view_remains_coherent_after_later_publication(self):
        old, _ = self.publish_fake("old")
        snapshot, pinned, _ = self.repository.read_view()
        self.publish_fake("new")
        self.assertTrue(all(item["rejectionReason"] == "old" for item in pinned["result"]["requestResults"]))
        self.assertTrue(all(item["rejectionReason"] == "new" for item in self.repository.read_view()[1]["result"]["requestResults"]))
        self.assertEqual(len(snapshot["requests"]), 14)

    def test_lock_timeout_leaves_inputs_unchanged(self):
        short_database = Database(self.url, lock_timeout=.1)
        self.addCleanup(short_database.dispose)
        with self.database.transaction() as session:
            state_row(session, lock=True)
            with ThreadPoolExecutor(1) as pool:
                future = pool.submit(Repository(short_database).save_request, new_request())
                with self.assertRaisesRegex(DatabaseBusy, "busy"):
                    future.result(5)
        self.assertEqual(len(self.repository.snapshot()["requests"]), 14)

    def test_terminated_worker_releases_postgresql_lock(self):
        context = multiprocessing.get_context("spawn")
        ready = context.Event()
        process = context.Process(target=hold_database_lock_process, args=(self.url, ready))
        try:
            process.start()
            self.assertTrue(ready.wait(20))
            process.terminate()
            process.join(5)
            self.assertGreater(self.repository.save_request(new_request()), 45)
        finally:
            if process.is_alive():
                process.terminate()
            process.join(5)

    def test_engine_execution_does_not_hold_global_database_lock(self):
        previous, _ = self.publish_fake()
        started, release = threading.Event(), threading.Event()
        snapshots = []
        def execute(snapshot):
            snapshots.append(deepcopy(snapshot))
            started.set()
            if not release.wait(10):
                raise RuntimeError("No release signal")
            return fake_result(snapshot), {}
        gateway = mock.Mock(execute=execute)
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(execute_allocation, self.repository, gateway)
            self.assertTrue(started.wait(5))
            self.repository.set_strategy("priority")
            self.assertEqual(self.repository.snapshot()["strategy"], "priority")
            release.set()
            with self.assertRaises(StaleRun):
                future.result(10)
        self.assertNotEqual(snapshots[0]["strategy"], "priority")
        self.assertEqual(self.repository.read_view()[2], previous)

    def test_failed_run_record_has_no_active_outputs(self):
        gateway = mock.Mock()
        gateway.execute.side_effect = EngineIntegrationError("Engine failed")
        with self.assertRaises(EngineIntegrationError):
            execute_allocation(self.repository, gateway)
        self.assertIsNone(self.repository.read_view()[1])
        with self.database.transaction(read_only=True) as session:
            run = session.scalar(select(AllocationRun))
            self.assertEqual(run.status, "failed")
            self.assertIn("Engine failed", run.error)
