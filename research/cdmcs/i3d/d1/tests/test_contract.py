import copy
from dataclasses import FrozenInstanceError
import json
import unittest

from research.cdmcs.i3d.d1.contract import (PreferenceError, PreferenceUnavailable, load_document,
                                         parse_policy, parse_preference)
from research.cdmcs.i3d.d1.tests.fixtures import policy, preference


class PreferenceContractTests(unittest.TestCase):
    def test_configured_profile_is_explicit_immutable_and_role_independent(self):
        result = parse_preference(preference())
        self.assertEqual((result.owner, result.revision, result.desired_gap), ("organizer", 1, 15))
        with self.assertRaises(FrozenInstanceError):
            result.owner = "someone-else"
        self.assertNotIn("organizer", repr(result))

    def test_all_fields_are_required_even_zero_values(self):
        for key in preference():
            with self.subTest(key=key):
                value = preference()
                del value[key]
                with self.assertRaises(PreferenceError) as caught:
                    parse_preference(value)
                self.assertEqual(caught.exception.code, "MISSING_FIELD")

    def test_missing_unknown_and_unsupported_are_distinct(self):
        for state in ("missing", "unknown", "unsupported"):
            result = parse_preference(preference(state=state, effective=None, preferred_weekdays=None,
                                                preferred_windows=None, desired_gap_minutes=None))
            self.assertEqual(result.state, state)
            self.assertIsNone(result.desired_gap)

    def test_unavailable_state_cannot_smuggle_configured_values(self):
        with self.assertRaises(PreferenceError):
            parse_preference(preference(state="unknown"))

    def test_configured_null_is_not_zero_or_indifference(self):
        for key in ("effective", "preferred_weekdays", "preferred_windows", "desired_gap_minutes"):
            with self.subTest(key=key), self.assertRaises(PreferenceError):
                parse_preference(preference(**{key: None}))

    def test_explicit_indifference_is_not_a_missing_gap(self):
        result = parse_preference(preference(desired_gap_minutes="indifferent"))
        self.assertEqual(result.desired_gap, "indifferent")
        self.assertEqual(result.weekdays, ())

    def test_versions_and_synthetic_provenance_are_checked(self):
        with self.assertRaises(PreferenceUnavailable):
            parse_preference(preference(preference_version=2))
        for changes in ({"synthetic": False}, {"provenance": {"source": "live", "fixture_id": "private"}},
                        {"role": "Administrator"}, {"owner": ""}, {"revision": 0}):
            with self.subTest(changes=changes), self.assertRaises(PreferenceError):
                parse_preference(preference(**changes))

    def test_bool_float_and_string_numbers_are_not_integers(self):
        for value in (True, False, 1.0, "15", -1, 1441, 2**100):
            with self.subTest(value=value), self.assertRaises(PreferenceError):
                parse_preference(preference(desired_gap_minutes=value))

    def test_dates_and_timezones_are_explicit(self):
        for changes in ({"timezone": "Bad/Zone"}, {"timezone": None},
                        {"effective": {"from": "20300101", "until": "2030-01-07"}},
                        {"effective": {"from": "2030-01-08", "until": "2030-01-07"}},
                        {"effective": {"from": "2030-02-30", "until": "2030-03-01"}}):
            with self.subTest(changes=changes), self.assertRaises(PreferenceError):
                parse_preference(preference(**changes))

    def test_weekdays_are_unique_bounded_and_canonical(self):
        self.assertEqual(parse_preference(preference(preferred_weekdays=[5, 1])).weekdays, (1, 5))
        for days in ([1, 1], [0], [8], [True], "Monday"):
            with self.subTest(days=days), self.assertRaises(PreferenceError):
                parse_preference(preference(preferred_weekdays=days))

    def test_touching_windows_merge_without_changing_meaning(self):
        windows = [{"weekday": 1, "start": "10:00", "end": "12:00"},
                   {"weekday": 1, "start": "09:00", "end": "10:00"}]
        self.assertEqual(parse_preference(preference(preferred_windows=windows)).windows, ((1, 540, 720),))

    def test_cross_midnight_and_sunday_wrap_are_explicit(self):
        result = parse_preference(preference(preferred_weekdays=[1, 7], preferred_windows=[
            {"weekday": 7, "start": "22:00", "end": "02:00"}]))
        self.assertEqual(result.windows, ((1, 0, 120), (7, 1320, 1440)))

    def test_overlaps_duplicates_and_inconsistent_weekdays_are_rejected(self):
        first = {"weekday": 1, "start": "09:00", "end": "12:00"}
        for windows, days in (([first, first], []),
                              ([first, {**first, "start": "11:00"}], []), ([first], [2]),
                              ([{"weekday": 1, "start": "22:00", "end": "02:00"}], [1])):
            with self.subTest(windows=windows), self.assertRaises(PreferenceError):
                parse_preference(preference(preferred_windows=windows, preferred_weekdays=days))

    def test_clock_values_do_not_round_or_guess(self):
        for start, end in (("9:00", "10:00"), ("24:00", "24:00"), ("09:61", "10:00"),
                           ("09:00", "09:00"), ("09:00:01", "10:00"), ("09:00", "24:01"),
                           ("\u0660\u0669:\u0660\u0660", "10:00")):
            with self.subTest(start=start, end=end), self.assertRaises(PreferenceError):
                parse_preference(preference(preferred_windows=[{"weekday": 1, "start": start, "end": end}]))

    def test_json_rejects_duplicates_nonfinite_and_wrong_encodings(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'[]', b'\xff', b'{}{}', b' ' * (4*1024**2+1)):
            with self.subTest(size=len(raw)), self.assertRaises(PreferenceError):
                load_document(raw)
        value = preference()
        self.assertEqual(parse_preference(load_document(json.dumps(value).encode())), parse_preference(value))

    def test_unknown_fields_and_payloads_do_not_leak_in_errors(self):
        value = preference()
        value["PRIVATE-MARKER"] = "PRIVATE-MARKER"
        with self.assertRaises(PreferenceError) as caught:
            parse_preference(value)
        self.assertNotIn("PRIVATE", str(caught.exception))

    def test_identifiers_are_bounded_in_utf8_bytes_not_characters(self):
        self.assertEqual(parse_preference(preference(owner='x'*256)).owner, 'x'*256)
        self.assertEqual(parse_preference(preference(owner='\u6559'*85)).owner, '\u6559'*85)
        with self.assertRaises(PreferenceError):
            parse_preference(preference(owner='\u6559'*86))


class CostPolicyTests(unittest.TestCase):
    def test_policy_has_no_omitted_numerical_defaults(self):
        for key in policy():
            value = policy()
            del value[key]
            with self.subTest(key=key), self.assertRaises(PreferenceError):
                parse_policy(value)

    def test_explicit_zero_policy_is_valid_not_missing(self):
        value = policy(preferred_rate=0, outside_window_rate=0, outside_day_rate=0,
                       gap_weight=0, nearby_limit=0)
        self.assertEqual(parse_policy(value).preferred_rate, 0)

    def test_invalid_weights_and_conflicting_tiers_are_rejected(self):
        for key, values in (("gap_weight", [-1, 100001, True, 1.5, None]),
                            ("nearby_limit", [-1, 10081]), ("delay_per_day", [-1, 10**7+1]),
                            ("outside_day_rate", [-1, 10**8+1, 0])):
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(PreferenceError):
                    parse_policy(policy(**{key: value}))

    def test_engine_upper_bounds_are_accepted_exactly(self):
        result = parse_policy(policy(preferred_rate=10**8, outside_window_rate=10**8,
                                     outside_day_rate=10**8, gap_weight=100000, nearby_limit=10080,
                                     exception_fee=10**7, move_fixed_cost=10**7,
                                     move_participant_cost=10**7, delay_per_day=10**7))
        self.assertEqual(result.delay_per_day, 10**7)

    def test_no_unapproved_objective_can_be_selected(self):
        for changes in ({"rate_model": "new-minimax"}, {"back_to_back_penalty": 1},
                        {"movement_distance_weight": 1}, {"optional_attendance_weight": 1},
                        {"synthetic": False}):
            with self.subTest(changes=changes), self.assertRaises(PreferenceError):
                parse_policy(policy(**changes))

    def test_policy_input_is_not_mutated(self):
        value = policy()
        original = copy.deepcopy(value)
        parse_policy(value)
        self.assertEqual(value, original)
