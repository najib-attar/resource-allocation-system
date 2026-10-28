"""Black-box safety regressions; writes no fixtures or application data."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest


BINARY = None


def request(horizon=10):
    return {
        "operation": "cdmcs_schedule_v1", "horizon_minutes": horizon,
        "duration": 1, "candidate_starts": [0, 1], "replacement_starts": [],
        "required_people": ["A"], "required_resources": [], "existing": [],
        "profiles": {"A": {"rate_prefix": [0] * (horizon + 1),
                           "published": [[0, horizon]], "exceptions": []}},
        "local_day_index": [0] * (horizon + 1), "limit": 100,
    }


class SafetyTests(unittest.TestCase):
    def invoke(self, data):
        raw = data if isinstance(data, bytes) else json.dumps(data).encode("utf-8")
        process = subprocess.run([str(BINARY)], input=raw, capture_output=True, timeout=20)
        result = json.loads(process.stdout)
        self.assertIsInstance(result, dict)
        return process.returncode, result

    def invalid(self, value):
        code, result = self.invoke(value)
        self.assertEqual(code, 2, result)
        self.assertEqual(result["status"], "INVALID_INPUT")
        self.assertTrue(result["error"])
        self.assertNotIn("recommendations", result)

    def test_day_subtraction_is_widened_before_arithmetic(self):
        value = request()
        value["local_day_index"] = [-2147483648] + [2147483647] * 10
        code, result = self.invoke(value)
        self.assertEqual(code, 0, result)
        self.assertEqual([r["start_minute"] for r in result["recommendations"]], [0, 1])
        self.assertEqual(result["recommendations"][1]["total_cost"], 4294967295 * 5)

    def test_byte_limit_before_dom_parsing(self):
        raw = json.dumps(request()).encode() + b" " * (16 * 1024 * 1024)
        self.invalid(raw)

    def test_control_z_does_not_hide_trailing_invalid_json(self):
        self.invalid(json.dumps(request()).encode() + b"\x1a{}")

    def test_wire_byte_limit_counts_crlf_before_text_translation(self):
        self.invalid(json.dumps(request()).encode() + b"\r\n" * (8 * 1024 * 1024))

    def test_bounded_identifiers_and_memberships(self):
        value = request()
        value["required_resources"] = ["x" * 257]
        self.invalid(value)
        value["required_resources"] = [str(i) for i in range(257)]
        self.invalid(value)

    def test_bounded_window_count(self):
        value = request()
        value["profiles"]["A"]["published"] = [[0, 10]] * 1025
        self.invalid(value)

    def test_malformed_json_and_types(self):
        for raw in (b"", b"{", b"{} {}", b"[]", b"null", b'{"x":"\xff"}',
                    b"[" * 40 + b"0" + b"]" * 40):
            with self.subTest(raw=raw[:40]):
                self.invalid(raw)
        for key, bad in (("duration", True), ("duration", 1.0), ("duration", -1),
                         ("horizon_minutes", 100801), ("duration", 2**64),
                         ("operation", "unknown"), ("candidate_starts", []),
                         ("candidate_starts", [0, 0]), ("limit", 101)):
            with self.subTest(key=key, value=bad):
                self.invalid(request() | {key: bad})

    def test_prefix_bounds_and_nonmonotone_days(self):
        for prefix in ([0], [0, -1] + [0] * 9, [0, 100000001] + [100000001] * 9):
            value = request()
            value["profiles"]["A"]["rate_prefix"] = prefix
            self.invalid(value)
        value = request()
        value["local_day_index"] = [1, 0] + [1] * 9
        self.invalid(value)

    def test_meeting_numeric_boundaries_and_baseline_conflicts(self):
        meeting = {"id": "M", "start": 1, "duration": 1, "people": ["A"], "resources": []}
        for changes in ({"start": 2147483647}, {"start": -2147483648},
                        {"duration": 2147483647}, {"duration": -1}, {"id": "NEW"}):
            self.invalid(request() | {"existing": [meeting | changes]})
        self.invalid(request() | {"existing": [meeting, meeting | {"id": "N"}]})

    def test_maximum_horizon_and_prefix_values(self):
        value = request(100800)
        value["duration"] = 100800
        value["candidate_starts"] = [0]
        value["profiles"]["A"]["rate_prefix"] = [min(i * 100000000, 10**12) for i in range(100801)]
        code, result = self.invoke(value)
        self.assertEqual(code, 0, result)
        self.assertEqual(result["recommendations"][0]["total_cost"], 10**12)

    def test_count_and_top_k_are_distinguished(self):
        value = request(150)
        value["candidate_starts"] = list(range(150))
        code, result = self.invoke(value)
        self.assertEqual(code, 0)
        self.assertEqual(result["solutions_evaluated"], 150)
        self.assertEqual(result["returned_count"], 100)
        self.assertTrue(result["truncated"])

    def test_unresolved_calendar_has_complete_result_metadata(self):
        code, result = self.invoke(request() | {"unresolved_people": ["A"]})
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "UNRESOLVED_CALENDAR")
        self.assertEqual(result["solutions_evaluated"], 0)
        self.assertEqual(result["returned_count"], 0)
        self.assertFalse(result["truncated"])

    def test_typed_resource_keys_and_unicode(self):
        value = request()
        value["existing"] = [{"id": "\u00d6\"\n", "start": 0, "duration": 10,
                              "people": [], "resources": ["A"], "flexible": False}]
        code, result = self.invoke(value)
        self.assertEqual(code, 0)
        self.assertEqual(result["solutions_evaluated"], 2)
        value["required_resources"] = ["A"]
        self.assertEqual(self.invoke(value)[1]["status"], "NO_FEASIBLE_PROPOSAL")

    def test_replacement_cache_budget_fails_without_partial_proposals(self):
        value = request(1000)
        value["required_resources"] = [str(i) for i in range(256)]
        value["candidate_starts"] = [0]
        value["replacement_starts"] = list(range(1000))
        value["existing"] = [{"id": "M", "start": 0, "duration": 1,
                              "people": ["A"], "resources": value["required_resources"],
                              "flexible": True}]
        self.invalid(value)

    def test_window_search_work_limit_does_not_publish_partial_top_k(self):
        value = request(10001)
        value["candidate_starts"] = list(range(1, 10001))
        value["profiles"]["A"]["published"] = [[0, 1]] * 1023 + [[0, 10001]]
        code, result = self.invoke(value)
        self.assertEqual(code, 2)
        self.assertIn("search work", result["error"])
        self.assertNotIn("recommendations", result)

    def test_resource_only_relocation_stays_inside_horizon(self):
        value = request(4) | {"candidate_starts": [0], "replacement_starts": [3],
                              "required_resources": ["R"]}
        value["existing"] = [{"id": "X", "start": 0, "duration": 2,
                              "people": [], "resources": ["R"], "flexible": True}]
        code, result = self.invoke(value)
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "NO_FEASIBLE_PROPOSAL")
        # The preserved reference has a known empty-people horizon hole. This is
        # evidence of the discrepancy, not a claim of parity on that input.
        sys.path.insert(0, str(Path(__file__).parent / "original_reference"))
        from test_differential import fixture_profiles
        from cdmcs_v1_reference_prototype import Meeting
        from cdmcs_v15_minute_domain import MinuteCase, exhaustive
        case = MinuteCase([Meeting("X", 0, 2, (), ("R",), True)], ("A",), ("R",),
                          1, (0,), (3,), fixture_profiles(4, profiles=("A",)))
        self.assertEqual(exhaustive(case)[3:], ("X", 3))

    def test_original_research_sources_match_archive_manifest(self):
        root = Path(__file__).resolve().parent.parent
        manifest = json.loads((root / "docs" / "UPSTREAM_SHA256.json").read_text())
        for path in sorted((root / "tests" / "original_reference").glob("*.py")):
            with self.subTest(file=path.name):
                key = path.relative_to(root).as_posix()
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), manifest[key])

    def test_maximum_person_count_and_costs_remain_64_bit(self):
        value = request()
        value["required_people"] = [str(i) for i in range(256)]
        value["profiles"] = {p: {"rate_prefix": [i * 100000000 for i in range(11)],
                                 "published": [[0, 10]], "exceptions": []}
                             for p in value["required_people"]}
        value["local_day_index"] = [-2147483648] + [2147483647] * 10
        value["delay_per_day"] = 10000000
        code, result = self.invoke(value)
        self.assertEqual(code, 0)
        self.assertEqual(result["recommendations"][1]["total_cost"],
                         25600000000 + 4294967295 * 10000000)

    def test_limit_one_keeps_same_optimum_and_counts(self):
        full = self.invoke(request())[1]
        limited = self.invoke(request() | {"limit": 1})[1]
        self.assertEqual(limited["recommendations"], full["recommendations"][:1])
        self.assertEqual(limited["solutions_evaluated"], full["solutions_evaluated"])
        self.assertTrue(limited["truncated"])

    def test_historical_backward_local_date_is_explicitly_unsupported(self):
        from datetime import datetime, timedelta, timezone
        from zoneinfo import ZoneInfo
        value = request(240)
        anchor = datetime(2010, 11, 7, 1, tzinfo=timezone.utc)
        zone = ZoneInfo("America/St_Johns")
        value["local_day_index"] = [(anchor + timedelta(minutes=i)).astimezone(zone).date().toordinal()
                                    for i in range(241)]
        self.assertLess(value["local_day_index"][91], value["local_day_index"][90])
        code, result = self.invoke(value)
        self.assertEqual(code, 2)
        self.assertIn("nondecreasing", result["error"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", required=True, type=Path)
    args, remaining = parser.parse_known_args()
    BINARY = args.binary.resolve()
    unittest.main(argv=[sys.argv[0], *remaining])
