"""Independent regressions for release-review failure boundaries."""

from contextlib import redirect_stderr
import io
from pathlib import Path
import subprocess
import sys
import threading
import traceback
from types import SimpleNamespace
import unittest
from unittest import mock

from research.cdmcs.i3a.fixtures import basic
from research.cdmcs.i3c.admission import synthetic_fixture
from research.cdmcs.i3c.process import ProcessFailure, ProcessResult, execute
from research.cdmcs.i3c.runner import ShadowRunner
from research.cdmcs.i3c import benchmark
from research.cdmcs.i3c.tests.test_shadow import response, production_response
from web.backend_executable import file_sha256


class ReleaseFailureTests(unittest.TestCase):
    def test_benchmark_fixtures_have_explicit_bounded_identical_candidate_grids(self):
        from research.cdmcs.i3c.admission import admitted_snapshot
        for count in (1, 8, 32, 128):
            snapshot = admitted_snapshot(benchmark.fixture(count))
            self.assertEqual(snapshot.origin, "synthetic")
            self.assertEqual(len(snapshot.explicit_starts), count)
            self.assertEqual(snapshot.explicit_starts, tuple(snapshot.anchor + 900 * i for i in range(count)))
            self.assertEqual(snapshot.horizon.end, snapshot.explicit_starts[-1] + 1800)

    def test_benchmark_cli_rejects_excessive_work_before_launching(self):
        command = ["benchmark", "--cdmcs", "synthetic-unused", "--cdmcs-sha256", "0" * 64,
                   "--production", "synthetic-unused", "--candidates", "257"]
        with mock.patch.object(sys, "argv", command), redirect_stderr(io.StringIO()), \
             mock.patch.object(benchmark, "ShadowRunner") as construct:
            with self.assertRaises(SystemExit) as caught:
                benchmark.main()
            self.assertEqual(caught.exception.code, 2)
            construct.assert_not_called()

    def test_each_launch_rehashes_its_own_executable_without_rehashing_the_peer(self):
        digest = file_sha256(sys.executable)
        production = SimpleNamespace(path=Path(sys.executable), metadata={"binary_sha256": digest})
        def success(command, request, **kwargs):
            return ProcessResult(production_response(request) if request["operation"] == "appointment"
                                 else response(request), 1, 2)
        runner = ShadowRunner(sys.executable, digest, enabled=True)
        with mock.patch("research.cdmcs.i3c.runner.resolve_backend_executable", return_value=production), \
             mock.patch("research.cdmcs.i3c.runner.file_sha256", wraps=file_sha256) as hashing, \
             mock.patch("research.cdmcs.i3c.runner.execute", side_effect=success) as calls:
            result = runner.run(synthetic_fixture(basic()))
        self.assertEqual(result.status, "match")
        self.assertEqual(calls.call_count, 22)
        self.assertEqual(hashing.call_count, 1 + calls.call_count)

    def test_changed_executable_between_paired_calls_still_fails_closed(self):
        digest = file_sha256(sys.executable)
        production = SimpleNamespace(path=Path(sys.executable), metadata={"binary_sha256": digest})
        def success(command, request, **kwargs):
            return ProcessResult(response(request), 1, 2)
        runner = ShadowRunner(sys.executable, digest, enabled=True)
        with mock.patch("research.cdmcs.i3c.runner.resolve_backend_executable", return_value=production), \
             mock.patch("research.cdmcs.i3c.runner.file_sha256", side_effect=(digest, digest, "0" * 64)), \
             mock.patch("research.cdmcs.i3c.runner.execute", side_effect=success) as calls:
            result = runner.run(synthetic_fixture(basic()))
        self.assertEqual(result.code, "EXECUTABLE_CHANGED")
        self.assertEqual(calls.call_count, 1)
        self.assertFalse(result.complete)

    def test_io_thread_start_failure_is_sanitized_and_reaps_every_child(self):
        for failing_start in (1, 2, 3):
            children = []
            original_spawn, original_start = subprocess.Popen, threading.Thread.start
            count = 0

            def spawn(*args, **kwargs):
                child = original_spawn(*args, **kwargs)
                children.append(child)
                return child

            def start(thread):
                nonlocal count
                count += 1
                if count == failing_start:
                    raise RuntimeError("PRIVATE-SYNTHETIC-THREAD-MARKER")
                return original_start(thread)

            with self.subTest(failing_start=failing_start):
                with mock.patch("research.cdmcs.i3c.process.subprocess.Popen", side_effect=spawn), \
                     mock.patch("research.cdmcs.i3c.process.threading.Thread.start", new=start):
                    with self.assertRaises(ProcessFailure) as caught:
                        execute([sys._base_executable, "-B", "-c", "import sys; sys.stdin.read(); print('{}')"],
                            {"synthetic": True}, timeout=2, memory_bytes=128*1024**2,
                            input_limit=1024, output_limit=4096)
                self.assertEqual(caught.exception.code, "THREAD_START")
                self.assertNotIn("PRIVATE-SYNTHETIC", "".join(traceback.format_exception(caught.exception)))
                self.assertEqual(len(children), 1)
                self.assertIsNotNone(children[0].poll())
                self.assertTrue(all(p.closed for p in (children[0].stdin, children[0].stdout, children[0].stderr)))

    def test_empty_candidate_universe_still_enforces_total_deadline(self):
        value = basic()
        value["candidates"] = {"mode": "explicit", "anchor_participant": "professor-A", "starts": []}
        runner = ShadowRunner(sys.executable, file_sha256(sys.executable), enabled=True)
        with mock.patch("research.cdmcs.i3c.runner.monotonic", side_effect=(0, 121)):
            result = runner.run(synthetic_fixture(value), compare=False)
        self.assertEqual((result.status, result.code), ("engine_failure", "RUN_DEADLINE"))
        self.assertFalse(result.complete)


if __name__ == "__main__":
    unittest.main()
