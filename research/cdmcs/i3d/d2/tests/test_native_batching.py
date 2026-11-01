"""Independent, explicitly pinned native witnesses on fictional calendars only."""

from datetime import datetime
import os
import random
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from research.cdmcs.i3a.execution import validate_cdmcs
from research.cdmcs.i3a.fixtures import commitment, matrix, participant, period, rebase, stamp
from research.cdmcs.i3c import runner as kernel
from research.cdmcs.i3c.admission import AdmissionError, synthetic_fixture
from research.cdmcs.i3c.process import execute
from research.cdmcs.i3c.runner import ShadowRunner
from research.cdmcs.i3d.d1.contract import PreferenceUnavailable
from research.cdmcs.i3d.d1.tests import test_native_preferences as d1_native
from research.cdmcs.i3d.d2.planning import prepare
from research.cdmcs.i3d.d2.runner import BatchResult, BatchedShadowRunner
from research.cdmcs.i3d.d2.tests.fixtures import context, fixture, policy, preference
from web.backend_executable import file_sha256


COUNTS = (1, 2, 8, 32, 99, 100, 101, 128, 191, 256)
SIZES = (1, 2, 8, 32, 99, 100)
NATIVE = bool(os.environ.get('CDMCS_I3A_BINARY') and os.environ.get('CDMCS_I3A_SHA256'))
PRODUCTION = bool(os.environ.get('CDMCS_I3A_PRODUCTION'))


def explicit(starts, *, duration=30, end=None):
    value = fixture(len(starts))
    end = max(starts) + duration if end is None else end
    value['duration_minutes'] = duration
    value['horizon'] = period(0, end)
    value['participants'][1]['published'] = [period(0, end)]
    value['candidates']['starts'] = [stamp(t) for t in starts]
    return value


def choices(value, *, specs=None, weights=None, facts=None):
    specs = ([preference(p['id'], timezone=value['timezone'],
                         effective={'from': '1970-01-01', 'until': '2099-12-31'})
              for p in value['participants'] if p['required']] if specs is None else specs)
    weights = policy() if weights is None else weights
    facts = context(value) if facts is None else facts
    return prepare(synthetic_fixture(value), specs, weights, facts), specs, weights


@unittest.skipUnless(NATIVE, 'Explicit CDMCS_I3A_BINARY and CDMCS_I3A_SHA256 required')
class NativeBatchingTests(unittest.TestCase):
    def setUp(self):
        self.binary = os.environ['CDMCS_I3A_BINARY']
        self.digest = os.environ['CDMCS_I3A_SHA256'].lower()
        self.assertEqual(file_sha256(self.binary), self.digest, 'Native binary pin changed')

    def call(self, request, *, complete=True):
        self.assertEqual(file_sha256(self.binary), self.digest)
        payload = execute([self.binary], request, timeout=5, memory_bytes=256*1024**2,
                          input_limit=4*1024**2, output_limit=64*1024).payload
        self.assertIn(validate_cdmcs(payload, request), ('feasible', 'infeasible'))
        if complete:
            self.assertFalse(payload['truncated'])
            self.assertEqual(payload['returned_count'], payload['solutions_evaluated'])
        return payload

    def singleton_reference(self, compiled):
        """Select each target directly from D1, without any D2 partition helpers."""
        original = compiled.to_request()
        starts = original['candidate_starts']
        first = starts[0]
        observations = []
        for index, target in enumerate(starts):
            request = compiled.to_request()
            later_day = original['local_day_index'][target] > original['local_day_index'][first]
            request['candidate_starts'] = ([first, target]
                if original['delay_per_day'] > 0 and later_day else [target])
            request['limit'] = 100
            payload = self.call(request)
            rows = {r['start_minute']: r for r in payload['recommendations']}
            row = rows.get(target)
            observations.append((index, row is not None, row['total_cost'] if row else None,
                                 row['fairness_max_burden'] if row else None))
        self.assertEqual(compiled.to_request(), original)
        return tuple(observations)

    def assert_full_calendar(self, data, observations):
        value, specs, weights = data
        request = value.compiled.to_request()
        # D1's full-calendar oracle ignores publication, so require full coverage.
        for profile in request['profiles'].values():
            for start in request['candidate_starts']:
                self.assertTrue(any(a <= start and start + request['duration'] <= b
                                    for a, b in profile['published']))
        scored = d1_native.NativePreferenceTests().oracle(value.compiled, specs, weights)
        by_start = {start: (cost, burden) for cost, burden, start in scored}
        expected = tuple((i, start in by_start,
                          by_start[start][0] if start in by_start else None,
                          by_start[start][1] if start in by_start else None)
                         for i, start in enumerate(request['candidate_starts']))
        self.assertEqual(observations, expected)
        return scored

    def run_batch(self, value, observations, size, *, compare=False, processes=None, references=0):
        runner = BatchedShadowRunner(self.binary, self.digest, enabled=True, batch_size=size,
                                    production_path=os.environ.get('CDMCS_I3A_PRODUCTION'))
        result = runner.run(value, compare=compare)
        self.assertIsInstance(result, BatchResult, result)
        self.assertEqual(result.status, 'match' if compare else 'cdmcs_only', result)
        self.assertTrue(result.complete)
        self.assertEqual(result.code, '')
        self.assertEqual(result.observations, observations)
        count = len(observations)
        feasible = sum(row[1] for row in observations)
        self.assertEqual((result.candidates, result.evaluated, result.cdmcs_feasible),
                         (count, count, feasible))
        self.assertEqual((result.production_processes, result.production_feasible, result.discrepancies),
                         (count if compare else 0, feasible if compare else 0, 0))
        expected_calls = (count + size - 1)//size if processes is None else processes
        self.assertEqual((result.cdmcs_processes, result.reference_evaluations),
                         (expected_calls, references))
        starts = value.compiled.to_request()['candidate_starts']
        ranked = tuple(row[0] for row in sorted((r for r in observations if r[1]),
                       key=lambda r: (r[2], r[3], starts[r[0]])))
        self.assertEqual(result.ranked_ordinals, ranked)
        self.assertEqual(len(set(ranked)), feasible)
        for index, available, cost, burden in result.observations:
            self.assertIs(type(index), int)
            self.assertIs(type(available), bool)
            if available:
                self.assertIs(type(cost), int)
                self.assertIs(type(burden), int)
            else:
                self.assertIsNone(cost)
                self.assertIsNone(burden)
        self.assertNotIn('observations', result.summary())
        self.assertNotIn('ranked_ordinals', result.summary())
        return result

    def test_boundary_counts_all_sizes_and_one_production_comparison_per_count(self):
        for count in COUNTS:
            data = choices(fixture(count))
            value = data[0]
            reference = self.singleton_reference(value.compiled)
            self.assert_full_calendar(data, reference)
            self.assertEqual(reference, tuple((i, True, 60, 30) for i in range(count)))
            for size in SIZES:
                with self.subTest(count=count, size=size, compare=False):
                    self.run_batch(value, reference, size)
            with self.subTest(count=count, size=100, compare=True):
                if not PRODUCTION:
                    self.skipTest('Explicit CDMCS_I3A_PRODUCTION required for production comparison')
                self.run_batch(value, reference, 100, compare=True)

    def test_positive_delay_size_matrix_counts_reference_only_once(self):
        count = 256
        data = choices(explicit([0] + list(range(1440, 1440 + count - 1)), duration=1),
                       weights=policy(preferred_rate=0, outside_window_rate=0,
                                      outside_day_rate=0, gap_weight=0, delay_per_day=5))
        value = data[0]
        reference = self.singleton_reference(value.compiled)
        self.assert_full_calendar(data, reference)
        self.assertEqual(reference, ((0, True, 0, 0),) +
                         tuple((i, True, 5, 0) for i in range(1, count)))
        for size in SIZES[1:]:
            with self.subTest(size=size):
                calls = 1 + (max(0, count - size) + size - 2)//(size - 1)
                self.run_batch(value, reference, size, processes=calls, references=calls-1)

    def test_size_one_rejects_positive_multiday_but_accepts_same_day_delay(self):
        weights = policy(delay_per_day=5)
        value = choices(explicit([0, 1440], duration=1), weights=weights)[0]
        result = BatchedShadowRunner(self.binary, self.digest, enabled=True,
                                     batch_size=1).run(value, compare=False)
        self.assertEqual((result.status, result.code, result.complete, result.evaluated),
                         ('unsupported', 'BATCH_DELAY_CAPACITY', False, 0))
        data = choices(fixture(2), weights=weights)
        reference = self.singleton_reference(data[0].compiled)
        self.assert_full_calendar(data, reference)
        self.run_batch(data[0], reference, 1)

    def test_global_delay_ranking_counterexample_is_three_five_not_three_zero(self):
        weights = policy(preferred_rate=0, outside_window_rate=0, outside_day_rate=3,
                         gap_weight=0, delay_per_day=5)
        specs = [preference(preferred_weekdays=[2], desired_gap_minutes='indifferent'),
                 preference('professor-A', desired_gap_minutes='indifferent')]
        data = choices(explicit([0, 15, 1440], duration=1), specs=specs, weights=weights)
        value = data[0]
        reference = self.singleton_reference(value.compiled)
        self.assertEqual(reference, ((0, True, 3, 3), (1, True, 3, 3), (2, True, 5, 0)))
        self.assert_full_calendar(data, reference)
        result = self.run_batch(value, reference, 2, processes=2, references=1)
        self.assertEqual(result.ranked_ordinals, (0, 1, 2))
        naive = []
        for start in value.compiled.to_request()['candidate_starts']:
            request = value.compiled.to_request()
            request['candidate_starts'] = [start]
            naive.append(self.call(request)['recommendations'][0]['total_cost'])
        self.assertEqual(naive, [3, 3, 0])
        self.assertEqual(tuple(sorted(range(3), key=lambda i: naive[i])), (2, 0, 1))

    def test_blocked_reference_preserves_delay_and_does_not_become_a_target_twice(self):
        raw = explicit([0] + list(range(1440, 1540)), duration=1)
        raw['commitments'] = [commitment('blocked-origin', ['organizer'], 0, 1)]
        data = choices(raw, weights=policy(preferred_rate=0, outside_window_rate=0,
                                          outside_day_rate=0, gap_weight=0, delay_per_day=5))
        value = data[0]
        reference = self.singleton_reference(value.compiled)
        self.assert_full_calendar(data, reference)
        self.assertEqual(reference, ((0, False, None, None),) +
                         tuple((i, True, 5, 0) for i in range(1, 101)))
        self.run_batch(value, reference, 100, processes=2, references=1)

    def test_over_one_hundred_feasible_rows_are_not_a_capped_recommendation_set(self):
        data = choices(fixture(101))
        value = data[0]
        payload = self.call(value.compiled.to_request(), complete=False)
        self.assertEqual((payload['solutions_evaluated'], payload['returned_count'], payload['truncated']),
                         (101, 100, True))
        expected = tuple((i, True, 60, 30) for i in range(101))
        self.assert_full_calendar(data, expected)
        result = self.run_batch(value, expected, 100)
        self.assertEqual(result.ranked_ordinals[-1], 100)

    def test_batching_cannot_relax_original_candidate_or_full_context_budgets(self):
        with self.assertRaises(PreferenceUnavailable) as caught:
            choices(fixture(257))
        self.assertEqual(caught.exception.code, 'CANDIDATE_BUDGET')
        raw = explicit([0], duration=1, end=6249)
        raw['participants'].extend(participant('professor-' + str(i), end=6249) for i in range(30))
        # The original 32*6250 prefix entries fit; expanded context must not bypass its cap.
        facts = context(raw, coverage=period(0, 6250))
        with self.assertRaises(PreferenceUnavailable) as caught:
            choices(raw, facts=facts)
        self.assertEqual(caught.exception.code, 'COST_CONTEXT_BUDGET')

    def test_sparse_and_all_infeasible_sets_keep_every_original_observation(self):
        for sparse in (True, False):
            raw = fixture(128)
            end = 15*127 + 30
            raw['commitments'] = ([commitment('first-block', ['organizer'], 0, 15*64),
                                   commitment('second-block', ['organizer'], 15*64+30, end-30)]
                                  if sparse else [commitment('all-blocked', ['organizer'], 0, end)])
            data = choices(raw)
            with self.subTest(sparse=sparse):
                reference = self.singleton_reference(data[0].compiled)
                self.assert_full_calendar(data, reference)
                self.assertEqual(tuple(r[0] for r in reference if r[1]), (64, 127) if sparse else ())
                self.run_batch(data[0], reference, 100)

    def test_negative_net_cost_and_positive_part_fairness_are_not_clamped(self):
        for professor_rate, expected in ((0, (-25, 0)), (2, (-5, 20))):
            raw = explicit([55], duration=10, end=180)
            raw['commitments'] = [commitment('before', ['organizer'], 0, 10),
                                  commitment('after', ['organizer'], 110, 120)]
            specs = [preference(), preference('professor-A', preferred_windows=[
                {'weekday': 1, 'start': '09:00', 'end': '09:01'}])]
            data = choices(raw, specs=specs, weights=policy(preferred_rate=0,
                           outside_window_rate=professor_rate, outside_day_rate=professor_rate))
            with self.subTest(professor_rate=professor_rate):
                reference = self.singleton_reference(data[0].compiled)
                self.assertEqual(reference, ((0, True, *expected),))
                self.assert_full_calendar(data, reference)
                self.run_batch(data[0], reference, 1)

    def test_fairness_breaks_cost_ties_but_never_replaces_total_cost(self):
        for outside_window, outside_day, gap, expected, ranking in (
                (1, 2, 16, ((0, True, 2, 2), (1, True, 2, 1)), (1, 0)),
                (2, 3, 17, ((0, True, 3, 3), (1, True, 4, 2)), (0, 1))):
            raw = explicit([0, 1440], duration=1, end=1470)
            raw['commitments'] = [commitment('Tuesday-before', ['organizer'], 1430-gap-10, 1440-gap)]
            specs = [preference(preferred_weekdays=[2]),
                     preference('professor-A', preferred_weekdays=[1, 2], preferred_windows=[
                         {'weekday': 1, 'start': '09:00', 'end': '09:01'}])]
            data = choices(raw, specs=specs, weights=policy(preferred_rate=0,
                           outside_window_rate=outside_window, outside_day_rate=outside_day))
            with self.subTest(outside_window=outside_window):
                reference = self.singleton_reference(data[0].compiled)
                self.assertEqual(reference, expected)
                self.assert_full_calendar(data, reference)
                self.assertEqual(self.run_batch(data[0], reference, 1).ranked_ordinals, ranking)

    def test_native_costs_above_32_bits_remain_exact_integers(self):
        data = choices(fixture(2), weights=policy(preferred_rate=10**8,
                       outside_window_rate=10**8, outside_day_rate=10**8))
        reference = self.singleton_reference(data[0].compiled)
        self.assertEqual(reference, ((0, True, 6_000_000_000, 3_000_000_000),
                                     (1, True, 6_000_000_000, 3_000_000_000)))
        self.assert_full_calendar(data, reference)
        self.run_batch(data[0], reference, 2)

    def test_neighbors_outside_original_search_preserve_costs_and_ranking(self):
        for side, starts, duration, event, scores in (
                ('left', [0, 10], 10, (-15, -5), (10, 0)),
                ('right', [145, 150], 30, (190, 210), (0, 5))):
            raw = explicit(starts, duration=duration, end=180)
            facts = context(raw, coverage=period(-180, 360), left_boundary='open',
                            right_boundary='open', commitments=[
                                commitment('outside-search', ['organizer'], *event)])
            data = choices(raw, facts=facts, weights=policy(preferred_rate=0,
                           outside_window_rate=0, outside_day_rate=0))
            with self.subTest(side=side):
                original = data[0].compiled.to_request()
                reference = self.singleton_reference(data[0].compiled)
                self.assertEqual(tuple(r[2] for r in reference), scores)
                self.assert_full_calendar(data, reference)
                self.run_batch(data[0], reference, 1)
                self.run_batch(data[0], reference, 2)
                self.assertEqual(data[0].compiled.to_request(), original)

    def test_touching_cross_midnight_events_are_not_merged_for_gap_scoring(self):
        raw = rebase(explicit([25, 40], duration=5, end=180), '2030-01-06T20:45:00+00:00')
        raw['commitments'] = [commitment('Sunday', ['organizer'], 0, 15),
                              commitment('Monday', ['organizer'], 15, 25)]
        for event, (start, end) in zip(raw['commitments'], ((0, 15), (15, 25))):
            event['interval'] = period(start, end, raw['utc_anchor'])
        data = choices(raw, weights=policy(preferred_rate=0, outside_window_rate=0, outside_day_rate=0))
        reference = self.singleton_reference(data[0].compiled)
        self.assertEqual(reference, ((0, True, 15, 15), (1, True, 0, 0)))
        self.assert_full_calendar(data, reference)
        self.assertEqual(self.run_batch(data[0], reference, 1).ranked_ordinals, (1, 0))

    def test_off_grid_cross_midnight_and_valid_dst_factory_cases(self):
        names = {'synthetic-manual-off-grid', 'synthetic-cross-midnight',
                 'synthetic-dst-spring', 'synthetic-dst-fall'}
        selected = [raw for raw in matrix() if raw['snapshot_id'] in names]
        self.assertEqual(len(selected), 4)
        for raw in selected:
            specs = [preference(p['id'], timezone=raw['timezone'], desired_gap_minutes='indifferent',
                     effective={'from': '2026-01-01', 'until': '2031-12-31'},
                     preferred_windows=([{'weekday': 7, 'start': '00:00', 'end': '05:00'}]
                                        if raw['timezone'] == 'Europe/Berlin' else []))
                     for p in raw['participants'] if p['required']]
            data = choices(raw, specs=specs)
            with self.subTest(case=raw['snapshot_id']):
                reference = self.singleton_reference(data[0].compiled)
                self.assert_full_calendar(data, reference)
                self.run_batch(data[0], reference, 2)
                if raw['snapshot_id'] == 'synthetic-manual-off-grid':
                    self.assertEqual(tuple(r[1] for r in reference), (True, False, False, True))
                if raw['timezone'] == 'Europe/Berlin':
                    zone = ZoneInfo(raw['timezone'])
                    universe = data[0].compiled.delay_reference.universe
                    self.assertGreater(len({datetime.fromtimestamp(t, zone).utcoffset() for t in universe}), 1)

    def test_invalid_dst_factory_instants_and_preference_endpoints_are_rejected(self):
        invalid = [raw for raw in matrix() if raw['snapshot_id'] in
                   ('synthetic-invalid-dst-gap', 'synthetic-invalid-dst-fold')]
        self.assertEqual(len(invalid), 2)
        for raw in invalid:
            with self.subTest(case=raw['snapshot_id']), self.assertRaises(AdmissionError):
                choices(raw)
        for anchor in ('2030-03-31T00:00:00+00:00', '2030-10-27T00:00:00+00:00'):
            raw = rebase(explicit([0, 60, 120], end=180), anchor)
            raw['timezone'] = 'Europe/Berlin'
            specs = [preference(p['id'], timezone=raw['timezone'], preferred_windows=[
                {'weekday': 7, 'start': '02:15', 'end': '04:00'}]) for p in raw['participants']]
            with self.subTest(anchor=anchor), self.assertRaises(PreferenceUnavailable) as caught:
                choices(raw, specs=specs)
            self.assertEqual(caught.exception.code, 'AMBIGUOUS_OR_NONEXISTENT_PREFERENCE_WINDOW')

    @unittest.skipUnless(PRODUCTION, 'Explicit CDMCS_I3A_PRODUCTION required for actual I3c comparison')
    def test_original_i3c_aggregate_feasibility_is_independent_of_top_k(self):
        raw = fixture(101)
        value = choices(raw)[0]
        legacy = ShadowRunner(self.binary, self.digest, enabled=True,
                              production_path=os.environ['CDMCS_I3A_PRODUCTION']).run(value.scope)
        self.assertEqual((legacy.status, legacy.complete, legacy.candidates, legacy.evaluated,
                          legacy.cdmcs_feasible, legacy.production_feasible, legacy.discrepancies),
                         ('match', True, 101, 101, 101, 101, 0))
        result = self.run_batch(value, tuple((i, True, 60, 30) for i in range(101)), 100)
        self.assertEqual(result.cdmcs_feasible, legacy.cdmcs_feasible)

    @unittest.skipUnless(PRODUCTION, 'Explicit CDMCS_I3A_PRODUCTION required for paired legacy scores')
    def test_original_i3c_raw_scores_only_match_on_compatible_explicit_profiles(self):
        raw = fixture(8)
        raw['commitments'] = [commitment('shared-class', ['organizer', 'professor-A'], 45, 60)]
        for person in raw['participants']:
            person['preference'] = {'base_rate': 0, 'rate_bands': [], 'preferred_break': 15,
                                    'gap_weight': 1, 'nearby_limit': 120,
                                    'source': 'synthetic-D2-compatible-explicit-zero-rate'}
        data = choices(raw, weights=policy(preferred_rate=0, outside_window_rate=0, outside_day_rate=0))
        value = data[0]
        reference = self.singleton_reference(value.compiled)
        self.assert_full_calendar(data, reference)
        captured, production_calls = [], []

        def capture(command, request, **limits):
            call = execute(command, request, **limits)
            if request['operation'] == 'cdmcs_schedule_v1':
                self.assertEqual(request['delay_per_day'], 0)
                self.assertEqual(len(request['candidate_starts']), 1)
                self.assertIn(validate_cdmcs(call.payload, request), ('feasible', 'infeasible'))
                start = request['candidate_starts'][0]
                index = value.compiled.to_request()['candidate_starts'].index(start)
                rows = call.payload['recommendations']
                captured.append((index, bool(rows), rows[0]['total_cost'] if rows else None,
                                 rows[0]['fairness_max_burden'] if rows else None))
            else:
                self.assertEqual(request['action'], 'validate')
                production_calls.append(request['proposed']['start'])
            return call

        with mock.patch.object(kernel, 'execute', side_effect=capture):
            legacy = ShadowRunner(self.binary, self.digest, enabled=True,
                                  production_path=os.environ['CDMCS_I3A_PRODUCTION']).run(value.scope)
        self.assertEqual((legacy.status, legacy.complete, legacy.evaluated, legacy.discrepancies),
                         ('match', True, 8, 0))
        self.assertEqual(tuple(captured), reference)
        self.assertEqual(len(production_calls), 8)
        self.assertEqual(len(set(production_calls)), 8)
        result = self.run_batch(value, reference, 2, compare=True)
        self.assertEqual((result.cdmcs_feasible, result.production_feasible),
                         (legacy.cdmcs_feasible, legacy.production_feasible))

    @unittest.skipUnless(PRODUCTION, 'Explicit CDMCS_I3A_PRODUCTION required for role/invitee parity')
    def test_generic_organizer_roles_and_known_unavailable_optional_invitee(self):
        for role in ('student', 'professor', 'administrator', 'committee organizer'):
            raw = explicit([0, 15, 31], duration=10, end=90)
            raw['participants'][0]['role_label'] = role
            raw['participants'].append(participant('guest', required=False, published_required=False))
            raw['commitments'] = [commitment('guest-unavailable', ['guest'], 0, 90)]
            data = choices(raw)
            with self.subTest(role=role):
                self.assertNotIn('guest', data[0].compiled.to_request()['required_people'])
                reference = self.singleton_reference(data[0].compiled)
                self.assertEqual(reference, tuple((i, True, 20, 10) for i in range(3)))
                self.assert_full_calendar(data, reference)
                self.run_batch(data[0], reference, 2, compare=True)

    @unittest.skipUnless(PRODUCTION, 'Explicit CDMCS_I3A_PRODUCTION required for multiple calendars')
    def test_four_required_calendars_and_optional_unavailable_invitee_match(self):
        raw = fixture(8)
        raw['participants'].extend((participant('professor-B', end=135),
                                    participant('professor-C', end=135),
                                    participant('guest', required=False, published_required=False)))
        raw['commitments'] = [commitment('B-class', ['professor-B'], 0, 30),
                              commitment('C-class', ['professor-C'], 45, 60),
                              commitment('organizer-class', ['organizer'], 90, 105),
                              commitment('optional-busy', ['guest'], 0, 135)]
        data = choices(raw)
        self.assertEqual(len(data[0].compiled.to_request()['required_people']), 4)
        reference = self.singleton_reference(data[0].compiled)
        self.assertEqual(tuple(row[1] for row in reference),
                         (False, False, False, False, True, False, False, True))
        self.assert_full_calendar(data, reference)
        for size in (1, 2, 8, 100):
            with self.subTest(size=size):
                self.run_batch(data[0], reference, size, compare=True)

    def test_twenty_seeded_cases_match_native_targets_and_full_calendar_recomputation(self):
        rng = random.Random(205646)
        pool = (1, 17, 31, 45, 60, 73, 90, 115, 140, 1430, 1440, 1457, 1490)
        for case in range(20):
            starts = [0] + rng.sample(pool, 7)
            rng.shuffle(starts)
            raw = explicit(starts, duration=rng.choice((1, 5, 10, 30)), end=1530)
            raw['commitments'] = [commitment('shared-class', ['organizer', 'professor-A'], 45, 60),
                                  commitment('later-class', ['organizer'], 100, 115)]
            weights = policy(preferred_rate=rng.randrange(3), outside_window_rate=3, outside_day_rate=6,
                             gap_weight=rng.randrange(5), nearby_limit=rng.choice((0, 15, 120, 180)),
                             delay_per_day=rng.choice((0, 2, 5)))
            specs = [preference(p['id'], preferred_weekdays=[1, 2], desired_gap_minutes=rng.randrange(31),
                     preferred_windows=[{'weekday': 1, 'start': '09:00', 'end': '10:30'},
                                        {'weekday': 2, 'start': '09:00', 'end': '09:30'}])
                     for p in raw['participants']]
            data = choices(raw, specs=specs, weights=weights)
            with self.subTest(case=case):
                reference = self.singleton_reference(data[0].compiled)
                self.assert_full_calendar(data, reference)
                size = (2, 8, 32)[case % 3]
                calls, references = (len(starts)+size-1)//size, 0
                if weights['delay_per_day']:
                    request = data[0].compiled.to_request()
                    days = [request['local_day_index'][t] for t in request['candidate_starts']]
                    first_day_calls = (days.count(days[0])+size-1)//size
                    remaining = max(0, len(starts)-first_day_calls*size)
                    references = (remaining+size-2)//(size-1)
                    calls = first_day_calls+references
                self.run_batch(data[0], reference, size, processes=calls, references=references)


if __name__ == '__main__':
    unittest.main()
