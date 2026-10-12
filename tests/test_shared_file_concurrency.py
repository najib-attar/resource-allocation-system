"""Concurrency regressions migrated to PostgreSQL, plus retained offline CSV QA."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main, mock
from urllib.parse import parse_qs, urlparse
import csv
import json
import multiprocessing
import os
import subprocess
import threading
import time

from web import app as web_app
from web.backend_executable import resolve_backend_executable
from web.database_result_adapter import DatabaseResultAdapter
from web.persistence.importer import import_csv
from web.persistence.repository import Repository, state_row
from web.result_table_schema import OUTPUT_HEADERS
from legacy_shared_file_state import SharedFileState, SharedStateBusy, atomic_write
from engine_json_fixtures import fake_result
from legacy_csv_fixtures import create_legacy_workspace, validate_legacy_outputs
from postgres_fixtures import PostgresTestCase, ROOT


def write_csv(path, headers, rows):
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def read_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def form(title, action="save"):
    return {"requestType": "CommitteeMeeting", "userId": "2", "spaceId": "301",
            "participantCount": "5", "day": "1", "startTime": "10:00", "endTime": "11:00",
            "title": title, "purpose": "Meeting", "requiredFeature": "None",
            "requiredBuilding": "Main", "submitAction": action,
            "requiredParticipantIds": ["2"], "participantRole_2": title}


def create_inputs(data):
    write_csv(data / "users.csv", ["userId", "name", "role"],
              [{"userId": "2", "name": "Professor Ada", "role": "Instructor"}])
    write_csv(data / "spaces.csv", ["spaceId", "type", "name", "capacity", "building"],
              [{"spaceId": "301", "type": "MeetingRoom", "name": "M301", "capacity": "20", "building": "Main"}])
    write_csv(data / "requests.csv", web_app.REQUEST_HEADERS,
              [{"requestId": "1", "requestType": "OneTime", "userId": "2", "spaceId": "301",
                "participantCount": "5", "timeData": "1-09:00-10:00", "title": "Original request"}])
    write_csv(data / "request_participants.csv", web_app.REQUEST_PARTICIPANT_HEADERS, [])
    (data / "config.txt").write_text("allocation_strategy=greedy\n", encoding="utf-8")


def submit_process(url, start, results, title):
    web_app.app.config.update(TESTING=True, DATABASE_URL=url, DATABASE_LOCK_TIMEOUT=10)
    results.put(("ready", None))
    if not start.wait(10):
        raise RuntimeError("Concurrent submission start signal missing")
    response = web_app.app.test_client().post("/add-request", data=form(title))
    results.put((response.status_code, response.location))


def hold_lock_process(data_dir, acquired):
    with SharedFileState(data_dir).locked() as state:
        workspace = create_legacy_workspace(state)
        (workspace / "data" / "allocations.csv").write_text("partial worker output")
        acquired.set()
        time.sleep(60)


def crash_during_save_process(data_dir):
    state = SharedFileState(data_dir)
    real_write = atomic_write
    def crash_write(path, contents):
        real_write(path, contents)
        if Path(path).name == "request_participants.csv":
            os._exit(19)
    with state.locked(), mock.patch("legacy_shared_file_state.atomic_write", side_effect=crash_write):
        state.save_request({"requestId": "2", "requestType": "CommitteeMeeting", "title": "Crash save"},
                           [{"requestId": "2", "userId": "2", "participantRole": "Crash role"}],
                           web_app.REQUEST_HEADERS, web_app.REQUEST_PARTICIPANT_HEADERS)


class DatabaseWebConcurrencyTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        temporary = TemporaryDirectory(prefix="database-web-tests-")
        self.addCleanup(temporary.cleanup)
        self.data = Path(temporary.name)
        create_inputs(self.data)
        import_csv(self.database, self.data)
        self.repository = Repository(self.database)
        self.client = self.configure_web()
        self.context = multiprocessing.get_context("spawn")

    @property
    def adapter(self):
        return DatabaseResultAdapter(self.repository, web_app.RAW_DATA_FILES)

    def fake_execution(self, command, **kwargs):
        return subprocess.CompletedProcess(command, 0, json.dumps(fake_result(json.loads(kwargs["input"]))), "")

    def publish_fixture(self, marker="old"):
        run_id, snapshot = self.repository.start_run()
        result = fake_result(snapshot)
        for item in result["requestResults"]:
            item["rejectionReason"] = marker
        self.repository.publish_run(run_id, result, {})
        return run_id

    def assert_associations(self):
        requests = self.adapter.read_csv_table("requests.csv")["rows"]
        self.assertEqual(len(requests), 3)
        self.assertEqual(len({row["requestId"] for row in requests}), 3)
        by_id = {row["requestId"]: row for row in requests}
        participants = self.adapter.read_csv_table("request_participants.csv")["rows"]
        self.assertEqual(len(participants), 2)
        for participant in participants:
            self.assertEqual(participant["participantRole"], by_id[participant["requestId"]]["title"])

    def test_two_threads_save_unique_ids_and_matching_participants(self):
        start = threading.Barrier(2)
        def submit(title):
            start.wait(5)
            return web_app.app.test_client().post("/add-request", data=form(title))
        with ThreadPoolExecutor(2) as pool:
            responses = list(pool.map(submit, ["Thread A", "Thread B"]))
        self.assertEqual([response.status_code for response in responses], [302, 302])
        self.assertEqual(len({response.location for response in responses}), 2)
        self.assert_associations()

    def test_two_processes_save_unique_ids_and_matching_participants(self):
        start, results = self.context.Event(), self.context.Queue()
        processes = [self.context.Process(target=submit_process, args=(self.url, start, results, title))
                     for title in ("Process A", "Process B")]
        for process in processes:
            process.start()
            self.addCleanup(self.stop_process, process)
        self.assertEqual([results.get(timeout=20) for _ in processes], [("ready", None), ("ready", None)])
        start.set()
        responses = [results.get(timeout=20) for _ in processes]
        for process in processes:
            process.join(10)
            self.assertEqual(process.exitcode, 0)
        self.assertTrue(all(status == 302 for status, _ in responses))
        self.assertEqual(len({location for _, location in responses}), 2)
        self.assert_associations()
        results.close()

    def stop_process(self, process):
        if process.is_alive():
            process.terminate()
        process.join(5)

    def test_strategy_changes_do_not_leak_into_running_engine_snapshots(self):
        started, release = threading.Event(), threading.Event()
        snapshots = []
        def execution(command, **kwargs):
            snapshot = json.loads(kwargs["input"])
            snapshots.append(snapshot)
            if snapshot["strategy"] == "greedy":
                started.set()
                self.assertTrue(release.wait(10))
            return self.fake_execution(command, **kwargs)
        with mock.patch("web.engine_gateway.subprocess.run", side_effect=execution), ThreadPoolExecutor(2) as pool:
            first = pool.submit(lambda: web_app.app.test_client().post("/run-allocation"))
            self.assertTrue(started.wait(5))
            self.assertEqual(self.client.post("/set-strategy", data={"strategy": "priority"}).status_code, 302)
            second = self.client.post("/run-allocation")
            self.assertEqual(parse_qs(urlparse(second.location).query)["run_status"], ["success"])
            release.set()
            self.assertEqual(parse_qs(urlparse(first.result(10).location).query)["run_status"], ["error"])
        self.assertEqual([item["strategy"] for item in snapshots], ["greedy", "priority"])
        self.assertNotEqual(snapshots[0]["runId"], snapshots[1]["runId"])
        self.assertEqual(self.repository.read_view()[1]["snapshot"]["strategy"], "priority")
        self.assertIn("greedy", (self.data / "config.txt").read_text())

    def test_reader_pins_all_results_and_inputs_across_publication(self):
        old = self.publish_fixture()
        pinned = self.adapter
        self.client.post("/add-request", data=form("Later request"))
        self.publish_fixture("new")
        self.assertEqual(pinned.run_id, old)
        self.assertEqual(pinned.read_csv_table("request_results.csv")["rows"][0]["rejectionReason"], "old")
        self.assertEqual(pinned.read_csv_table("request_summaries.csv")["rows"][0]["summaryText"], "old")
        self.assertEqual(len(pinned.read_csv_table("requests.csv")["rows"]), 1)
        self.assertNotEqual(self.adapter.run_id, old)
        self.assertEqual(len(self.adapter.read_csv_table("requests.csv")["rows"]), 2)

    def test_flask_response_pins_results_once_even_if_publication_changes_mid_response(self):
        self.publish_fixture("old")
        original, original_summary = web_app.read_csv_table, web_app.build_request_list_context
        observed = []
        def switch_after_read(filename):
            table = original(filename)
            if filename == "request_results.csv":
                self.publish_fixture("new")
            return table
        def capture_summary():
            context = original_summary()
            observed.extend(context["items"])
            return context
        with mock.patch.object(web_app, "read_csv_table", side_effect=switch_after_read), \
                mock.patch.object(web_app, "build_request_list_context", side_effect=capture_summary):
            self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(observed[0]["rejection_reason"], "old")

    def test_nonzero_backend_does_not_publish_partial_outputs(self):
        old = self.publish_fixture()
        with mock.patch("web.engine_gateway.subprocess.run", return_value=subprocess.CompletedProcess([], 7, "", "failed")):
            result = web_app.run_backend_allocation()
        self.assertEqual(result["status"], "error")
        self.assertIn("7", result["message"])
        self.assertEqual(self.adapter.run_id, old)

    def assert_failed_submit_remains_pending(self, executor, expected):
        old = self.publish_fixture()
        with mock.patch("web.engine_gateway.subprocess.run", side_effect=executor):
            response = self.client.post("/add-request", data=form("Failure saved", "save_run"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(expected, parse_qs(urlparse(response.location).query)["run_message"][0])
        self.assertEqual(self.adapter.run_id, old)
        self.assertEqual(self.adapter.read_csv_table("request_participants.csv")["rows"][-1]["requestId"], "2")
        item, _ = self.adapter.get_request_summary("2")
        self.assertEqual(item["status"], "Pending")
        self.assertEqual(item["assigned_rooms"], [])
        self.assertEqual(self.client.get(response.location).status_code, 200)

    def test_backend_timeout_never_publishes_and_preserves_saved_request(self):
        def timeout(command, **kwargs):
            raise subprocess.TimeoutExpired(command, kwargs["timeout"], output=b"partial")
        self.assert_failed_submit_remains_pending(timeout, "timed out")

    def test_submit_and_run_backend_error_keeps_request_and_participants_pending(self):
        self.assert_failed_submit_remains_pending(lambda command, **kwargs: subprocess.CompletedProcess(command, 9, "", "bad"), "9")

    def test_zero_exit_with_missing_or_malformed_output_is_not_published(self):
        old = self.publish_fixture()
        def bad_output(command, **kwargs):
            result = fake_result(json.loads(kwargs["input"]))
            result["requestResults"] = []
            return subprocess.CompletedProcess(command, 0, json.dumps(result), "")
        for executor in (lambda command, **kwargs: subprocess.CompletedProcess(command, 0, "", ""), bad_output):
            with self.subTest(executor=executor), mock.patch("web.engine_gateway.subprocess.run", side_effect=executor):
                self.assertEqual(web_app.run_backend_allocation()["status"], "error")
                self.assertEqual(self.adapter.run_id, old)

    def test_publication_failure_keeps_previous_run_authoritative(self):
        old = self.publish_fixture()
        from web.persistence.repository import PersistenceError
        with mock.patch("web.engine_gateway.subprocess.run", side_effect=self.fake_execution), \
                mock.patch.object(Repository, "publish_run", side_effect=PersistenceError("publication denied")):
            result = web_app.run_backend_allocation()
        self.assertEqual(result["status"], "error")
        self.assertIn("publication denied", result["message"])
        self.assertEqual(self.adapter.run_id, old)

    def test_lock_timeout_returns_busy_and_does_not_modify_inputs_or_active_run(self):
        old = self.publish_fixture()
        before = self.adapter.read_csv_table("requests.csv")["rows"]
        with mock.patch.dict(web_app.app.config, {"DATABASE_LOCK_TIMEOUT": .1}), self.database.transaction() as session:
            state_row(session, lock=True)
            for route, data in (("/add-request", form("Busy")), ("/set-strategy", {"strategy": "priority"}), ("/run-allocation", {})):
                response = self.client.post(route, data=data)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.headers["Retry-After"], "2")
                self.assertIn("retry", response.get_data(as_text=True).lower())
        self.assertEqual(before, self.adapter.read_csv_table("requests.csv")["rows"])
        self.assertEqual(self.adapter.run_id, old)

    def test_save_only_does_not_execute_or_replace_published_generation(self):
        old = self.publish_fixture()
        with mock.patch("web.engine_gateway.subprocess.run") as execute:
            response = self.client.post("/add-request", data=form("Save only"))
        execute.assert_not_called()
        self.assertEqual(self.adapter.run_id, old)
        self.assertEqual(self.client.get(response.location).status_code, 200)
        self.assertEqual(self.adapter.get_request_summary("2")[0]["status"], "Pending")

    def test_submit_and_run_publishes_and_existing_views_use_it(self):
        with mock.patch("web.engine_gateway.subprocess.run", side_effect=self.fake_execution):
            response = self.client.post("/add-request", data=form("Submit and run", "save_run"))
        self.assertEqual(parse_qs(urlparse(response.location).query)["run_status"], ["success"])
        self.assertEqual(len(self.repository.read_view()[1]["result"]["requestResults"]), 2)
        for route in (response.location, "/", "/allocation-summary", "/requests", "/schedules",
                      "/schedules?type=user&id=2", "/schedules?type=space&id=301", "/users", "/spaces",
                      "/raw-data?file=request_summaries.csv", "/raw-data?file=allocation_summaries.csv"):
            with self.subTest(route=route):
                self.assertEqual(self.client.get(route).status_code, 200)

    def test_legacy_generated_files_and_json_are_not_read_or_overwritten_by_run(self):
        for name in (*OUTPUT_HEADERS, "engine-result.json"):
            (self.data / name).write_text("legacy file to preserve")
        with mock.patch("web.engine_gateway.subprocess.run", side_effect=self.fake_execution), \
                mock.patch("web.backend_result_adapter.BackendResultAdapter.pin", side_effect=AssertionError("CSV fallback used")):
            self.assertEqual(web_app.run_backend_allocation()["status"], "success")
            self.assertEqual(self.client.get("/").status_code, 200)
        for name in (*OUTPUT_HEADERS, "engine-result.json"):
            self.assertEqual((self.data / name).read_text(), "legacy file to preserve")


class LegacyFileRecoveryTests(TestCase):
    """Retain regression coverage for offline utilities, not operational web persistence."""
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.data = Path(temporary.name)
        create_inputs(self.data)
        self.state = SharedFileState(self.data)
        self.context = multiprocessing.get_context("spawn")

    def test_terminated_process_releases_os_lock_without_deleting_lockfile(self):
        acquired = self.context.Event()
        process = self.context.Process(target=hold_lock_process, args=(str(self.data), acquired))
        process.start()
        try:
            self.assertTrue(acquired.wait(10))
            with self.assertRaises(SharedStateBusy), SharedFileState(self.data, .1).locked():
                pass
        finally:
            process.terminate()
            process.join(10)
        with SharedFileState(self.data, .5).locked():
            self.assertTrue((self.state.root / "shared.lock").exists())
            self.assertTrue(list(self.state.root.glob("run-*/data/allocations.csv")))

    def test_crash_between_input_replacements_recovers_association_before_next_save(self):
        process = self.context.Process(target=crash_during_save_process, args=(str(self.data),))
        process.start()
        process.join(15)
        if process.is_alive():
            process.terminate()
            process.join(5)
        self.assertEqual(process.exitcode, 19)
        self.assertTrue(self.state.pending_save.exists())
        with self.state.locked():
            self.state.save_request({"requestId": "3", "requestType": "CommitteeMeeting", "title": "After crash"},
                                    [{"requestId": "3", "userId": "2", "participantRole": "After crash"}],
                                    web_app.REQUEST_HEADERS, web_app.REQUEST_PARTICIPANT_HEADERS)
        self.assertEqual([(row["requestId"], row["participantRole"]) for row in read_rows(self.data / "request_participants.csv")],
                         [("2", "Crash role"), ("3", "After crash")])
        self.assertFalse(self.state.pending_save.exists())

    def test_orphan_workspace_does_not_change_legacy_current_generation(self):
        with self.state.locked():
            orphan = create_legacy_workspace(self.state)
            (orphan / "data" / "allocations.csv").write_text("partial orphan")
            self.assertIsNone(self.state.current_data_dir())
        self.assertTrue(orphan.exists())


class DatabaseRealSubmitTests(PostgresTestCase):
    def test_real_submit_and_run_shows_approved_result_and_schedules(self):
        backend = resolve_backend_executable(ROOT)
        import_csv(self.database, ROOT / "tests" / "fixtures" / "runtime_no_demo")
        repository = Repository(self.database)
        client = self.configure_web()
        with mock.patch.dict(os.environ, {"RESOURCE_ALLOCATION_BACKEND": str(backend.path)}):
            response = client.post("/add-request", data={
                "requestType": "OneTime", "userId": "1", "spaceId": "101",
                "participantCount": "5", "day": "1", "startTime": "12:00", "endTime": "13:00",
                "title": "Live submit and run", "purpose": "Meeting", "requiredFeature": "None",
                "requiredBuilding": "Main", "submitAction": "save_run"})
        self.assertEqual(parse_qs(urlparse(response.location).query)["run_status"], ["success"])
        self.assertEqual(client.get(response.location).status_code, 200)
        adapter = DatabaseResultAdapter(repository, web_app.RAW_DATA_FILES)
        item, _ = adapter.get_request_summary("2")
        self.assertEqual(item["status"], "Approved")
        self.assertEqual(item["assigned_rooms"][0]["name"], "Runtime Classroom")
        for schedule_type, resource_id in (("space", "101"), ("user", "1")):
            schedule = adapter.get_schedule_context(schedule_type, resource_id)
            ids = {event["request_id"] for row in schedule["schedule_rows"] for day in row["days"] for event in day["events"]}
            self.assertIn("2", ids)
            self.assertEqual(client.get(f"/schedules?type={schedule_type}&id={resource_id}").status_code, 200)


class IsolatedCliSmokeTests(TestCase):
    def test_real_cli_writes_only_inside_temporary_workspace(self):
        backend = resolve_backend_executable(ROOT)
        with TemporaryDirectory(prefix="isolated-cli-") as temporary:
            data = Path(temporary) / "data"
            data.mkdir()
            for source in (ROOT / "tests" / "fixtures" / "runtime_no_demo").iterdir():
                (data / source.name).write_bytes(source.read_bytes())
            completed = subprocess.run([str(backend.path)], cwd=temporary, capture_output=True, text=True, timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            validate_legacy_outputs(data)
            self.assertEqual(read_rows(data / "request_results.csv")[0]["status"], "Approved")


if __name__ == "__main__":
    main()
