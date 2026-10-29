"""Pure DTO/privacy boundaries; no database or executable required."""

from dataclasses import FrozenInstanceError, asdict
import json
from pathlib import Path
import tempfile
import unittest

from research.cdmcs.i3a.__main__ import export
from research.cdmcs.i3a.adapter import UnsupportedComparison, normalize, production_request, cdmcs_request
from research.cdmcs.i3a.snapshot import SnapshotError, parse_snapshot
from research.cdmcs.i3a.fixtures import basic
from research.cdmcs.i3b.projection import ProjectionError, project_facts


def facts():
    return {"protocolVersion": 1, "operation": "appointment", "action": "recommend",
            "organizerId": 11, "professorIds": [22, 33], "invitedIds": [44],
            "durationMinutes": 30, "horizon": {"start": 1893996000, "end": 1894006800},
            "published": [{"userId": uid, "start": 1893996000, "end": 1894006800} for uid in (22, 33)],
            "busy": [{"userId": 44, "start": 1893996000, "end": 1894006800}], "unresolvedIds": []}


class ProjectionContractTests(unittest.TestCase):
    def test_immutable_contract_and_explicit_non_synthetic_origin(self):
        raw = facts()
        result = project_facts(raw, 7, "Europe/Istanbul")
        snapshot = result.internal_snapshot()
        raw["busy"].clear()
        self.assertEqual(snapshot.origin, "authorized_calendar")
        self.assertEqual(len(snapshot.commitments), 1)
        with self.assertRaises(FrozenInstanceError):
            snapshot.duration = 99
        with self.assertRaises(FrozenInstanceError):
            result.calendar_revision = 99
        self.assertTrue(all(row.preference is None for row in snapshot.participants))

    def test_opaque_aliases_are_per_projection_and_do_not_encode_roles(self):
        first = project_facts(facts(), 1, "Europe/Istanbul").internal_snapshot()
        second = project_facts(facts(), 1, "Europe/Istanbul").internal_snapshot()
        self.assertTrue(all(p.id.startswith("person-") and not p.role_label for p in first.participants))
        self.assertTrue(set(p.id for p in first.participants).isdisjoint(p.id for p in second.participants))
        self.assertEqual(sum(p.required for p in first.participants), 3)
        self.assertEqual(first.grid_anchor, first.participants[1].id)
        self.assertFalse(first.participants[-1].required)

    def test_safe_summary_and_repr_withhold_calendar_contents(self):
        result = project_facts(facts(), 4, "Europe/Istanbul")
        self.assertEqual(result.summary(), {"projection_version": 1, "read_only": True,
                                          "calendar_revision": 4, "engine_execution_enabled": False})
        for rendered in (repr(result), repr(result.internal_snapshot()), json.dumps(result.summary())):
            self.assertNotIn("1893996000", rendered)
            self.assertNotIn("person-", rendered)

    def test_real_origin_or_missing_preferences_cannot_launch_a_comparison(self):
        result = project_facts(facts(), 4, "Europe/Istanbul")
        normalized = normalize(result.internal_snapshot())
        self.assertTrue(any("not approved for engine" in r for r in normalized.unsupported))
        self.assertTrue(any("preferences" in r for r in normalized.unsupported))
        for serializer in (production_request, cdmcs_request):
            with self.assertRaises(UnsupportedComparison):
                serializer(normalized)

    def test_offline_parser_and_direct_export_do_not_accept_database_snapshots(self):
        snapshot = project_facts(facts(), 4, "Europe/Istanbul").internal_snapshot()
        with self.assertRaises(SnapshotError):
            parse_snapshot(asdict(snapshot))
        value = basic()
        value["synthetic"] = False
        with self.assertRaises(SnapshotError):
            parse_snapshot(value)
        with tempfile.TemporaryDirectory(prefix="cdmcs-export-denial-") as folder:
            target = Path(folder) / "must-not-exist"
            with self.assertRaises(ValueError):
                export(target, [{"input": asdict(snapshot)}], {}, [])
            self.assertFalse(target.exists())

    def test_unknown_required_calendar_is_not_free_optional_stays_optional(self):
        raw = facts()
        raw["unresolvedIds"] = [22, 44]
        snapshot = project_facts(raw, 1, "Europe/Istanbul").internal_snapshot()
        self.assertEqual([row.calendar_state for row in snapshot.participants], ["known", "unresolved", "known", "unresolved"])
        self.assertFalse(snapshot.participants[-1].required)

    def test_invalid_or_excessive_facts_fail_without_echoing_payload(self):
        for key, value in (("operation", "equipment"), ("protocolVersion", True), ("action", "unknown"),
                           ("durationMinutes", True), ("professorIds", []), ("professorIds", [22] * 101),
                           ("busy", [{"userId": 999, "start": 1, "end": 2}]),
                           ("unresolvedIds", [999]), ("preferredStart", 1893996001), ("required_resources", ["room"])):
            with self.subTest(key=key):
                raw = facts()
                raw[key] = value
                with self.assertRaises(ProjectionError) as caught:
                    project_facts(raw, 1, "Europe/Istanbul")
                self.assertEqual(caught.exception.code, "INVALID_CALENDAR_FACTS")
                self.assertNotIn("999", str(caught.exception))

    def test_manual_off_grid_candidate_is_preserved_not_rounded(self):
        raw = facts()
        raw.update(action="validate", proposed={"start": 1893996060, "end": 1893997860})
        snapshot = project_facts(raw, 1, "Europe/Istanbul").internal_snapshot()
        self.assertEqual(snapshot.candidate_mode, "explicit")
        self.assertEqual(snapshot.explicit_starts, (1893996060,))

    def test_original_synthetic_contract_remains_normalizable(self):
        snapshot = parse_snapshot(basic())
        self.assertEqual(snapshot.origin, "synthetic")
        self.assertFalse(normalize(snapshot).unsupported)


if __name__ == "__main__":
    unittest.main()
