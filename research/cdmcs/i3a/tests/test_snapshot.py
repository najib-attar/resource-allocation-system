from dataclasses import FrozenInstanceError
import copy
import json
import unittest
from zoneinfo import ZoneInfo

from research.cdmcs.i3a.fixtures import basic
from research.cdmcs.i3a.snapshot import SnapshotError, instant, load_snapshot, parse_snapshot


class SnapshotTests(unittest.TestCase):
    def test_nested_contract_is_immutable_and_detached(self):
        value = basic()
        snapshot = parse_snapshot(value)
        value["participants"][1]["published"].clear()
        self.assertEqual(len(snapshot.participants[1].published), 1)
        with self.assertRaises(FrozenInstanceError):
            snapshot.participants[0].id = "other"
        with self.assertRaises(TypeError):
            snapshot.provenance[0] = ("x", "y")

    def test_required_fields_types_and_bounds(self):
        for field, invalid in (("synthetic", False), ("snapshot_version", True),
                               ("duration_minutes", True), ("duration_minutes", 0),
                               ("duration_minutes", 1441), ("timezone", "Unknown/University"),
                               ("organizer", "stranger"), ("participants", [])):
            with self.subTest(field=field, value=invalid):
                value = basic()
                value[field] = invalid
                with self.assertRaises(SnapshotError):
                    parse_snapshot(value)
        value = basic()
        del value["provenance"]
        with self.assertRaises(SnapshotError):
            parse_snapshot(value)

    def test_invalid_relations_and_unknown_fields(self):
        for mutate in (lambda v: v.update(unknown="x"),
                       lambda v: v["participants"].append(copy.deepcopy(v["participants"][0])),
                       lambda v: v["candidates"].update(step_minutes=5),
                       lambda v: v["participants"][0].update(required=False),
                       lambda v: v["candidates"].update(anchor_participant="organizer")):
            value = basic()
            mutate(value)
            with self.assertRaises(SnapshotError):
                parse_snapshot(value)

    def test_wire_size_duplicate_keys_nonfinite_and_malformed(self):
        for raw in (b"{", b'{"x":1,"x":2}', b'{"x":NaN}', b" " * (16 * 1024 * 1024 + 1), b"\xff"):
            with self.subTest(length=len(raw)), self.assertRaises(SnapshotError):
                load_snapshot(raw)
        self.assertEqual(load_snapshot(json.dumps(basic()).encode()).id, "synthetic-basic")

    def test_no_rounding_or_implicit_anchor_timezone(self):
        for text in ("2030-01-07T06:00:01Z", "2030-01-07T06:00:00.000001Z", "2101-01-01T00:00:00Z"):
            with self.assertRaises(SnapshotError):
                instant(text, ZoneInfo("Europe/Istanbul"))
        value = basic()
        value["utc_anchor"] = "2030-01-07T06:00"
        with self.assertRaises(SnapshotError):
            parse_snapshot(value)

    def test_dst_fold_gap_and_offset_mismatch_rejected(self):
        zone = ZoneInfo("Europe/Berlin")
        for text in ("2026-03-29T02:30", "2026-10-25T02:30", "2026-10-25T02:30+02:00",
                     "2026-01-07T10:00+03:00"):
            with self.subTest(text=text), self.assertRaises(SnapshotError):
                instant(text, zone)
        self.assertEqual(instant("2026-10-25T00:30Z", zone) + 3600,
                         instant("2026-10-25T01:30Z", zone))

    def test_explicit_local_time_uses_only_declared_zone(self):
        self.assertEqual(instant("2030-01-07T09:00", ZoneInfo("Europe/Istanbul")),
                         instant("2030-01-07T06:00Z", ZoneInfo("UTC")))

    def test_overlapping_rate_bands_and_excessive_collections_rejected(self):
        value = basic()
        value["participants"][1]["preference"] = {"rate_bands": [
            {"interval": value["horizon"], "rate": 1}, {"interval": value["horizon"], "rate": 2}]}
        with self.assertRaises(SnapshotError):
            parse_snapshot(value)
        value = basic()
        value["participants"][1]["published"] *= 1025
        with self.assertRaises(SnapshotError):
            parse_snapshot(value)


if __name__ == "__main__":
    unittest.main()
