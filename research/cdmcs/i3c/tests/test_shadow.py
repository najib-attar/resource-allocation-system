"""Synthetic admission, bounded process transport and sanitized orchestration."""

from dataclasses import asdict, replace
import json
from pathlib import Path
import subprocess
import sys
import threading
import traceback
import unittest
from types import SimpleNamespace
from unittest import mock

from research.cdmcs.i3a.adapter import cdmcs_request, normalize, production_request, _normalize_fixed_calendar
from research.cdmcs.i3a.fixtures import basic, participant
from research.cdmcs.i3a.snapshot import Interval, Preference, parse_snapshot
from research.cdmcs.i3a.__main__ import export
from research.cdmcs.i3b.projection import CalendarProjection
from research.cdmcs.i3c.admission import (AdmissionError, admitted_snapshot, synthetic_fixture,
                                         synthetic_projection)
from research.cdmcs.i3c.process import ProcessFailure, ProcessResult, execute
from research.cdmcs.i3c.runner import Budget, ShadowRunner
from research.cdmcs.i3c.serialization import candidate_requests
from web.backend_executable import file_sha256


def database_projection():
    snapshot = parse_snapshot(basic())
    snapshot = replace(snapshot, origin="authorized_calendar", participants=tuple(
        replace(p, preference=None) for p in snapshot.participants))
    return CalendarProjection(snapshot, 1)


def response(request, feasible=True):
    row = {"start_minute": request["candidate_starts"][0],
           "end_minute": request["candidate_starts"][0] + request["duration"],
           "total_cost": 0, "fairness_max_burden": 0, "moved_meeting_id": None,
           "replacement_start_minute": None, "proposal_status": "DIRECT_PENDING_NORMAL_MEETING_APPROVAL",
           "required_permissions": {key: [] for key in ("new_meeting_extra_availability",
                "relocated_meeting_extra_availability", "relocation_participant_approval")}}
    return {"operation": "cdmcs_schedule_v1", "model": "V15_restricted_one_blocking_move",
            "status": "OK" if feasible else "NO_FEASIBLE_PROPOSAL", "solutions_evaluated": int(feasible),
            "returned_count": int(feasible), "recommendations": [row] if feasible else [], "truncated": False}


def production_response(request):
    return {"protocolVersion": 1, "operation": "appointment", "runId": request["runId"],
            "status": "success", "engineVersion": "synthetic", "errors": [], "feasible": True,
            "reasonCode": "AVAILABLE", "recommendations": [{**request["proposed"], "reason": "synthetic",
                "preferenceDistanceSeconds": 0, "availableInvitees": request["invitedIds"],
                "unavailableInvitees": [], "unresolvedInvitees": []}]}


class AdmissionTests(unittest.TestCase):
    def test_fixture_is_immutable_role_independent_and_repr_private(self):
        value = basic()
        value["participants"][0]["role_label"] = "committee organizer"
        admitted = synthetic_fixture(value)
        snapshot = admitted_snapshot(admitted)
        self.assertEqual(snapshot.participants[0].role_label, "committee organizer")
        self.assertNotIn("professor-A", repr(admitted))
        with self.assertRaises(AttributeError):
            admitted._snapshot = snapshot

    def test_non_synthetic_or_malformed_fixture_errors_are_sanitized(self):
        for key, bad in (("synthetic", False), ("timezone", "PRIVATE-MARKER"), ("snapshot_version", 2)):
            value = basic()
            value[key] = bad
            with self.assertRaises(AdmissionError) as caught:
                synthetic_fixture(value)
            self.assertNotIn("PRIVATE-MARKER", "".join(traceback.format_exception(caught.exception)))

    def test_raw_snapshot_and_tampered_scope_are_rejected(self):
        value = synthetic_fixture(basic())
        for invalid in (admitted_snapshot(value), replace(value, _seal=None),
                        replace(value, _snapshot=None, _bound=None),
                        replace(value, _snapshot=replace(admitted_snapshot(value), explicit_starts=(0,)))):
            with self.assertRaises(AdmissionError):
                admitted_snapshot(invalid)

    def test_projection_needs_explicit_disposable_fixture_declaration(self):
        for flag in (False, None, 1, "true"):
            with self.assertRaises(AdmissionError):
                synthetic_projection(database_projection(), disposable_fixture=flag)

    def test_missing_preferences_remain_missing(self):
        value = synthetic_projection(database_projection(), disposable_fixture=True)
        self.assertTrue(all(p.preference is None for p in admitted_snapshot(value).participants))
        result = ShadowRunner(enabled=True).run(value)
        self.assertEqual(result.status, "unsupported")

    def test_explicit_synthetic_preferences_preserve_origin_horizon_and_scope(self):
        projection = database_projection()
        snapshot = projection.internal_snapshot()
        pref = Preference(1, (), 0, 0, 0, "synthetic-explicit-test")
        value = synthetic_projection(projection, disposable_fixture=True,
            preferences=tuple((p.id, pref) for p in snapshot.participants))
        admitted = admitted_snapshot(value)
        self.assertEqual(admitted.origin, "authorized_calendar")
        self.assertEqual(admitted.horizon, snapshot.horizon)
        self.assertEqual(admitted.explicit_starts, snapshot.explicit_starts)
        normalized = _normalize_fixed_calendar(admitted)
        self.assertFalse(normalized.unsupported)
        # Even internal normalization never opens the public synthetic serializers.
        for fn in (cdmcs_request, production_request):
            with self.assertRaises(ValueError):
                fn(normalized)
        self.assertTrue(normalize(admitted).unsupported)
        self.assertEqual(normalize(admitted).prefixes, ())
        with self.assertRaises(ValueError):
            export("unused", [{"input": asdict(admitted)}], {}, [])

    def test_invalid_or_invented_projection_preferences_are_rejected(self):
        projection = database_projection()
        key = projection.internal_snapshot().organizer
        for prefs in ((("unknown", Preference(0, (), 0, 0, 0, "synthetic-test")),),
                      ((key, Preference(-1, (), 0, 0, 0, "synthetic-test")),),
                      ((key, Preference(0, (), 0, 0, 0, "invented-user-policy")),)):
            with self.assertRaises(AdmissionError):
                synthetic_projection(projection, disposable_fixture=True, preferences=prefs)

    def test_internal_serializer_binds_scope_and_exact_candidate(self):
        value = synthetic_fixture(basic())
        normalized = _normalize_fixed_calendar(admitted_snapshot(value))
        other = synthetic_fixture(basic())
        for scope, candidate in ((other, normalized.candidates[0]), (value, 0)):
            with self.assertRaises(ValueError):
                candidate_requests(scope, normalized, candidate, True)
        requests = candidate_requests(value, normalized, normalized.candidates[0], True)
        self.assertEqual(requests[0][2]["candidate_starts"], [0])
        self.assertEqual(requests[1][2]["proposed"]["start"], normalized.candidates[0])

    def test_malformed_projection_and_mutable_preference_bands_fail_closed(self):
        with self.assertRaises(AdmissionError):
            synthetic_projection(CalendarProjection(None, 1), disposable_fixture=True)
        projection = database_projection()
        snapshot = projection.internal_snapshot()
        mutable = Preference(0, ([Interval(snapshot.anchor, snapshot.horizon.end), 0],),
                             0, 0, 0, "synthetic-test")
        with self.assertRaises(AdmissionError):
            synthetic_projection(projection, disposable_fixture=True, preferences=((snapshot.organizer, mutable),))


class ProcessTests(unittest.TestCase):
    def call(self, script, timeout=2, **kwargs):
        # Windows venv python.exe is a launcher that spawns another process; the
        # one-process Job Object deliberately forbids that. Test the real interpreter.
        return execute([sys._base_executable, "-B", "-c", script], {"synthetic": True}, timeout=timeout,
            memory_bytes=128 * 1024**2, input_limit=1024, output_limit=4096, **kwargs)

    def test_valid_json_and_bounded_stderr_are_not_returned_or_logged(self):
        with self.assertNoLogs():
            result = self.call("import sys; sys.stdin.read(); sys.stderr.write('PRIVATE-MARKER'); print('{}')")
        self.assertEqual(result.payload, {})
        self.assertNotIn("PRIVATE", repr(result))
        self.assertGreater(result.launch_ns, 0)

    def test_timeout_reaps_child_and_drains_pipes(self):
        launched = []
        original = subprocess.Popen
        def capture(*args, **kwargs):
            child = original(*args, **kwargs)
            launched.append(child)
            return child
        with mock.patch("research.cdmcs.i3c.process.subprocess.Popen", side_effect=capture):
            with self.assertRaises(ProcessFailure) as caught:
                self.call("import sys,time; sys.stdin.read(); time.sleep(30)", timeout=0.15)
        self.assertEqual(caught.exception.code, "TIMEOUT")
        self.assertIsNotNone(launched[0].poll())
        self.assertTrue(all(pipe.closed for pipe in (launched[0].stdin, launched[0].stdout, launched[0].stderr)))

    def test_crash_is_not_infeasibility(self):
        with self.assertRaises(ProcessFailure) as caught:
            self.call("import sys; sys.stdin.read(); sys.exit(9)")
        self.assertEqual(caught.exception.code, "ENGINE_EXIT")

    def test_malformed_duplicate_nonfinite_and_nonobject_output_are_rejected(self):
        for output in ("PRIVATE-MARKER", '{"x":1,"x":2}', '{"x":NaN}', '[]', '{}{}'):
            with self.subTest(output=output), self.assertRaises(ProcessFailure) as caught:
                self.call("import sys; sys.stdin.read(); print(" + repr(output) + ")")
            self.assertEqual(caught.exception.code, "MALFORMED_RESPONSE")
            self.assertNotIn("PRIVATE-MARKER", "".join(traceback.format_exception(caught.exception)))

    def test_stdout_and_stderr_floods_are_bounded(self):
        for stream in ("stdout", "stderr"):
            with self.assertRaises(ProcessFailure) as caught:
                self.call(f"import sys; sys.stdin.read(); sys.{stream}.write('X'*100000)")
            self.assertEqual(caught.exception.code, "OUTPUT_LIMIT")

    def test_resource_exhaustion_is_isolated(self):
        # One GiB cannot fit inside the 128 MiB child limit; parent stays bounded.
        with self.assertRaises(ProcessFailure) as caught:
            self.call("import sys; sys.stdin.read(); x=bytearray(1024**3); print('{}')")
        self.assertEqual(caught.exception.code, "ENGINE_EXIT")

    def test_limit_setup_failure_reaps_process(self):
        with mock.patch("research.cdmcs.i3c.process._limits", side_effect=OSError("PRIVATE-MARKER")):
            with self.assertRaises(ProcessFailure) as caught:
                self.call("import sys; sys.stdin.read(); print('{}')")
        self.assertNotIn("PRIVATE-MARKER", "".join(traceback.format_exception(caught.exception)))

    def test_input_limit_prevents_launch(self):
        with mock.patch("research.cdmcs.i3c.process.subprocess.Popen") as spawn:
            with self.assertRaises(ProcessFailure):
                execute([], {"raw": "x" * 2000}, timeout=1, memory_bytes=128*1024**2,
                        input_limit=1024, output_limit=4096)
            spawn.assert_not_called()


class RunnerTests(unittest.TestCase):
    def setUp(self):
        patch = mock.patch("research.cdmcs.i3c.runner.resolve_backend_executable", return_value=
            SimpleNamespace(path=Path(sys.executable), metadata={"binary_sha256": file_sha256(sys.executable)}))
        patch.start()
        self.addCleanup(patch.stop)

    def runner(self, **kwargs):
        return ShadowRunner(sys.executable, file_sha256(sys.executable), enabled=True, **kwargs)

    def test_disabled_by_default_never_reads_or_launches(self):
        with mock.patch("research.cdmcs.i3c.runner.admitted_snapshot") as read:
            self.assertEqual(ShadowRunner().run(None).status, "disabled")
            read.assert_not_called()

    def test_excessive_or_invalid_budgets_rejected(self):
        with self.assertRaises(ValueError):
            ShadowRunner(budget=False)
        for kwargs in ({"candidates": 257}, {"total_seconds": float('nan')},
                       {"memory_bytes": 0}, {"per_process_seconds": True}):
            with self.assertRaises(ValueError):
                Budget(**kwargs)

    def test_unauthorized_raw_input_rejected_without_launch(self):
        with mock.patch("research.cdmcs.i3c.runner.execute") as spawn:
            self.assertEqual(self.runner().run(parse_snapshot(basic())).status, "input_error")
            spawn.assert_not_called()

    def test_unresolved_capabilities_and_resources_never_launch(self):
        cases = []
        value = basic()
        value["participants"][1]["calendar_state"] = "unresolved"
        cases.append(value)
        value = basic()
        value["required_resources"] = ["room"]
        cases.append(value)
        value = basic()
        value["unsupported_information"] = ["relocation"]
        cases.append(value)
        for value in cases:
            with mock.patch("research.cdmcs.i3c.runner.execute") as spawn:
                self.assertEqual(self.runner().run(synthetic_fixture(value)).status, "unsupported")
                spawn.assert_not_called()

    def test_optional_unresolved_is_nonblocking(self):
        value = basic()
        value["participants"].append(participant("optional", required=False, published_required=False))
        value["participants"][-1]["calendar_state"] = "unresolved"
        def success(command, request, **kwargs):
            self.assertNotIn("optional", request["required_people"])
            return ProcessResult(response(request), 1, 2)
        with mock.patch("research.cdmcs.i3c.runner.execute", side_effect=success):
            result = self.runner().run(synthetic_fixture(value), compare=False)
        self.assertEqual(result.status, "cdmcs_only")
        self.assertEqual(result.cdmcs_feasible, 11)

    def test_pre_normalization_allocation_budget(self):
        value = basic()
        value["participants"].extend(participant("extra-" + str(i)) for i in range(31))
        with mock.patch("research.cdmcs.i3c.runner._normalize_fixed_calendar") as normalize_facts:
            result = self.runner().run(synthetic_fixture(value))
            self.assertEqual(result.code, "NORMALIZATION_BUDGET")
            normalize_facts.assert_not_called()

    def test_discrepancies_are_reported_not_hidden_as_infeasible(self):
        def different(command, request, **kwargs):
            payload = production_response(request) if request.get("operation") == "appointment" else response(request, False)
            return ProcessResult(payload, 1, 2)
        with mock.patch("research.cdmcs.i3c.runner.execute", side_effect=different):
            result = self.runner().run(synthetic_fixture(basic()))
        self.assertEqual(result.status, "discrepancy")
        self.assertEqual(result.discrepancies, 11)
        self.assertTrue(result.complete)

    def test_production_correlation_mismatch_is_engine_failure(self):
        def invalid(command, request, **kwargs):
            if request.get("operation") == "appointment":
                payload = production_response(request)
                payload["runId"] = "PRIVATE-INVALID-ID"
            else:
                payload = response(request)
            return ProcessResult(payload, 1, 2)
        with mock.patch("research.cdmcs.i3c.runner.execute", side_effect=invalid):
            result = self.runner().run(synthetic_fixture(basic()))
        self.assertEqual(result.code, "INVALID_PROTOCOL")
        self.assertNotIn("PRIVATE", repr(result))

    def test_failure_after_partial_evaluation_never_returns_partial_success(self):
        calls = []
        def fail_later(command, request, **kwargs):
            calls.append(request)
            if len(calls) > 1:
                raise ProcessFailure("ENGINE_EXIT")
            return ProcessResult(response(request), 1, 2)
        with mock.patch("research.cdmcs.i3c.runner.execute", side_effect=fail_later):
            result = self.runner().run(synthetic_fixture(basic()), compare=False)
        self.assertEqual(result.status, "engine_failure")
        self.assertFalse(result.complete)
        self.assertEqual((result.evaluated, result.cdmcs_feasible), (0, 0))

    def test_candidate_limit_does_not_truncate_universe(self):
        with mock.patch("research.cdmcs.i3c.runner.execute") as spawn:
            result = self.runner(budget=Budget(candidates=1)).run(synthetic_fixture(basic()))
            self.assertEqual(result.code, "CANDIDATE_BUDGET")
            self.assertFalse(result.complete)
            spawn.assert_not_called()

    def test_pending_extra_permission_or_relocation_is_not_accepted(self):
        for field, bad in (("moved_meeting_id", "NEW"), ("proposal_status", "CONDITIONAL_PENDING_APPROVAL")):
            def corrupt(command, request, **kwargs):
                payload = response(request)
                payload["recommendations"][0][field] = bad
                return ProcessResult(payload, 1, 2)
            with mock.patch("research.cdmcs.i3c.runner.execute", side_effect=corrupt):
                result = self.runner().run(synthetic_fixture(basic()), compare=False)
            self.assertEqual(result.code, "INVALID_PROTOCOL")
            self.assertFalse(result.complete)

    def test_failure_output_contains_no_partial_feasible_results_or_calendar_data(self):
        with mock.patch("research.cdmcs.i3c.runner.execute", side_effect=ProcessFailure("TIMEOUT")):
            with self.assertNoLogs():
                result = self.runner().run(synthetic_fixture(basic()), compare=False)
        self.assertEqual(result.status, "engine_failure")
        self.assertEqual(result.evaluated, 0)
        raw = json.dumps(asdict(result))
        for marker in ("professor-A", "2030", "published", "rate_prefix", "PRIVATE"):
            self.assertNotIn(marker, raw)

    def test_concurrency_admission_is_process_wide_and_nonblocking(self):
        entered, release = threading.Event(), threading.Event()
        def wait(command, request, **kwargs):
            entered.set()
            release.wait(3)
            return ProcessResult(response(request), 1, 2)
        value = synthetic_fixture(basic())
        with mock.patch("research.cdmcs.i3c.runner.execute", side_effect=wait):
            thread = threading.Thread(target=lambda: self.runner().run(value, compare=False))
            thread.start()
            try:
                self.assertTrue(entered.wait(2))
                self.assertEqual(self.runner().run(value).status, "busy")
            finally:
                release.set()
                thread.join(5)
        self.assertFalse(thread.is_alive())

    def test_run_deadline_fails_closed(self):
        with mock.patch("research.cdmcs.i3c.runner.monotonic", side_effect=(0, 121)):
            self.assertEqual(self.runner().run(synthetic_fixture(basic()), compare=False).code, "RUN_DEADLINE")


if __name__ == "__main__":
    unittest.main()
