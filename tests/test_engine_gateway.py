from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock
import csv
import json
import shutil
import subprocess

from engine_json_fixtures import fake_result
from web.backend_executable import BackendExecutable, BackendExecutableError, resolve_backend_executable
from csv_cli_fixtures import extract_meeting_suggestions
from web.backend_result_adapter import BackendResultAdapter
from web.engine_result_projection import input_tables, result_tables
from web.engine_gateway import (EngineGateway, EngineIntegrationError, validate_result,
    validate_appointment_result, validate_equipment_result, validate_equipment_series_result,
    validate_room_result, validate_room_series_result)
from web.persistence.importer import CsvInputs


ROOT = Path(__file__).resolve().parent.parent
STRATEGIES = ("greedy", "priority", "multi_room_exam_greedy", "multi_room_exam_best_fit", "shared_room_exam_best_fit")


def input_fixture():
    return {"protocolVersion": 1, "runId": "gateway-test", "strategy": "greedy",
            "users": [{"id": 1, "name": 'Professor, "Ada" \u00d6', "role": "Instructor"}],
            "spaces": [{"id": 101, "name": "Room", "type": "Classroom", "capacity": 100, "available": True,
                        "building": "Main", "features": {"projector": True, "whiteboard": True, "computers": False}}],
            "busySlots": [], "requests": [{"id": 1, "type": "OneTime", "requesterId": 1, "spaceId": 101,
                 "participantCount": 10, "title": 'Algorithms, "Part II" \u00d6\nSession', "purpose": "Teaching",
                 "slots": [{"day": 1, "startMinutes": 600, "endMinutes": 660}]}]}


class GatewayTests(TestCase):
    def setUp(self):
        self.snapshot = input_fixture()
        self.result = fake_result(self.snapshot)
        self.gateway = EngineGateway(ROOT)
        patch = mock.patch("web.engine_gateway.resolve_backend_executable", return_value=BackendExecutable(Path("engine.exe"), {}))
        patch.start(); self.addCleanup(patch.stop)

    def call(self, result=None, code=0, stderr=""):
        completed = subprocess.CompletedProcess([], code, json.dumps(self.result if result is None else result), stderr)
        with mock.patch("web.engine_gateway.subprocess.run", return_value=completed) as run:
            response = self.gateway.execute(self.snapshot)
        return response, run.call_args

    def test_success_passes_utf8_document_stdin_without_shell(self):
        (result, _), call = self.call()
        self.assertEqual(result, self.result)
        self.assertEqual(call.args[0], ["engine.exe", "--json"])
        self.assertEqual(json.loads(call.kwargs["input"]), self.snapshot)
        self.assertEqual(call.kwargs["encoding"], "utf-8")
        self.assertFalse(call.kwargs.get("shell", False))

    def test_nonzero_exit_never_succeeds(self):
        with self.assertRaisesRegex(EngineIntegrationError, "exit code 9"):
            self.call(code=9)

    def test_timeout_is_explicit(self):
        with mock.patch("web.engine_gateway.subprocess.run", side_effect=subprocess.TimeoutExpired([], 30)):
            with self.assertRaisesRegex(EngineIntegrationError, "timed out"):
                self.gateway.execute(self.snapshot)

    def test_malformed_stdout_is_rejected(self):
        for stdout in ("not-json", "{}\n{}", "debug\n{}", "NaN"):
            with self.subTest(stdout=stdout), mock.patch("web.engine_gateway.subprocess.run", return_value=subprocess.CompletedProcess([], 0, stdout, "")):
                with self.assertRaises(EngineIntegrationError): self.gateway.execute(self.snapshot)

    def test_stderr_diagnostics_do_not_contaminate_result(self):
        (result, _), _ = self.call(stderr="diagnostic warning")
        self.assertEqual(result["status"], "success")

    def test_protocol_mismatch_is_rejected(self):
        self.result["protocolVersion"] = 2
        with self.assertRaisesRegex(EngineIntegrationError, "protocolVersion"): self.call()

    def test_run_id_mismatch_is_rejected(self):
        self.result["runId"] = "other"
        with self.assertRaisesRegex(EngineIntegrationError, "runId"): self.call()

    def test_missing_executable_validation_is_not_bypassed(self):
        with mock.patch("web.engine_gateway.resolve_backend_executable", side_effect=BackendExecutableError("missing")), mock.patch("web.engine_gateway.subprocess.run") as run:
            with self.assertRaises(BackendExecutableError): self.gateway.execute(self.snapshot)
            run.assert_not_called()

    def test_stale_executable_validation_is_not_bypassed(self):
        with mock.patch("web.engine_gateway.resolve_backend_executable", side_effect=BackendExecutableError("stale")), mock.patch("web.engine_gateway.subprocess.run") as run:
            with self.assertRaises(BackendExecutableError): self.gateway.execute(self.snapshot)
            run.assert_not_called()

    def test_result_collections_and_fields_are_validated(self):
        for key in ("requestResults", "allocations", "suggestions", "errors"):
            result = deepcopy(self.result); result[key] = {}
            with self.subTest(key=key), self.assertRaises(EngineIntegrationError): validate_result(result, self.snapshot)
        for key, value in (("priority", True), ("history", "text"), ("status", "Pending"), ("status", {})):
            result = deepcopy(self.result); result["requestResults"][0][key] = value
            with self.subTest(key=key), self.assertRaises(EngineIntegrationError): validate_result(result, self.snapshot)

    def test_zero_exit_with_error_state_is_rejected(self):
        self.result.update(status="error", errors=[{"code": "INVALID_INPUT", "message": "invalid"}])
        with self.assertRaisesRegex(EngineIntegrationError, "zero exit"): self.call()

    def test_strategy_mismatch_is_rejected(self):
        self.result["strategy"] = "priority"
        with self.assertRaisesRegex(EngineIntegrationError, "strategy"): self.call()


class OperationEnvelopeTests(TestCase):
    def cases(self):
        period = {'start': 1800000000, 'end': 1800001800}
        common = {'runId': 'envelope-test', 'action': 'recommend', 'proposed': period,
                  'horizon': period, 'occurrences': [period]}
        equipment = common | {'items': [{'typeId': 1, 'quantity': 1}], 'types': [{'id': 1}], 'units': []}
        room = common | {'rooms': [], 'attendeeCount': 1}
        appointment = common | {'invitedIds': [], 'durationMinutes': 30}
        header = {'protocolVersion': 1, 'runId': common['runId'], 'status': 'success',
                  'engineVersion': 'test-engine', 'feasible': False, 'errors': []}
        equipment_body = {'items': [{'typeId': 1, 'availableQuantity': 0, 'reasonCode': 'INSUFFICIENT_QUANTITY',
                                     'unitIds': [], 'alternativeTypeIds': []}], 'alternativePeriods': []}
        room_body = {'reasonCode': 'NO_ELIGIBLE_ROOM', 'candidates': [], 'alternatives': [], 'explanations': []}
        return [
            (validate_equipment_result, equipment, header | equipment_body | {'operation': 'equipment'}, 'Invalid equipment engine response.'),
            (validate_room_result, room, header | room_body | {'operation': 'studentRoom'}, 'Invalid room-selection engine response.'),
            (validate_appointment_result, appointment, header | {'operation': 'appointment', 'reasonCode': 'NO_FEASIBLE_TIME', 'recommendations': []}, 'Invalid appointment engine response.'),
            (validate_equipment_series_result, equipment, header | {'operation': 'equipmentSeries', 'items': [], 'alternativePeriods': [],
                'occurrences': [period | equipment_body | {'feasible': False}]}, 'Invalid recurring reservation engine response.'),
            (validate_room_series_result, room, header | room_body | {'operation': 'studentRoomSeries',
                'occurrences': [period | room_body | {'feasible': False}]}, 'Invalid recurring reservation engine response.'),
        ]

    def test_all_operation_envelopes_preserve_valid_results(self):
        for validator, snapshot, result, _ in self.cases():
            with self.subTest(operation=result['operation']):
                self.assertIs(validator(result, snapshot), result)

    def test_all_operation_envelopes_preserve_rejection_and_error_messages(self):
        changes = [('protocolVersion', value) for value in (None, True, 1.0, '1', 2)] + [
            ('operation', 'other'), ('runId', 'other'), ('status', 'error'), ('status', 'pending'),
            ('engineVersion', ''), ('engineVersion', None), ('engineVersion', 1),
            ('feasible', None), ('feasible', 0), ('feasible', 'false'), ('errors', None), ('errors', {}), ('errors', ['failure'])]
        for validator, snapshot, result, message in self.cases():
            malformed = [None, [], True, 'not an object']
            malformed += [result | {key: value} for key, value in changes]
            malformed += [{key: value for key, value in result.items() if key != omitted}
                for omitted in ('protocolVersion', 'operation', 'runId', 'status', 'engineVersion', 'feasible', 'errors')]
            for invalid in malformed:
                with self.subTest(operation=result['operation'], invalid=invalid):
                    with self.assertRaises(EngineIntegrationError) as error:
                        validator(invalid, snapshot)
                    self.assertEqual(str(error.exception), message)


class JsonEngineIntegrationTests(TestCase):
    def setUp(self):
        self.backend = resolve_backend_executable(ROOT)  # Required, not a skipped verification.
        self.gateway = EngineGateway(ROOT)

    def test_real_engine_supports_all_four_types_and_utf8(self):
        for kind in ("OneTime", "Recurring", "Exam", "CommitteeMeeting"):
            with self.subTest(kind=kind):
                snapshot = input_fixture(); request = snapshot["requests"][0]; request["type"] = kind
                if kind == "Recurring": request["slots"].append({"day": 2, "startMinutes": 600, "endMinutes": 660})
                if kind == "Exam": request["exam"] = {"courseCode": "CS1", "courseName": 'Algorithms, "II"', "examType": "Final", "canSplitAcrossRooms": True}
                if kind == "CommitteeMeeting":
                    snapshot["spaces"][0]["type"] = "MeetingRoom"
                    request["participants"] = [{"userId": 1, "role": "Chair"}]
                result, _ = self.gateway.execute(snapshot)
                self.assertEqual(result["requestResults"][0]["status"], "Approved")
                self.assertEqual(result["requestResults"][0]["title"], request["title"])
                self.assertEqual(len(result["allocations"]), 2 if kind == "Recurring" else 1)

    def test_json_needs_no_csv_or_config_and_writes_no_files(self):
        with TemporaryDirectory() as temporary:
            response = subprocess.run([str(self.backend.path), "--json"], input=json.dumps(input_fixture()), encoding="utf-8",
                                      capture_output=True, cwd=temporary, timeout=30)
            self.assertEqual(response.returncode, 0, response.stderr)
            self.assertEqual(json.loads(response.stdout)["status"], "success")
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_real_protocol_errors_are_one_json_document_with_nonzero_exit(self):
        snapshot = input_fixture()
        cases = ["{broken"]
        for key, value in (("protocolVersion", 2), ("strategy", "unknown"), ("requests", [{}]), ("protocolVersion", None)):
            invalid = deepcopy(snapshot)
            if value is None: invalid.pop(key)
            else: invalid[key] = value
            cases.append(json.dumps(invalid))
        for document in cases:
            with self.subTest(document=document):
                response = subprocess.run([str(self.backend.path), "--json"], input=document, encoding="utf-8", capture_output=True, timeout=30)
                self.assertEqual(response.returncode, 2, response.stderr)
                self.assertEqual(json.loads(response.stdout)["status"], "error")

    def test_real_best_fit_limits_are_errors_not_publication_candidates(self):
        for strategy in ('multi_room_exam_best_fit', 'shared_room_exam_best_fit'):
            for capacity in (10000000, 2147483647):
                with self.subTest(strategy=strategy, capacity=capacity), TemporaryDirectory() as temporary:
                    snapshot = input_fixture()
                    snapshot['strategy'] = strategy
                    snapshot['spaces'][0]['capacity'] = capacity
                    snapshot['requests'][0].update(type='Exam', exam={'courseCode': 'CS1',
                        'courseName': 'Safety', 'examType': 'Final', 'canSplitAcrossRooms': True})
                    response = subprocess.run([str(self.backend.path), '--json'], input=json.dumps(snapshot),
                        encoding='utf-8', capture_output=True, cwd=temporary, timeout=10)
                    self.assertEqual(response.returncode, 3, response.stderr)
                    result = json.loads(response.stdout)
                    self.assertEqual(result['status'], 'error')
                    self.assertEqual(result['errors'][0]['code'], 'ENGINE_FAILURE')
                    self.assertEqual(result['allocations'], [])
                    self.assertEqual(result['requestResults'], [])
                    self.assertIn('Best-fit', response.stderr)
                    self.assertEqual(list(Path(temporary).iterdir()), [])
                    with self.assertRaisesRegex(EngineIntegrationError, 'exit code 3'):
                        self.gateway.execute(snapshot)

    def test_legacy_best_fit_limits_exit_cleanly_without_replacing_outputs(self):
        for strategy in ('multi_room_exam_best_fit', 'shared_room_exam_best_fit'):
            with self.subTest(strategy=strategy), TemporaryDirectory() as temporary:
                data = Path(temporary) / 'data'
                data.mkdir()
                for name in ('users.csv', 'spaces.csv', 'requests.csv', 'request_participants.csv',
                             'user_busy_slots.csv', 'config.txt'):
                    shutil.copy2(ROOT / 'data' / name, data / name)
                with (data / 'users.csv').open(encoding='utf-8-sig', newline='') as source:
                    instructors = {row['userId'] for row in csv.DictReader(source) if row['role'] == 'Instructor'}
                for name in ('spaces.csv', 'requests.csv'):
                    with (data / name).open(encoding='utf-8-sig', newline='') as source:
                        reader = csv.DictReader(source)
                        fields, rows = reader.fieldnames, list(reader)
                    if name == 'spaces.csv':
                        for row in rows:
                            row['capacity'] = '10000000'
                    else:
                        rows = [next(row for row in rows if row['requestType'] == 'Exam' and row['userId'] in instructors)]
                        rows[0].update(canSplitAcrossRooms='true', requiredFeature='', requiredBuilding='')
                    with (data / name).open('w', encoding='utf-8', newline='') as target:
                        writer = csv.DictWriter(target, fieldnames=fields)
                        writer.writeheader()
                        writer.writerows(rows)
                (data / 'config.txt').write_text('allocation_strategy=' + strategy, encoding='utf-8')
                outputs = ('allocations.csv', 'request_results.csv', 'request_summaries.csv', 'allocation_summaries.csv')
                for name in outputs:
                    (data / name).write_bytes(b'previous successful output\n')
                response = subprocess.run([str(self.backend.path)], cwd=temporary, encoding='utf-8',
                                          capture_output=True, timeout=10)
                self.assertEqual(response.returncode, 1, response.stderr)
                self.assertIn('Allocation failed: Best-fit', response.stderr)
                self.assertIn('No results exported', response.stderr)
                for name in outputs:
                    self.assertEqual((data / name).read_bytes(), b'previous successful output\n')

    def test_allocation_and_suggestion_output_shapes_are_checked(self):
        snapshot = input_fixture()
        result, _ = self.gateway.execute(snapshot)
        for key, value in (("slot", {}), ("spaceId", 999), ("assignedParticipants", -1), ("spaceCapacity", True)):
            invalid = deepcopy(result); invalid["allocations"][0][key] = value
            with self.subTest(key=key), self.assertRaises(EngineIntegrationError): validate_result(invalid, snapshot)
        invalid = deepcopy(result); invalid["suggestions"] = [{"requestId": 999, "items": []}]
        with self.assertRaises(EngineIntegrationError): validate_result(invalid, snapshot)

    def compare_legacy(self, source):
        with TemporaryDirectory(prefix="legacy-json-comparison-") as temporary:
            data = Path(temporary) / "data"; data.mkdir()
            for name in ("users.csv", "spaces.csv", "requests.csv", "request_participants.csv", "user_busy_slots.csv", "config.txt"):
                if (source / name).exists(): shutil.copy2(source / name, data / name)
            for strategy in STRATEGIES:
                with self.subTest(source=source.name, strategy=strategy):
                    (data / "config.txt").write_text("allocation_strategy=" + strategy, encoding="utf-8")
                    snapshot = CsvInputs(data).snapshot()
                    snapshot["strategy"] = strategy
                    result, _ = self.gateway.execute(snapshot)
                    legacy = subprocess.run([str(self.backend.path)], cwd=temporary, capture_output=True, encoding="utf-8", timeout=30)
                    self.assertEqual(legacy.returncode, 0, legacy.stderr)
                    def rows(name):
                        with (data / name).open(encoding="utf-8-sig", newline="") as file: return list(csv.DictReader(file))
                    old_decisions = {(int(row["requestId"]), row["status"], "" if row["rejectionReason"] == "None" else row["rejectionReason"])
                                     for row in rows("request_results.csv")}
                    self.assertEqual(old_decisions, {(row["requestId"], row["status"], row["rejectionReason"]) for row in result["requestResults"]})
                    old_allocations = [(int(row["requestId"]), int(row["spaceId"]), int(row["day"]), row["startHour"], row["endHour"], int(row["assignedParticipants"])) for row in rows("allocations.csv")]
                    def clock(value): return f"{value // 60:02d}:{value % 60:02d}"
                    self.assertEqual(old_allocations, [(row["requestId"], row["spaceId"], row["slot"]["day"], clock(row["slot"]["startMinutes"]), clock(row["slot"]["endMinutes"]), row["assignedParticipants"]) for row in result["allocations"]])
                    groups = {group["requestId"]: group for group in result["suggestions"]}
                    from web.engine_result_projection import suggestion_display
                    for row in rows("request_results.csv"):
                        old = extract_meeting_suggestions(row["lifecycleHistory"])
                        group = groups.get(int(row["requestId"]))
                        self.assertEqual(old["items"] if old else None, suggestion_display(group)["items"] if group else None)

    def test_normal_dataset_matches_legacy_for_all_five_strategies(self):
        self.compare_legacy(ROOT / "data")

    def test_clean_fixture_matches_legacy_for_all_five_strategies(self):
        self.compare_legacy(ROOT / "tests" / "fixtures" / "runtime_no_demo")

    def test_suggestions_render_without_history_parsing(self):
        snapshot = input_fixture(); snapshot["spaces"][0]["type"] = "MeetingRoom"
        request = snapshot["requests"][0]; request["type"] = "CommitteeMeeting"; request["participants"] = [{"userId": 1, "role": "Chair"}]
        snapshot["busySlots"] = [{"userId": 1, "slot": request["slots"][0], "reason": "Lecture"}]
        result, _ = self.gateway.execute(snapshot)
        result["requestResults"][0]["history"] = []
        from web import app as web_app
        tables = input_tables(snapshot) | result_tables(snapshot, result)
        adapter = BackendResultAdapter(tables, web_app.RAW_DATA_FILES, engine_result=result)
        item, _ = adapter.get_request_summary("1")
        self.assertEqual(len(item["meeting_suggestions"]["items"]), 3)
        repository = mock.Mock()
        repository.read_view.return_value = (snapshot, {"snapshot": snapshot, "result": result, "build": {}}, 1)
        from auth_fixtures import authorized_client, mocked_administrator
        with mock.patch.object(web_app, "get_repository", return_value=repository), mocked_administrator():
            response = authorized_client(web_app.app).get("/request/1")
            self.assertEqual(response.status_code, 200)
            self.assertIn("Suggested least-change", response.get_data(as_text=True))

    def test_independent_json_strategies_do_not_modify_config(self):
        from concurrent.futures import ThreadPoolExecutor
        before = (ROOT / "data" / "config.txt").read_bytes()
        snapshots = [input_fixture(), input_fixture()]
        snapshots[1]["strategy"] = "priority"; snapshots[1]["runId"] = "other-run"
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(self.gateway.execute, snapshots))
        self.assertEqual([result[0]["strategy"] for result in results], ["greedy", "priority"])
        self.assertEqual(before, (ROOT / "data" / "config.txt").read_bytes())
