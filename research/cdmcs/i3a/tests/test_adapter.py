import copy
import unittest

from research.cdmcs.i3a.adapter import UnsupportedComparison, cdmcs_request, normalize, production_request
from research.cdmcs.i3a.fixtures import basic, commitment, participant, period, stamp
from research.cdmcs.i3a.snapshot import parse_snapshot


class AdapterTests(unittest.TestCase):
    def test_production_grid_keeps_original_window_anchor_before_horizon(self):
        value = basic()
        value["horizon"] = period(10, 180)
        value["participants"][1]["published"] = [period(7, 75), period(75, 180)]
        normalized = normalize(parse_snapshot(value))
        self.assertEqual(normalized.candidates[0], parse_snapshot(value).anchor + 22 * 60)
        self.assertEqual(len(dict(normalized.published)["professor-A"]), 1)
        self.assertEqual(production_request(normalized)["published"][0]["start"], normalized.snapshot.anchor + 7 * 60)

    def test_overlap_union_and_optional_calendars_preserve_feasibility(self):
        value = basic()
        value["participants"].append(participant("guest", required=False, published_required=False, role="student"))
        value["commitments"] = [commitment("first", ["professor-A"], 0, 30),
                                commitment("overlap", ["professor-A"], 15, 45),
                                commitment("optional", ["guest"], 0, 180)]
        normalized = normalize(parse_snapshot(value))
        request = cdmcs_request(normalized)
        self.assertEqual(len(request["existing"]), 1)
        self.assertEqual(request["existing"][0]["duration"], 45)
        self.assertNotIn("guest", request["required_people"])
        self.assertEqual(len(production_request(normalized)["busy"]), 2)
        self.assertTrue(all(not item["flexible"] for item in request["existing"]))
        self.assertEqual(request["replacement_starts"], [])

    def test_role_labels_and_input_order_do_not_select_scheduling_logic(self):
        value = basic()
        expected = normalize(parse_snapshot(value))
        for label in ("student", "professor", "administrator", "committee organizer"):
            changed = copy.deepcopy(value)
            changed["participants"][0]["role_label"] = label
            changed["participants"].reverse()
            actual = normalize(parse_snapshot(changed))
            self.assertEqual(production_request(actual), production_request(expected))
            self.assertEqual(cdmcs_request(actual), cdmcs_request(expected))

    def test_unknown_mandatory_and_resources_are_unsupported_not_free(self):
        for state in ("missing", "unresolved", "unsupported"):
            value = basic()
            value["participants"][1]["calendar_state"] = state
            normalized = normalize(parse_snapshot(value))
            with self.assertRaises(UnsupportedComparison):
                production_request(normalized)
        value = basic()
        value["required_resources"] = ["exclusive-room"]
        with self.assertRaises(UnsupportedComparison):
            cdmcs_request(normalize(parse_snapshot(value)))

    def test_optional_unknown_is_preserved_as_unknown_not_required(self):
        value = basic()
        optional = participant("optional", required=False, published_required=False)
        optional["calendar_state"] = "missing"
        value["participants"].append(optional)
        normalized = normalize(parse_snapshot(value))
        self.assertFalse(normalized.unsupported)
        self.assertEqual(production_request(normalized)["unresolvedIds"], [3])
        self.assertNotIn("optional", cdmcs_request(normalized)["profiles"])

    def test_explicit_minute_grid_and_prepared_rates(self):
        value = basic()
        value["candidates"] = {"mode": "explicit", "anchor_participant": "professor-A", "starts": [stamp(1)]}
        value["participants"][1]["preference"] = {"base_rate": 1, "rate_bands": [{"interval": period(0, 30), "rate": 3}]}
        normalized = normalize(parse_snapshot(value))
        request = cdmcs_request(normalized)
        self.assertEqual(request["candidate_starts"], [1])
        self.assertEqual(request["profiles"]["professor-A"]["rate_prefix"][30], 90)
        self.assertEqual(production_request(normalized, normalized.candidates[0])["proposed"]["start"], normalized.snapshot.anchor + 60)

    def test_serializers_return_detached_copies(self):
        normalized = normalize(parse_snapshot(basic()))
        request = cdmcs_request(normalized)
        request["profiles"]["professor-A"]["rate_prefix"][0] = 99
        self.assertEqual(cdmcs_request(normalized)["profiles"]["professor-A"]["rate_prefix"][0], 0)

    def test_clipping_does_not_reanchor_the_production_grid(self):
        value = basic()
        value["utc_anchor"] = stamp(10)
        value["horizon"] = period(10, 180)
        value["participants"][1]["published"] = [period(7, 187)]
        normalized = normalize(parse_snapshot(value))
        self.assertEqual(cdmcs_request(normalized)["candidate_starts"][0], 12)
        self.assertEqual(production_request(normalized)["published"][0]["start"], parse_snapshot(basic()).anchor + 7 * 60)

    def test_incompatible_organizer_and_required_policies_are_not_reinterpreted(self):
        for index, flag in ((0, True), (1, False)):
            value = basic()
            value["participants"][index]["published_required"] = flag
            if index == 1:
                value["participants"].append(participant("anchor"))
                value["candidates"]["anchor_participant"] = "anchor"
            self.assertTrue(normalize(parse_snapshot(value)).unsupported)


if __name__ == "__main__":
    unittest.main()
