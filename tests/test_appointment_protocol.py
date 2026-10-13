"""Appointment process-contract validation, independent of database storage."""

import copy
import json
import subprocess
from pathlib import Path
from unittest import TestCase, mock

ROOT = Path(__file__).resolve().parent.parent
from web.backend_executable import resolve_backend_executable
from web.engine_gateway import EngineGateway, EngineIntegrationError


def snapshot():
    return {"protocolVersion": 1, "operation": "appointment", "runId": "appointment-protocol-test", "action": "recommend",
            "organizerId": 1, "professorIds": [2], "invitedIds": [], "unresolvedIds": [], "durationMinutes": 30,
            "horizon": {"start": 1800000000, "end": 1800086400},
            "published": [{"userId": 2, "start": 1800000000, "end": 1800010800}], "busy": []}


class AppointmentProtocolTests(TestCase):
    def setUp(self):
        self.gateway = EngineGateway(ROOT)

    def test_real_protocol_rejects_invalid_version_identifiers_intervals_and_shapes(self):
        backend = resolve_backend_executable(ROOT)
        examples = [{"protocolVersion": 2}, {"professorIds": []}, {"organizerId": -1}, {"durationMinutes": True},
                    {"professorIds": [2, 2]}, {"invitedIds": [1]}, {"action": "unknown"},
                    {"busy": [{"userId": 2, "start": 100, "end": 10}]}, {"unresolvedIds": [999]},
                    {"horizon": {"start": 100, "end": 4102444800}}, {"published": "invalid"}, {"runId": ""}]
        examples.append({"protocolVersion": None})
        for changes in examples:
            with self.subTest(changes=changes):
                completed = subprocess.run([str(backend.path), "--appointments-json"], input=json.dumps(snapshot() | changes),
                                           encoding="utf-8", capture_output=True, timeout=10)
                self.assertEqual(completed.returncode, 2)
                self.assertEqual(json.loads(completed.stdout)["status"], "error")
                self.assertTrue(completed.stderr)

    def test_real_protocol_accepts_manual_non_grid_times_and_empty_optional_participants(self):
        value = snapshot() | {"action": "validate", "proposed": {"start": 1800000060, "end": 1800001860}}
        result, build = self.gateway.execute_appointment(value)
        self.assertTrue(result["feasible"])
        self.assertEqual(result["recommendations"][0]["start"], 1800000060)
        self.assertTrue(build["source_sha256"])

    def test_gateway_rejects_malformed_or_mismatched_appointment_output(self):
        result, _ = self.gateway.execute_appointment(snapshot())
        for changes in ({"runId": "different"}, {"protocolVersion": 2}, {"operation": "allocation"},
                        {"feasible": "true"}, {"recommendations": {}}, {"reasonCode": "invented"}, {"status": "error"}):
            with self.subTest(changes=changes), mock.patch("web.engine_gateway.subprocess.run", return_value=
                    subprocess.CompletedProcess([], 0, json.dumps(result | changes), "")):
                with self.assertRaises(EngineIntegrationError):
                    self.gateway.execute_appointment(snapshot())
        with mock.patch("web.engine_gateway.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "not JSON", "")):
            with self.assertRaises(EngineIntegrationError):
                self.gateway.execute_appointment(snapshot())

    def test_gateway_timeout_and_nonzero_exit_cannot_be_accepted(self):
        with mock.patch("web.engine_gateway.subprocess.run", side_effect=subprocess.TimeoutExpired([], 30)):
            with self.assertRaisesRegex(EngineIntegrationError, "timed out"):
                self.gateway.execute_appointment(snapshot())
        with mock.patch("web.engine_gateway.subprocess.run", return_value=subprocess.CompletedProcess([], 2, '{"errors":[]}', "failure")):
            with self.assertRaisesRegex(EngineIntegrationError, "exit code 2"):
                self.gateway.execute_appointment(snapshot())

    def test_result_invitee_partition_and_duration_are_verified(self):
        result, _ = self.gateway.execute_appointment(snapshot())
        bad = copy.deepcopy(result)
        bad["recommendations"][0]["availableInvitees"] = [999]
        for invalid in (bad, copy.deepcopy(result)):
            if invalid is not bad:
                invalid["recommendations"][0]["end"] += 60
            with mock.patch("web.engine_gateway.subprocess.run", return_value=subprocess.CompletedProcess([], 0, json.dumps(invalid), "")):
                with self.assertRaises(EngineIntegrationError):
                    self.gateway.execute_appointment(snapshot())
