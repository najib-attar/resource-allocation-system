"""Defect 6 regressions. Spawn processes exercise the actual platform OS lock."""

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
from web.backend_result_adapter import BackendResultAdapter
from web.shared_file_state import OUTPUT_HEADERS, SharedFileState, SharedStateBusy, atomic_write
from engine_json_fixtures import fake_result


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


def submit_process(data_dir, start, results, title):
    web_app.DATA_DIR = Path(data_dir)
    web_app.backend_results = BackendResultAdapter(data_dir, web_app.RAW_DATA_FILES)
    web_app.app.config.update(TESTING=True, SHARED_FILE_LOCK_TIMEOUT=10)
    results.put(("ready", None))
    if not start.wait(10):
        raise RuntimeError("Concurrent submission start signal missing")
    original_save = SharedFileState.save_request
    def slow_save(state, *args, **kwargs):
        time.sleep(.15)
        return original_save(state, *args, **kwargs)
    with mock.patch.object(SharedFileState, "save_request", new=slow_save):
        response = web_app.app.test_client().post("/add-request", data=form(title))
    results.put((response.status_code, response.location))


def hold_lock_process(data_dir, acquired):
    with SharedFileState(data_dir).locked() as state:
        workspace = state.create_workspace()
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
    with state.locked(), mock.patch("web.shared_file_state.atomic_write", side_effect=crash_write):
        state.save_request({"requestId": "2", "requestType": "CommitteeMeeting", "title": "Crash save"},
                           [{"requestId": "2", "userId": "2", "participantRole": "Crash role"}],
                           web_app.REQUEST_HEADERS, web_app.REQUEST_PARTICIPANT_HEADERS)


def fake_outputs(workspace, marker="complete"):
    """Structurally valid test outputs; never pretend these exercise C++ algorithms."""
    data = Path(workspace) / "data"
    requests = read_rows(data / "requests.csv")
    results = []
    summaries = []
    for request in requests:
        result = {key: "" for key in OUTPUT_HEADERS["request_results.csv"].split(",")}
        result.update(requestId=request["requestId"], requestType=request["requestType"],
                      status="Rejected", title=request.get("title", ""), rejectionReason=marker)
        results.append(result)
        summary = {key: "" for key in OUTPUT_HEADERS["request_summaries.csv"].split(",")}
        summary.update(requestId=request["requestId"], requestType=request["requestType"],
                       status="Rejected", title=request.get("title", ""), summaryText=marker)
        summaries.append(summary)
    for name, rows in (("request_results.csv", results), ("request_summaries.csv", summaries),
                       ("allocations.csv", []), ("allocation_summaries.csv", [])):
        write_csv(data / name, OUTPUT_HEADERS[name].split(","), rows)


class SharedFileConcurrencyTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="shared-file-tests-")
        self.addCleanup(temporary.cleanup)
        self.data = Path(temporary.name) / "data"
        self.data.mkdir()
        write_csv(self.data / "users.csv", ["userId", "name", "role"],
                  [{"userId": "2", "name": "Professor Ada", "role": "Instructor"}])
        write_csv(self.data / "spaces.csv", ["spaceId", "type", "name", "capacity", "building"],
                  [{"spaceId": "301", "type": "MeetingRoom", "name": "M301", "capacity": "20", "building": "Main"}])
        write_csv(self.data / "requests.csv", web_app.REQUEST_HEADERS,
                  [{"requestId": "1", "requestType": "OneTime", "userId": "2", "spaceId": "301",
                    "participantCount": "5", "timeData": "1-09:00-10:00", "title": "Original request"}])
        write_csv(self.data / "request_participants.csv", web_app.REQUEST_PARTICIPANT_HEADERS, [])
        (self.data / "config.txt").write_text("allocation_strategy=greedy\n", encoding="utf-8")
        self.state = SharedFileState(self.data)
        self.adapter = BackendResultAdapter(self.data, web_app.RAW_DATA_FILES)
        for patch in (mock.patch.object(web_app, "DATA_DIR", self.data),
                      mock.patch.object(web_app, "backend_results", self.adapter),
                      mock.patch.dict(web_app.app.config, {"TESTING": True, "PROPAGATE_EXCEPTIONS": True,
                                                          "SHARED_FILE_LOCK_TIMEOUT": 5, "BACKEND_TIMEOUT": 30})):
            patch.start()
            self.addCleanup(patch.stop)
        self.client = web_app.app.test_client()
        self.context = multiprocessing.get_context("spawn")

    def publish_fixture(self, marker="old"):
        with self.state.locked():
            workspace = self.state.create_workspace()
            fake_outputs(workspace, marker)
            return self.state.publish(workspace, {"test": marker})

    def fake_execution(self, command, **kwargs):
        snapshot = json.loads(kwargs["input"])
        return subprocess.CompletedProcess(command, 0, json.dumps(fake_result(snapshot)), "")

    def assert_associations(self):
        requests = read_rows(self.data / "requests.csv")
        self.assertEqual(len(requests), 3)
        self.assertEqual(len({row["requestId"] for row in requests}), 3)
        by_id = {row["requestId"]: row for row in requests}
        participants = read_rows(self.data / "request_participants.csv")
        self.assertEqual(len(participants), 2)
        for participant in participants:
            self.assertEqual(participant["participantRole"], by_id[participant["requestId"]]["title"])

    def test_two_threads_save_unique_ids_and_matching_participants(self):
        start = threading.Barrier(2)
        def submit(title):
            start.wait(5)
            return web_app.app.test_client().post("/add-request", data=form(title))
        original_save = SharedFileState.save_request
        def slow_save(state, *args, **kwargs):
            time.sleep(.15)
            return original_save(state, *args, **kwargs)
        with mock.patch.object(SharedFileState, "save_request", new=slow_save):
            with ThreadPoolExecutor(2) as pool:
                responses = list(pool.map(submit, ["Thread A", "Thread B"]))
        self.assertEqual([response.status_code for response in responses], [302, 302])
        self.assertEqual(len({response.location for response in responses}), 2)
        self.assert_associations()

    def test_two_processes_save_unique_ids_and_matching_participants(self):
        start, results = self.context.Event(), self.context.Queue()
        processes = [self.context.Process(target=submit_process, args=(str(self.data), start, results, title))
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

    def test_strategy_changes_are_serialized_and_execution_configs_are_isolated(self):
        started, release = threading.Event(), threading.Event()
        configs = []
        def execution(command, **kwargs):
            snapshot = json.loads(kwargs["input"])
            before = snapshot["strategy"]
            if not configs:
                started.set()
                self.assertTrue(release.wait(5))
            self.assertEqual(before, json.loads(kwargs["input"])["strategy"])
            configs.append((before, snapshot["runId"]))
            return self.fake_execution(command, **kwargs)
        def run_greedy():
            return web_app.app.test_client().post("/run-allocation")
        def change_then_run():
            client = web_app.app.test_client()
            changed = client.post("/set-strategy", data={"strategy": "priority"})
            self.assertEqual(changed.status_code, 302)
            return client.post("/run-allocation")
        with mock.patch.object(web_app.subprocess, "run", side_effect=execution):
            with ThreadPoolExecutor(2) as pool:
                first = pool.submit(run_greedy)
                self.assertTrue(started.wait(5))
                second = pool.submit(change_then_run)
                time.sleep(.15)
                self.assertFalse(second.done())
                self.assertIn("greedy", (self.data / "config.txt").read_text())
                release.set()
                for future in (first, second):
                    response = future.result(10)
                    self.assertEqual(parse_qs(urlparse(response.location).query)["run_status"], ["success"])
        self.assertEqual([config for config, _ in configs], ["greedy", "priority"])
        self.assertNotEqual(configs[0][1], configs[1][1])
        self.assertEqual(self.state.read_engine_result()["snapshot"]["strategy"], "priority")

    def test_reader_pins_all_results_and_inputs_across_atomic_publication(self):
        old = self.publish_fixture()
        pinned = self.adapter.pin()
        self.assertEqual(pinned.generation_dir, old)
        self.client.post("/add-request", data=form("Later request"))
        self.publish_fixture("new")
        self.assertEqual(pinned.read_csv_table("request_results.csv")["rows"][0]["rejectionReason"], "old")
        self.assertEqual(pinned.read_csv_table("request_summaries.csv")["rows"][0]["summaryText"], "old")
        self.assertEqual(len(pinned.read_csv_table("requests.csv")["rows"]), 1)
        latest = self.adapter.pin()
        self.assertNotEqual(latest.generation_dir, old)
        self.assertEqual(latest.read_csv_table("request_summaries.csv")["rows"][0]["summaryText"], "new")
        self.assertEqual(len(latest.read_csv_table("requests.csv")["rows"]), 2)

    def test_flask_response_pins_results_once_even_if_pointer_changes_mid_response(self):
        self.publish_fixture("old")
        original = web_app.read_csv_table
        original_summary = web_app.build_request_list_context
        changed = False
        observed = []
        def switch_after_read(filename):
            nonlocal changed
            table = original(filename)
            if filename == "request_results.csv" and not changed:
                changed = True
                self.publish_fixture("new")
            return table
        def capture_summary():
            observed.extend(original_summary()["items"])
            return original_summary()
        with mock.patch.object(web_app, "read_csv_table", side_effect=switch_after_read), \
                mock.patch.object(web_app, "build_request_list_context", side_effect=capture_summary):
            response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(changed)
        self.assertEqual(observed[0]["rejection_reason"], "old")

    def test_nonzero_backend_does_not_publish_partial_outputs(self):
        old = self.publish_fixture()
        def fail(command, **kwargs):
            return subprocess.CompletedProcess(command, 7, "", "failed")
        with mock.patch.object(web_app.subprocess, "run", side_effect=fail):
            result = web_app.run_backend_allocation()
        self.assertEqual(result["status"], "error")
        self.assertIn("7", result["message"])
        self.assertEqual(self.state.current_data_dir(), old)

    def test_backend_timeout_never_publishes_and_preserves_saved_request(self):
        old = self.publish_fixture()
        with mock.patch.object(web_app.subprocess, "run", side_effect=self.fake_execution):
            self.assertEqual(web_app.run_backend_allocation()["status"], "success")
        previous_json = (self.state.root / "engine-result.json").read_bytes()
        def timeout(command, **kwargs):
            raise subprocess.TimeoutExpired(command, kwargs["timeout"], output=b"partial")
        with mock.patch.object(web_app.subprocess, "run", side_effect=timeout):
            response = self.client.post("/add-request", data=form("Timeout saved", "save_run"))
        self.assertIn("timed out", parse_qs(urlparse(response.location).query)["run_message"][0])
        self.assertEqual(self.state.current_data_dir(), old)
        self.assertEqual((self.state.root / "engine-result.json").read_bytes(), previous_json)
        self.assertEqual(read_rows(self.data / "requests.csv")[-1]["title"], "Timeout saved")
        item, _ = self.adapter.pin().get_request_summary("2")
        self.assertEqual(item["status"], "Pending")
        self.assertEqual(item["assigned_rooms"], [])

    def test_submit_and_run_backend_error_keeps_request_and_participants_pending(self):
        old = self.publish_fixture()
        with mock.patch.object(web_app.subprocess, "run", side_effect=self.fake_execution):
            self.assertEqual(web_app.run_backend_allocation()["status"], "success")
        previous_json = (self.state.root / "engine-result.json").read_bytes()
        with mock.patch.object(web_app.subprocess, "run", return_value=subprocess.CompletedProcess([], 9, "", "bad")):
            response = self.client.post("/add-request", data=form("Failure saved", "save_run"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(parse_qs(urlparse(response.location).query)["run_status"], ["error"])
        self.assertEqual(self.state.current_data_dir(), old)
        self.assertEqual((self.state.root / "engine-result.json").read_bytes(), previous_json)
        self.assertEqual(read_rows(self.data / "request_participants.csv")[-1]["requestId"], "2")
        self.assertEqual(self.adapter.pin().get_request_summary("2")[0]["status"], "Pending")
        self.assertEqual(self.client.get(response.location).status_code, 200)

    def test_zero_exit_with_missing_or_malformed_output_is_not_published(self):
        old = self.publish_fixture()
        def bad_output(command, **kwargs):
            result = fake_result(json.loads(kwargs["input"]))
            result["requestResults"] = []
            return subprocess.CompletedProcess(command, 0, json.dumps(result), "")
        for executor in (lambda command, **kwargs: subprocess.CompletedProcess(command, 0, "", ""), bad_output):
            with self.subTest(executor=executor), mock.patch.object(web_app.subprocess, "run", side_effect=executor):
                result = web_app.run_backend_allocation()
                self.assertEqual(result["status"], "error")
                self.assertEqual(self.state.current_data_dir(), old)

    def test_publication_failure_keeps_previous_pointer_authoritative(self):
        old = self.publish_fixture()
        real_replace = os.replace
        def fail_pointer(source, destination):
            if Path(destination) == self.state.root / "engine-result.json":
                raise OSError("publication denied")
            return real_replace(source, destination)
        with mock.patch.object(web_app.subprocess, "run", side_effect=self.fake_execution), \
                mock.patch("web.shared_file_state.os.replace", side_effect=fail_pointer):
            result = web_app.run_backend_allocation()
        self.assertEqual(result["status"], "error")
        self.assertIn("publication denied", result["message"])
        self.assertEqual(self.state.current_data_dir(), old)
        self.assertFalse(list(self.state.root.glob(".replace-*")))

    def test_lock_timeout_returns_busy_and_does_not_modify_inputs_or_pointer(self):
        self.publish_fixture()
        before = {path.name: path.read_bytes() for path in self.data.glob("*") if path.is_file()}
        pointer = self.state.pointer.read_bytes()
        with mock.patch.dict(web_app.app.config, {"SHARED_FILE_LOCK_TIMEOUT": .1}), self.state.locked():
            for route, data in (("/add-request", form("Busy")), ("/set-strategy", {"strategy": "priority"}),
                                ("/run-allocation", {})):
                response = self.client.post(route, data=data)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.headers["Retry-After"], "2")
                self.assertIn("retry", response.get_data(as_text=True).lower())
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.data.glob("*") if path.is_file()})
        self.assertEqual(pointer, self.state.pointer.read_bytes())

    def test_terminated_process_releases_os_lock_without_deleting_lockfile(self):
        old = self.publish_fixture()
        acquired = self.context.Event()
        process = self.context.Process(target=hold_lock_process, args=(str(self.data), acquired))
        process.start()
        self.addCleanup(self.stop_process, process)
        self.assertTrue(acquired.wait(10))
        with self.assertRaises(SharedStateBusy), SharedFileState(self.data, .1).locked():
            pass
        process.terminate()
        process.join(10)
        with SharedFileState(self.data, .5).locked():
            self.assertTrue((self.state.root / "shared.lock").exists())
            self.assertEqual(self.state.current_data_dir(), old)
            self.assertTrue(list(self.state.root.glob("run-*/data/allocations.csv")))

    def test_crash_between_input_replacements_recovers_association_before_next_save(self):
        process = self.context.Process(target=crash_during_save_process, args=(str(self.data),))
        process.start()
        self.addCleanup(self.stop_process, process)
        process.join(15)
        self.assertEqual(process.exitcode, 19)
        self.assertTrue(self.state.pending_save.exists())
        response = self.client.post("/add-request", data=form("After crash"))
        self.assertTrue(response.location.endswith("/request-added/3"))
        participants = read_rows(self.data / "request_participants.csv")
        self.assertEqual([(row["requestId"], row["participantRole"]) for row in participants],
                         [("2", "Crash role"), ("3", "After crash")])
        self.assertFalse(self.state.pending_save.exists())

    def test_orphan_workspace_is_ignored_and_current_generation_is_not_removed(self):
        old = self.publish_fixture()
        with self.state.locked():
            orphan = self.state.create_workspace()
        (orphan / "data" / "allocations.csv").write_text("partial orphan")
        with mock.patch.object(web_app.subprocess, "run", side_effect=self.fake_execution):
            result = web_app.run_backend_allocation()
        self.assertEqual(result["status"], "success")
        self.assertTrue(old.exists())
        self.assertTrue(orphan.exists())
        self.assertIsNotNone(self.state.read_engine_result())
        self.assertNotEqual(self.state.current_data_dir().parent, orphan)

    def test_save_only_does_not_execute_or_replace_published_generation(self):
        old = self.publish_fixture()
        with mock.patch.object(web_app.subprocess, "run") as execute:
            response = self.client.post("/add-request", data=form("Save only"))
        execute.assert_not_called()
        self.assertEqual(self.state.current_data_dir(), old)
        self.assertEqual(self.client.get(response.location).status_code, 200)
        self.assertEqual(self.adapter.pin().get_request_summary("2")[0]["status"], "Pending")

    def test_submit_and_run_publishes_and_existing_views_use_it(self):
        with mock.patch.object(web_app.subprocess, "run", side_effect=self.fake_execution):
            response = self.client.post("/add-request", data=form("Submit and run", "save_run"))
        self.assertEqual(parse_qs(urlparse(response.location).query)["run_status"], ["success"])
        self.assertEqual(len(self.state.read_engine_result()["result"]["requestResults"]), 2)
        for route in (response.location, "/", "/allocation-summary", "/requests", "/schedules",
                      "/schedules?type=user&id=2", "/schedules?type=space&id=301",
                      "/raw-data?file=request_summaries.csv", "/raw-data?file=allocation_summaries.csv"):
            with self.subTest(route=route):
                self.assertEqual(self.client.get(route).status_code, 200)

    def test_legacy_generated_files_are_not_overwritten_by_run(self):
        for name in OUTPUT_HEADERS:
            (self.data / name).write_text("legacy file to preserve")
        with mock.patch.object(web_app.subprocess, "run", side_effect=self.fake_execution):
            self.assertEqual(web_app.run_backend_allocation()["status"], "success")
        for name in OUTPUT_HEADERS:
            self.assertEqual((self.data / name).read_text(), "legacy file to preserve")


class IsolatedCliSmokeTests(TestCase):
    def test_real_submit_and_run_shows_approved_result_and_schedules(self):
        root = Path(__file__).resolve().parent.parent
        backend = resolve_backend_executable(root)
        with TemporaryDirectory(prefix="real-submit-run-") as temporary:
            data = Path(temporary) / "data"
            data.mkdir()
            for source in (root / "tests" / "fixtures" / "runtime_no_demo").iterdir():
                (data / source.name).write_bytes(source.read_bytes())
            adapter = BackendResultAdapter(data, web_app.RAW_DATA_FILES)
            with mock.patch.object(web_app, "DATA_DIR", data), \
                    mock.patch.object(web_app, "backend_results", adapter), \
                    mock.patch.dict(os.environ, {"RESOURCE_ALLOCATION_BACKEND": str(backend.path)}):
                client = web_app.app.test_client()
                response = client.post("/add-request", data={
                    "requestType": "OneTime", "userId": "1", "spaceId": "101",
                    "participantCount": "5", "day": "1", "startTime": "12:00", "endTime": "13:00",
                    "title": "Live submit and run", "purpose": "Meeting", "requiredFeature": "None",
                    "requiredBuilding": "Main", "submitAction": "save_run",
                })
                self.assertEqual(response.status_code, 302)
                self.assertEqual(parse_qs(urlparse(response.location).query)["run_status"], ["success"])
                self.assertEqual(client.get(response.location).status_code, 200)
                item, _ = adapter.pin().get_request_summary("2")
                self.assertEqual(item["status"], "Approved")
                self.assertEqual(item["assigned_rooms"][0]["name"], "Runtime Classroom")
                for schedule_type, resource_id in (("space", "101"), ("user", "1")):
                    schedule = adapter.pin().get_schedule_context(schedule_type, resource_id)
                    ids = {event["request_id"] for row in schedule["schedule_rows"]
                           for day in row["days"] for event in day["events"]}
                    self.assertIn("2", ids)
                    self.assertEqual(client.get(f"/schedules?type={schedule_type}&id={resource_id}").status_code, 200)
                for name in OUTPUT_HEADERS:
                    self.assertFalse((data / name).exists())

    def test_real_cli_writes_only_inside_temporary_workspace(self):
        root = Path(__file__).resolve().parent.parent
        backend = resolve_backend_executable(root)
        with TemporaryDirectory(prefix="isolated-cli-") as temporary:
            data = Path(temporary) / "data"
            data.mkdir()
            fixture = root / "tests" / "fixtures" / "runtime_no_demo"
            for source in fixture.iterdir():
                (data / source.name).write_bytes(source.read_bytes())
            completed = subprocess.run([str(backend.path)], cwd=temporary, capture_output=True, text=True, timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            state = SharedFileState(data)
            state.validate_outputs(Path(temporary))
            self.assertEqual(read_rows(data / "request_results.csv")[0]["status"], "Approved")


if __name__ == "__main__":
    main()
