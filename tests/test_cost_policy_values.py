"""Institutional values are not an authorization, activation or research exporter."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
from unittest import TestCase

from research.cdmcs.i3d.d1.contract import parse_policy
from research.cdmcs.i3d.d1.tests.fixtures import policy as synthetic_policy
from web.cost_policy_values import (COEFFICIENT_FIELDS, ENGINE_SCORE_BOUND, PREFIX_TOTAL_LIMIT,
    parse_coefficients, parse_institutional_policy)
from web.preference_values import PreferenceError


def policy_document(**changes):
    value = {'policy_contract_version': 1, 'origin': 'institutional_policy', 'policy_id': 'university',
        'revision': 1, 'objective_version': 1, 'engine_operation': 'cdmcs_schedule_v1',
        'objective_model': 'V15_restricted_one_blocking_move', 'rate_model': 'weekday_window_tiers_v1',
        'timezone': 'Europe/Istanbul', 'effective': {'from': '2030-01-01T00:00:00Z', 'until': '2031-01-01T00:00:00Z'},
        'cost_unit': 'Fictional study points', 'calibration_ref': 'fictional-study-v1',
        'provenance': {'type': 'institutional_policy', 'source_ref': 'fictional-institution-record'},
        'coefficients': {key: 0 for key in COEFFICIENT_FIELDS}}
    return value | changes


def parse(value, **kwargs):
    return parse_institutional_policy(value, university_timezone='Europe/Istanbul', **kwargs)


class CostPolicyValueTests(TestCase):
    def test_explicit_zero_is_not_missing_and_values_are_immutable(self):
        result = parse(policy_document())
        self.assertTrue(all(v == 0 for v in result.coefficients.document().values()))
        with self.assertRaises(FrozenInstanceError): result.revision = 2
        self.assertNotIn('fictional-study', repr(result))
        result.document()['coefficients']['gap_weight'] = 7
        self.assertEqual(result.coefficients.gap_weight, 0)

    def test_every_field_is_required_and_unknown_fields_are_rejected(self):
        original = policy_document()
        for key in original:
            value = deepcopy(original); del value[key]
            with self.subTest(key=key), self.assertRaises(PreferenceError): parse(value)
        for key in ('owner_id', 'proposer_id', 'approved_by', 'synthetic', 'status'):
            with self.subTest(key=key), self.assertRaises(PreferenceError): parse(original | {key: 1})

    def test_all_coefficient_minima_maxima_and_strict_types_match_d1(self):
        maximum = dict(zip(COEFFICIENT_FIELDS, (10**8, 10**8, 10**8, 100000, 10080, 10**7, 10**7, 10**7, 10**7)))
        for values in ({key: 0 for key in COEFFICIENT_FIELDS}, maximum):
            self.assertEqual(parse_coefficients(values).document(), values)
            reference = parse_policy(synthetic_policy(**values))
            self.assertEqual([getattr(reference, key) for key in COEFFICIENT_FIELDS], list(values.values()))
        for key, limit in maximum.items():
            for bad in (None, True, False, 0.0, float('inf'), float('nan'), '0', -1, limit + 1, 2**63):
                with self.subTest(key=key, bad=type(bad).__name__), self.assertRaises(PreferenceError):
                    parse_coefficients(maximum | {key: bad})
            value = maximum.copy(); del value[key]
            with self.assertRaises(PreferenceError): parse_coefficients(value)

    def test_tiers_are_ordered_and_nearby_limit_is_not_a_cost_default(self):
        for values in ({'preferred_rate': 2, 'outside_window_rate': 1}, {'outside_window_rate': 2, 'outside_day_rate': 1}):
            with self.assertRaises(PreferenceError): parse_coefficients(policy_document()['coefficients'] | values)
        self.assertEqual(parse_coefficients(policy_document()['coefficients']).nearby_limit, 0)

    def test_versions_identity_and_objective_are_explicit(self):
        for key in ('policy_contract_version', 'objective_version', 'revision'):
            for bad in (True, 0, -1, 1.0, 2**63):
                with self.subTest(key=key), self.assertRaises(PreferenceError): parse(policy_document(**{key: bad}))
        for key in ('policy_contract_version', 'objective_version'):
            with self.assertRaises(PreferenceError): parse(policy_document(**{key: 2}))
        for key in ('origin', 'policy_id', 'engine_operation', 'objective_model', 'rate_model'):
            with self.assertRaises(PreferenceError): parse(policy_document(**{key: 'unsupported'}))
        self.assertEqual(parse(policy_document(revision=2**63 - 1)).revision, 2**63 - 1)

    def test_effective_intervals_are_aware_finite_bounded_and_nonempty(self):
        for start, end in (('2030-01-01', '2031-01-01T00:00Z'), ('invalid', '2031-01-01T00:00Z'),
                          ('2031-01-01T00:00Z', '2030-01-01T00:00Z'), ('2030-01-01T00:00Z', '2030-01-01T00:00Z'),
                          ('1969-01-01T00:00Z', '2031-01-01T00:00Z'), ('2030-01-01T00:00Z', '2100-01-01T00:00Z')):
            with self.subTest(start=start), self.assertRaises(PreferenceError):
                parse(policy_document(effective={'from': start, 'until': end}))
        with self.assertRaises(PreferenceError):
            parse(policy_document(effective={'from': '2030-01-01T00:00:00.1234567Z', 'until': '2031-01-01T00:00:00Z'}))

    def test_timezone_and_institutional_provenance_are_not_synthetic(self):
        for timezone in ('Mars/Invalid', 'UTC', '', None):
            with self.assertRaises(PreferenceError): parse(policy_document(timezone=timezone))
        for provenance in ({'source': 'synthetic-test', 'fixture_id': 'fake'}, {'type': 'synthetic', 'source_ref': 'fake'}, None):
            with self.assertRaises(PreferenceError): parse(policy_document(provenance=provenance))
        with self.assertRaises(PreferenceError): parse_policy(parse(policy_document()).document())

    def test_digest_is_canonical_across_key_order_and_equivalent_offsets(self):
        value = policy_document(cost_unit='Fictional \u00fcniversity "points"')
        before = parse(value)
        reordered = dict(reversed(list(value.items())))
        self.assertEqual(before.content_digest, parse(reordered).content_digest)
        reordered['effective'] = {'from': '2030-01-01T03:00:00+03:00', 'until': '2031-01-01T03:00:00+03:00'}
        self.assertEqual(before.content_digest, parse(reordered).content_digest)
        self.assertEqual(before, parse(before.document(), expected_digest=before.content_digest))
        with self.assertRaises(PreferenceError): parse(value, expected_digest='0' * 64)
        self.assertNotEqual(before.content_digest, parse(value | {'revision': 2}).content_digest)

    def test_bounded_json_and_private_text_errors(self):
        raw = json.dumps(policy_document()).encode()
        self.assertEqual(parse(raw), parse(policy_document()))
        for raw in (b'{"revision":1,"revision":2}', b'{"x":1e999}', b'x' * (4 * 1024**2 + 1)):
            with self.assertRaises(PreferenceError): parse(raw)
        for text in ('', ' ', 'secret\ncalendar', 'x' * 257):
            with self.assertRaises(PreferenceError) as raised: parse(policy_document(cost_unit=text))
            self.assertNotIn('secret', str(raised.exception))

    def test_limits_do_not_claim_feasible_execution_or_new_objective(self):
        self.assertEqual(PREFIX_TOTAL_LIMIT, 10**12)
        self.assertEqual(ENGINE_SCORE_BOUND, 43720003072000000)
        self.assertLess(ENGINE_SCORE_BOUND, 2**63 - 1)
        # Accepted coefficients alone cannot keep an arbitrarily long prefix valid.
        self.assertGreater(parse_coefficients(dict(zip(COEFFICIENT_FIELDS,
            (10**8, 10**8, 10**8, 0, 0, 0, 0, 0, 0)))).preferred_rate * 10001, PREFIX_TOTAL_LIMIT)
