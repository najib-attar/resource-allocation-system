"""Actual pinned C++ subprocesses, never live calendars."""

from dataclasses import asdict
import os
import unittest

from research.cdmcs.i3a.fixtures import expected_status, matrix
from research.cdmcs.i3c.admission import AdmissionError, synthetic_fixture
from research.cdmcs.i3c.runner import ShadowRunner


def native_runner(**kwargs):
    return ShadowRunner(os.environ["CDMCS_I3A_BINARY"], os.environ["CDMCS_I3A_SHA256"],
                        production_path=os.environ.get("CDMCS_I3A_PRODUCTION"), enabled=True, **kwargs)


@unittest.skipUnless(os.environ.get("CDMCS_I3A_BINARY") and os.environ.get("CDMCS_I3A_SHA256"),
                     "Explicit native engine path and SHA-256 required")
class NativeShadowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = native_runner()
        cls.results = {}
        for value in matrix():
            try:
                result = cls.runner.run(synthetic_fixture(value))
            except AdmissionError:
                result = None
            cls.results[value["snapshot_id"]] = result

    def test_complete_existing_matrix_through_separate_internal_transport(self):
        for value in matrix():
            result = self.results[value["snapshot_id"]]
            with self.subTest(case=value["snapshot_id"]):
                expected = expected_status(value)
                if expected == "input_engine_error":
                    self.assertIsNone(result)
                elif expected == "unsupported_comparison":
                    self.assertEqual(result.status, "unsupported")
                    self.assertFalse(result.complete)
                else:
                    self.assertEqual(result.status, "match", result)
                    self.assertTrue(result.complete)
                    self.assertEqual(result.candidates, result.evaluated)
                    self.assertEqual(result.discrepancies, 0)

    def test_counts_and_over_100_feasible_candidates_are_not_top_k(self):
        supported = [r for r in self.results.values() if r and r.status == "match"]
        self.assertEqual(len(supported), 41)
        self.assertEqual(sum(r.candidates for r in supported), 469)
        self.assertEqual(sum(r.cdmcs_feasible for r in supported), 391)
        self.assertEqual(sum(r.production_feasible for r in supported), 391)
        large = self.results["synthetic-over-100-feasible-weekday-boundary"]
        self.assertEqual((large.evaluated, large.cdmcs_feasible), (191, 191))

    def test_repeated_results_are_deterministic_ignoring_wall_times(self):
        value = matrix()[1]
        expected = asdict(self.results[value["snapshot_id"]])
        for _ in range(2):
            actual = asdict(self.runner.run(synthetic_fixture(value)))
            for record in (actual, expected):
                record.pop("launch_ns", None)
                record.pop("exchange_ns", None)
            self.assertEqual(actual, expected)

    def test_cdmcs_only_does_not_resolve_or_launch_production(self):
        value = matrix()[0]
        runner = ShadowRunner(os.environ["CDMCS_I3A_BINARY"], os.environ["CDMCS_I3A_SHA256"],
                              enabled=True, production_path="not-a-backend")
        result = runner.run(synthetic_fixture(value), compare=False)
        self.assertEqual(result.status, "cdmcs_only")
        self.assertEqual(result.cdmcs_feasible, 11)

    def test_missing_and_stale_executables_are_sanitized(self):
        value = synthetic_fixture(matrix()[0])
        for runner in (ShadowRunner("PRIVATE-PATH", "0"*64, enabled=True),
                       ShadowRunner(os.environ["CDMCS_I3A_BINARY"], "0"*64, enabled=True),
                       ShadowRunner(os.environ["CDMCS_I3A_BINARY"], os.environ["CDMCS_I3A_SHA256"],
                                    enabled=True, production_path="PRIVATE-PATH")):
            result = runner.run(value)
            self.assertEqual(result.status, "input_error")
            self.assertNotIn("PRIVATE", repr(result))


if __name__ == "__main__":
    unittest.main()
