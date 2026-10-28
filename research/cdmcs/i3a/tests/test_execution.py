import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from research.cdmcs.i3a.adapter import cdmcs_request, normalize
from research.cdmcs.i3a.comparison import compare
from research.cdmcs.i3a.execution import ERROR, UNSUPPORTED, OfflineEngines, invoke, validate_cdmcs
from web.backend_executable import BackendExecutableError
from research.cdmcs.i3a.fixtures import basic
from research.cdmcs.i3a.__main__ import export, external_destination, main
from research.cdmcs.i3a.snapshot import parse_snapshot


class StubEngines:
    """Control-flow mock, not evidence of native engine feasibility."""
    def __init__(self, production="infeasible", cdmcs="infeasible"):
        self.states = {"production": production, "cdmcs": cdmcs}

    def execute(self, engine, request):
        return {"classification": self.states[engine], "request": request, "stdout": "mock",
                "stderr": "", "exit_code": 0, "timings_ns": {"total": 1}}


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.request = cdmcs_request(normalize(parse_snapshot(basic())))

    def test_malformed_nonzero_and_nonfinite_outputs_are_errors(self):
        for code, stdout in ((0, b"garbage"), (2, b'{"status":"INVALID_INPUT"}'),
                             (0, b'{"x":1,"x":2}'), (0, b'{"x":NaN}'), (0, b"\xff")):
            with self.subTest(code=code, stdout=stdout), mock.patch("subprocess.Popen") as launch:
                process = launch.return_value.__enter__.return_value
                process.communicate.return_value = (stdout, b"diagnostic")
                process.returncode = code
                result = invoke(["mock-binary"], self.request, ".", 1, "cdmcs")
                self.assertEqual(result["classification"], ERROR)
                self.assertIsNotNone(result["error"])
                self.assertEqual(result["stderr"], "diagnostic")
                if stdout == b"\xff":
                    self.assertEqual(result["stdout_base64"], "/w==")

    def test_timeout_kills_and_reaps_process_and_preserves_output(self):
        with mock.patch("subprocess.Popen") as launch:
            process = launch.return_value.__enter__.return_value
            process.communicate.side_effect = [subprocess.TimeoutExpired("mock", 1), (b"partial", b"timeout diagnostic")]
            process.returncode = -9
            result = invoke(["mock"], self.request, ".", 1, "cdmcs")
            process.kill.assert_called_once()
            self.assertEqual(process.communicate.call_count, 2)
            self.assertEqual(result["classification"], ERROR)
            self.assertEqual(result["stdout"], "partial")

    def test_executable_missing_hash_and_freshness_failures_do_not_fall_back(self):
        with mock.patch("research.cdmcs.i3a.execution.resolve_backend_executable",
                        side_effect=BackendExecutableError("Backend is stale")):
            with self.assertRaisesRegex(ValueError, "stale"):
                OfflineEngines("missing", "0" * 64)
        with mock.patch("research.cdmcs.i3a.execution.resolve_backend_executable"):
            with self.assertRaisesRegex(ValueError, "missing"):
                OfflineEngines("nonexistent-i3a-engine", "0" * 64)
            with tempfile.TemporaryDirectory(prefix="i3a-pin-test-") as temporary:
                file = Path(temporary) / "engine"
                file.write_bytes(b"synthetic non-executed binary bytes")
                file.chmod(0o700)
                with self.assertRaisesRegex(ValueError, "SHA-256"):
                    OfflineEngines(file, "0" * 64)

    def test_counts_permissions_and_arithmetic_shapes_are_checked(self):
        result = {"operation": "cdmcs_schedule_v1", "model": "V15_restricted_one_blocking_move",
                  "status": "NO_FEASIBLE_PROPOSAL", "solutions_evaluated": 0,
                  "returned_count": 0, "truncated": False, "recommendations": []}
        self.assertEqual(validate_cdmcs(result, self.request), "infeasible")
        for changes in ({"status": "OK"}, {"solutions_evaluated": True}, {"truncated": 0},
                        {"returned_count": 1}, {"model": "different"}):
            with self.assertRaises(ValueError):
                validate_cdmcs(result | changes, self.request)
        self.assertEqual(validate_cdmcs(result | {"status": "UNRESOLVED_CALENDAR"}, self.request), UNSUPPORTED)

    def test_complete_comparison_does_not_confuse_errors_with_infeasibility(self):
        for state in (ERROR, UNSUPPORTED):
            report = compare(basic(), StubEngines(state, state), ranking=False)
            self.assertEqual(report["status"], state)
            self.assertFalse(report["complete"])
            self.assertIsNone(report["feasible_set_equal"])
            self.assertEqual(len(report["calls"]), 2, "An integration error must halt further candidate launches")

    def test_discrepancies_keep_both_requests_and_raw_results(self):
        report = compare(basic(), StubEngines("feasible", "infeasible"), ranking=False)
        self.assertEqual(report["status"], "discrepancy")
        self.assertEqual(len(report["discrepancies"]), 11)
        self.assertEqual(len(report["calls"]), 22)
        self.assertIn("input", report)
        self.assertTrue(all(row["request"] and row["stdout"] for row in report["calls"]))

    def test_unsupported_and_invalid_snapshots_do_not_invoke_engines(self):
        engines = mock.Mock()
        value = basic()
        value["required_resources"] = ["resource"]
        self.assertEqual(compare(value, engines)["status"], UNSUPPORTED)
        self.assertEqual(compare([], engines)["status"], ERROR)
        engines.execute.assert_not_called()

    def test_repetition_limits_and_empty_grid_are_explicit(self):
        self.assertEqual(compare(basic(), StubEngines(), repetitions=100)["status"], ERROR)
        value = basic()
        value["participants"][1]["published"] = []
        engines = mock.Mock()
        report = compare(value, engines)
        self.assertEqual(report["status"], "equal")
        self.assertEqual(report["candidate_count"], 0)
        self.assertEqual(report["calls"], [])
        engines.execute.assert_not_called()

    def test_evidence_is_exclusive_and_outside_checkout(self):
        with self.assertRaises(ValueError):
            external_destination(Path.cwd() / "build" / "forbidden-evidence")
        with tempfile.TemporaryDirectory(prefix="i3a-evidence-test-") as temporary:
            target = Path(temporary) / "new"
            report = compare(basic(), StubEngines(), ranking=False)
            summary = export(target, [report], {"fixture": "mock only"}, ["unit-test"])
            self.assertEqual(summary["cases"][0]["status"], "equal")
            self.assertTrue((target / "provenance.json").is_file())
            self.assertEqual(json.loads((target / "case-000.json").read_text())["input"], basic())
            with self.assertRaises(ValueError):
                export(target, [report], {}, [])

    def test_non_synthetic_input_is_not_executed_or_exported(self):
        with tempfile.TemporaryDirectory(prefix="i3a-input-test-") as temporary:
            source, target = Path(temporary) / "input.json", Path(temporary) / "evidence"
            source.write_text(json.dumps(basic() | {"synthetic": False}), encoding="utf-8")
            args = ["i3a", "--input", str(source), "--output", str(target),
                    "--cdmcs", "not-invoked", "--cdmcs-sha256", "0" * 64]
            with mock.patch("sys.argv", args), mock.patch("sys.stderr"), \
                    mock.patch("research.cdmcs.i3a.__main__.OfflineEngines") as engine:
                self.assertEqual(main(), 2)
                engine.assert_not_called()
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
