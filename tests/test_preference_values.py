"""Private intent validation is shared without granting research provenance."""

import copy
import json
from unittest import TestCase

from web.preference_values import PreferenceError, load_document, parse_values


def preference_values(**changes):
    value = {"timezone": "Europe/Istanbul", "effective": {"from": "2030-01-01", "until": "2030-12-31"},
             "preferred_weekdays": [], "preferred_windows": [], "desired_gap_minutes": "indifferent"}
    value.update(changes)
    return value


class PreferenceValueTests(TestCase):
    def test_values_are_explicit_immutable_and_private(self):
        raw = preference_values()
        parsed = parse_values(raw)
        raw['effective']['from'] = '2040-01-01'
        self.assertEqual(parsed.first.isoformat(), '2030-01-01')
        self.assertNotIn('2030', repr(parsed))
        with self.assertRaises(AttributeError):
            parsed.timezone = 'UTC'

    def test_every_value_is_required_and_none_is_not_neutral(self):
        for key in preference_values():
            for absent in (False, True):
                value = preference_values()
                if absent:
                    del value[key]
                else:
                    value[key] = None
                with self.subTest(key=key, absent=absent), self.assertRaises(PreferenceError):
                    parse_values(value)

    def test_zero_indifference_and_empty_arrays_are_distinct_explicit_values(self):
        for gap in (0, 15, 1440, 'indifferent'):
            parsed = parse_values(preference_values(desired_gap_minutes=gap))
            self.assertEqual(parsed.desired_gap, gap)
            self.assertEqual(parsed.weekdays, ())
        for gap in (True, 0.0, '0', -1, 1441, 2**63):
            with self.subTest(gap=gap), self.assertRaises(PreferenceError):
                parse_values(preference_values(desired_gap_minutes=gap))

    def test_original_overnight_endpoints_survive_normalization_and_roundtrip(self):
        raw = preference_values(preferred_weekdays=[1, 7], preferred_windows=[
            {'weekday': 7, 'start': '22:00', 'end': '02:00'}])
        parsed = parse_values(raw)
        self.assertEqual(parsed.windows, ((1, 0, 120), (7, 1320, 1440)))
        self.assertEqual(parsed.source_windows, ((7, 1320, 1560),))
        self.assertEqual(parsed.document()['preferred_windows'], raw['preferred_windows'])
        self.assertEqual(parse_values(parsed.document()), parsed)

    def test_touching_windows_keep_both_original_endpoints(self):
        windows = [{'weekday': 1, 'start': '09:00', 'end': '10:00'},
                   {'weekday': 1, 'start': '10:00', 'end': '12:00'}]
        parsed = parse_values(preference_values(preferred_windows=windows))
        self.assertEqual(parsed.windows, ((1, 540, 720),))
        self.assertEqual(parsed.document()['preferred_windows'], windows)

    def test_overlaps_cross_day_conflicts_and_invalid_clocks_are_rejected(self):
        for windows in ([{'weekday': 1, 'start': '09:00', 'end': '09:00'}],
                        [{'weekday': 1, 'start': '24:00', 'end': '02:00'}],
                        [{'weekday': 1, 'start': '22:00', 'end': '02:00'},
                         {'weekday': 2, 'start': '01:00', 'end': '03:00'}]):
            with self.subTest(windows=windows), self.assertRaises(PreferenceError):
                parse_values(preference_values(preferred_windows=windows))

    def test_valid_iana_zones_do_not_imply_dated_dst_eligibility(self):
        for zone in ('UTC', 'Europe/Istanbul', 'America/New_York', 'Pacific/Apia'):
            parsed = parse_values(preference_values(timezone=zone, preferred_windows=[
                {'weekday': 7, 'start': '02:30', 'end': '04:00'}]))
            self.assertEqual(parsed.timezone, zone)
        for zone in ('PRIVATE-ZONE', '../UTC', 'Europe/Istanbul\x00', '', None):
            with self.subTest(zone=zone), self.assertRaises(PreferenceError):
                parse_values(preference_values(timezone=zone))

    def test_dates_are_local_bounded_and_never_inferred(self):
        for dates in ({'from': '2030-12-31', 'until': '2030-01-01'},
                      {'from': '2030-02-30', 'until': '2030-12-31'},
                      {'from': '1969-12-31', 'until': '2030-12-31'},
                      {'from': '2030-01-01', 'until': '2100-01-01'}):
            with self.subTest(dates=dates), self.assertRaises(PreferenceError):
                parse_values(preference_values(effective=dates))

    def test_bounded_json_rejects_duplicate_keys_nonfinite_and_nested_overflow(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":[1e999]}', b'[]', b'\xff',
                    b' '*(4*1024**2+1), b'{"x":'+b'['*2000+b'0'+b']'*2000+b'}'):
            with self.subTest(length=len(raw)), self.assertRaises(PreferenceError):
                load_document(raw)
        self.assertEqual(load_document(json.dumps(preference_values()).encode()), preference_values())

    def test_mutation_unknown_fields_and_private_error_messages(self):
        raw = preference_values()
        original = copy.deepcopy(raw)
        parse_values(raw)
        self.assertEqual(raw, original)
        for field in ('owner', 'actor_id', 'synthetic', 'provenance', 'PRIVATE-MARKER'):
            with self.assertRaises(PreferenceError) as caught:
                parse_values({**raw, field: 'PRIVATE-MARKER'})
            self.assertNotIn('PRIVATE-MARKER', str(caught.exception))

    def test_production_values_never_gain_synthetic_provenance(self):
        from research.cdmcs.i3d.d1.contract import parse_preference
        from research.cdmcs.i3c.admission import AdmissionError, synthetic_fixture
        raw = parse_values(preference_values()).document()
        with self.assertRaises(PreferenceError):
            parse_preference(raw)
        with self.assertRaises(AdmissionError):
            synthetic_fixture(raw)
