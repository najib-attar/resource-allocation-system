"""PostgreSQL web concurrency, atomic publication and request-saving regressions."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import main, mock
from urllib.parse import parse_qs, urlparse
import json
import multiprocessing
import os
import subprocess
import threading

from web import app as web_app
from web.backend_executable import resolve_backend_executable
from web.database_result_adapter import DatabaseResultAdapter
from web.persistence.importer import import_csv
from web.persistence.repository import Repository, state_row
from csv_cli_fixtures import CSV_OUTPUT_HEADERS
from engine_json_fixtures import fake_result
from postgres_web_fixtures import form, seed_web_database
from runtime_file_guard import forbid_runtime_files
from postgres_fixtures import PostgresTestCase, ROOT


def submit_process(url, start, results, title):
    web_app.app.config.update(TESTING=True, DATABASE_URL=url, DATABASE_LOCK_TIMEOUT=10)
    results.put(("ready", None))
    if not start.wait(10):
        raise RuntimeError("Concurrent submission start signal missing")
    response = web_app.app.test_client().post("/add-request", data=form(title))
    results.put((response.status_code, response.location))


class DatabaseWebConcurrencyTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        temporary = TemporaryDirectory(prefix="database-web-tests-")
        self.addCleanup(temporary.cleanup)
        self.data = Path(temporary.name)
        seed_web_database(self.database)
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
        requests = self.adapter.get_table("requests")["rows"]
        self.assertEqual(len(requests), 3)
        self.assertEqual(len({row["requestId"] for row in requests}), 3)
        by_id = {row["requestId"]: row for row in requests}
        participants = self.adapter.get_table("request_participants")["rows"]
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
        self.assertEqual(self.repository.snapshot()["strategy"], "priority")

    def test_reader_pins_all_results_and_inputs_across_publication(self):
        old = self.publish_fixture()
        pinned = self.adapter
        self.client.post("/add-request", data=form("Later request"))
        self.publish_fixture("new")
        self.assertEqual(pinned.run_id, old)
        self.assertEqual(pinned.get_table("request_results")["rows"][0]["rejectionReason"], "old")
        self.assertEqual(pinned.get_table("request_summaries")["rows"][0]["summaryText"], "old")
        self.assertEqual(len(pinned.get_table("requests")["rows"]), 1)
        self.assertNotEqual(self.adapter.run_id, old)
        self.assertEqual(len(self.adapter.get_table("requests")["rows"]), 2)

    def test_flask_response_pins_results_once_even_if_publication_changes_mid_response(self):
        self.publish_fixture("old")
        original, original_summary = web_app.get_table, web_app.build_request_list_context
        observed = []
        def switch_after_read(filename):
            table = original(filename)
            if filename == "request_results":
                self.publish_fixture("new")
            return table
        def capture_summary():
            context = original_summary()
            observed.extend(context["items"])
            return context
        with mock.patch.object(web_app, "get_table", side_effect=switch_after_read), \
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
        self.assertEqual(self.adapter.get_table("request_participants")["rows"][-1]["requestId"], "2")
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
        before = self.adapter.get_table("requests")["rows"]
        with mock.patch.dict(web_app.app.config, {"DATABASE_LOCK_TIMEOUT": .1}), self.database.transaction() as session:
            state_row(session, lock=True)
            for route, data in (("/add-request", form("Busy")), ("/set-strategy", {"strategy": "priority"}), ("/run-allocation", {})):
                response = self.client.post(route, data=data)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.headers["Retry-After"], "2")
                self.assertIn("retry", response.get_data(as_text=True).lower())
        self.assertEqual(before, self.adapter.get_table("requests")["rows"])
        self.assertEqual(self.adapter.run_id, old)

    def test_save_only_does_not_execute_or_replace_active_run(self):
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

    def test_stale_generated_files_and_json_are_not_read_or_overwritten_by_database_run(self):
        for name in (*CSV_OUTPUT_HEADERS, "engine-result.json"):
            (self.data / name).write_text("legacy file to preserve")
        with mock.patch("web.engine_gateway.subprocess.run", side_effect=self.fake_execution), \
                forbid_runtime_files():
            self.assertEqual(web_app.run_backend_allocation()["status"], "success")
            self.assertEqual(self.client.get("/").status_code, 200)
        for name in (*CSV_OUTPUT_HEADERS, "engine-result.json"):
            self.assertEqual((self.data / name).read_text(), "legacy file to preserve")


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


if __name__ == "__main__":
    main()
