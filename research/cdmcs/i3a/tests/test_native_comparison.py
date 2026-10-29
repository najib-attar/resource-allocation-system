"""Real C++ processes, only when an explicit I1 executable/hash is provided."""

import json
import os
from collections import Counter
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
        cls.owner = OfflineEngines(os.environ["CDMCS_I3A_BINARY"], os.environ["CDMCS_I3A_SHA256"],
                                  os.environ.get("CDMCS_I3A_PRODUCTION"))
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
                if report["status"] != "equal":
                    self.assertEqual(report["calls"], [], "Excluded/invalid cases must not reach either engine")

    def test_reported_comparison_domain_is_preserved(self):
        self.assertEqual(Counter(row["status"] for row in self.reports.values()),
                         {"equal": 41, "unsupported_comparison": 5, "input_engine_error": 4})
        supported = [row for row in self.reports.values() if row["status"] == "equal"]
        self.assertEqual(sum(row["candidate_count"] for row in supported), 469)
        self.assertEqual(sum(len(row["feasible_sets"]["production"]) for row in supported), 391)
        self.assertEqual(sum(len(row["feasible_sets"]["cdmcs"]) for row in supported), 391)
        self.assertTrue(all(row["complete"] and row["feasible_set_equal"] for row in supported))

    def test_paired_requests_preserve_intervals_people_and_hard_calendars(self):
        for report in self.reports.values():
            if report["status"] != "equal":
                continue
            snapshot = parse_snapshot(report["input"])
            ids = dict(report["normalized"]["identifiers"])
            required = {p.id for p in snapshot.participants if p.required}
            by_candidate = {}
            for call in report["calls"]:
                if call["phase"] == "validation":
                    by_candidate.setdefault(call["candidate"], {})[call["engine"]] = call["request"]
            self.assertEqual(len(by_candidate), report["candidate_count"])
            for candidate, requests in by_candidate.items():
                production, cdmcs = requests["production"], requests["cdmcs"]
                self.assertEqual(production["proposed"], {"start": candidate, "end": candidate + snapshot.duration * 60})
                self.assertEqual(cdmcs["candidate_starts"], [(candidate - snapshot.anchor) // 60])
                self.assertEqual(cdmcs["duration"], production["durationMinutes"])
                self.assertEqual(set(cdmcs["required_people"]), required)
                self.assertEqual({ids[p] for p in required}, {production["organizerId"], *production["professorIds"]})
                self.assertEqual(set(production["invitedIds"]), {ids[p.id] for p in snapshot.participants if not p.required})
                self.assertTrue(set(production["invitedIds"]).isdisjoint(ids[p] for p in required))
                self.assertEqual(cdmcs["profiles"][snapshot.organizer]["published"],
                                 [[0, (snapshot.horizon.end - snapshot.anchor) // 60]])
                production_busy = {(row["userId"], row["start"], row["end"]) for row in production["busy"]
                                   if row["userId"] in {ids[p] for p in required}}
                cdmcs_busy = {(ids[row["people"][0]], snapshot.anchor + row["start"] * 60,
                               snapshot.anchor + (row["start"] + row["duration"]) * 60) for row in cdmcs["existing"]}
                self.assertEqual(production_busy, cdmcs_busy)
                for person in required - {snapshot.organizer}:
                    published = {(max(row["start"], snapshot.anchor), min(row["end"], snapshot.horizon.end))
                                 for row in production["published"] if row["userId"] == ids[person]
                                 and max(row["start"], snapshot.anchor) < min(row["end"], snapshot.horizon.end)}
                    self.assertEqual(published, {(snapshot.anchor + a * 60, snapshot.anchor + b * 60)
                                                for a, b in cdmcs["profiles"][person]["published"]})
                self.assertEqual(cdmcs["replacement_starts"], [])
                self.assertEqual(cdmcs["required_resources"], [])
                self.assertTrue(all(not row["flexible"] for row in cdmcs["existing"]))
                self.assertTrue(all(not row["exceptions"] for row in cdmcs["profiles"].values()))

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
        self.assertEqual(self.offsets("three-professors"), [30, 90, 150])
        self.assertEqual(self.offsets("manual-off-grid"), [1, 150])
        self.assertEqual(self.offsets("touching-windows-offset-grid"), list(range(22, 143, 15)))
        self.assertEqual(self.offsets("adjacent-commitment"), list(range(30, 151, 15)))
        self.assertEqual(self.offsets("empty-feasible-set"), [])
        self.assertEqual(self.offsets("exact-end-boundary"), [0])

    def test_role_identity_does_not_change_feasibility(self):
        expected = self.offsets("one-professor")
        for role in ("student", "professor", "administrator", "committee-organizer"):
            self.assertEqual(self.offsets("organizer-" + role), expected)
        self.assertEqual(self.offsets("unicode-opaque-identifiers"), expected)

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
