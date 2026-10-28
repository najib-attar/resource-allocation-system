"""Real C++ processes, only when an explicit I1 executable/hash is provided."""

import json
import os
from pathlib import Path
import unittest

from research.cdmcs.i3a.comparison import compare
from research.cdmcs.i3a.execution import OfflineEngines
from research.cdmcs.i3a.fixtures import expected_status, matrix
from research.cdmcs.i3a.snapshot import parse_snapshot


@unittest.skipUnless(os.environ.get("CDMCS_I3A_BINARY") and os.environ.get("CDMCS_I3A_SHA256"),
                     "Explicit CDMCS_I3A_BINARY and CDMCS_I3A_SHA256 required for native comparisons")
class NativeComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.owner = OfflineEngines(os.environ["CDMCS_I3A_BINARY"], os.environ["CDMCS_I3A_SHA256"])
        cls.engines = cls.owner.__enter__()
        cls.addClassCleanup(cls.owner.__exit__, None, None, None)
        cls.reports = {value["snapshot_id"]: compare(value, cls.engines) for value in matrix()}

    def case(self, name):
        return self.reports["synthetic-" + name]

    def offsets(self, name):
        report = self.case(name)
        anchor = parse_snapshot(report["input"]).anchor
        return [(t - anchor) // 60 for t in report["feasible_sets"]["production"]]

    def test_every_matrix_outcome_is_explicit_and_no_unexplained_discrepancy(self):
        for value in matrix():
            report = self.reports[value["snapshot_id"]]
            with self.subTest(name=value["snapshot_id"]):
                self.assertEqual(report["status"], expected_status(value),
                                 json.dumps({k: v for k, v in report.items() if k != "normalized"}))
                self.assertFalse(report["discrepancies"])

    def test_independent_small_exhaustive_feasible_sets(self):
        count = 0
        for value in matrix():
            expected = value["provenance"].get("independent_expected_offsets")
            if expected is not None:
                count += 1
                self.assertEqual(self.offsets(value["snapshot_id"].removeprefix("synthetic-")), json.loads(expected))
        self.assertEqual(count, 20)

    def test_multiple_professors_manual_and_touching_window_witnesses(self):
        self.assertEqual(self.offsets("multiple-professors"), [30, 90])
        self.assertEqual(self.offsets("manual-off-grid"), [1, 150])
        self.assertEqual(self.offsets("touching-windows-offset-grid"), list(range(22, 143, 15)))
        self.assertEqual(self.offsets("adjacent-commitment"), list(range(30, 151, 15)))
        self.assertEqual(self.offsets("empty-feasible-set"), [])
        self.assertEqual(self.offsets("exact-end-boundary"), [0])

    def test_role_identity_does_not_change_feasibility(self):
        expected = self.offsets("one-professor")
        for role in ("student", "professor", "administrator", "committee-organizer"):
            self.assertEqual(self.offsets("organizer-" + role), expected)

    def test_more_than_100_feasible_starts_are_not_reconstructed_from_top_k(self):
        report = self.case("over-100-feasible-weekday-boundary")
        self.assertEqual(report["candidate_count"], 191)
        self.assertEqual(len(report["feasible_sets"]["cdmcs"]), 191)
        self.assertEqual(len(report["ranking"]["production"]), 100)
        self.assertEqual(len(report["ranking"]["cdmcs"]), 100)
        self.assertTrue(report["ranking"]["production_truncated"])
        self.assertTrue(report["ranking"]["cdmcs_truncated"])

    def test_ranking_difference_is_explained_and_not_a_feasibility_failure(self):
        report = self.case("optional-unavailable-ranking-difference")
        anchor = parse_snapshot(report["input"]).anchor
        self.assertTrue(report["feasible_set_equal"])
        self.assertFalse(report["ranking"]["same_start_order"])
        self.assertEqual(report["ranking"]["production"][0]["start"], anchor + 60 * 60)
        self.assertEqual(report["ranking"]["cdmcs"][0]["start_minute"], 0)

    def test_cross_midnight_dst_and_unsupported_cases(self):
        for name in ("cross-midnight", "dst-spring", "dst-fall", "optional-unresolved"):
            self.assertTrue(self.case(name)["feasible_set_equal"])
        for name in ("mandatory-unresolved", "exclusive-resource-unsupported", "capability-unsupported",
                     "backward-civil-date-unsupported", "invalid-dst-gap", "invalid-dst-fold"):
            self.assertEqual(self.case(name)["calls"], [])

    def test_no_files_are_created_in_execution_workspace(self):
        self.assertEqual(list(Path(self.engines._temporary.name).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
