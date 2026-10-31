"""Explicit synthetic C++ execution and independent full-calendar score witnesses."""

from datetime import datetime
import os
from pathlib import Path
import random
import unittest
from zoneinfo import ZoneInfo

from research.cdmcs.i3a.adapter import normalize, production_request
from research.cdmcs.i3a.execution import validate_cdmcs
from research.cdmcs.i3a.fixtures import commitment, period, rebase, stamp
from research.cdmcs.i3a.snapshot import parse_snapshot
from research.cdmcs.i3c.process import execute
from research.cdmcs.i3d.d1.contract import PreferenceUnavailable
from research.cdmcs.i3d.d1.tests.fixtures import calendar, compile_case, context, policy, preference
from web.backend_executable import file_sha256, resolve_backend_executable
from web.engine_gateway import validate_appointment_result


def reference_rate(instant, spec, weights):
    local = datetime.fromtimestamp(instant, ZoneInfo(spec['timezone']))
    weekday, minute = local.isoweekday(), local.hour*60+local.minute
    if spec['preferred_weekdays'] and weekday not in spec['preferred_weekdays']:
        return weights['outside_day_rate']
    if not spec['preferred_windows']:
        return weights['preferred_rate']
    for window in spec['preferred_windows']:
        start = int(window['start'][:2])*60+int(window['start'][3:])
        end = int(window['end'][:2])*60+int(window['end'][3:])
        if end > start:
            preferred = weekday == window['weekday'] and start <= minute < end
        else:
            preferred = ((weekday == window['weekday'] and minute >= start)
                         or (weekday == window['weekday'] % 7+1 and minute < end))
        if preferred:
            return weights['preferred_rate']
    return weights['outside_window_rate']


def full_score(events, owner, spec, weights, timezone):
    """Test oracle: no compiler bands/prefixes or incremental neighbor code used."""
    events = sorted((a, b) for a, b, people in events if owner in people)
    result = sum(reference_rate(t, spec, weights) for a, b in events for t in range(a, b, 60))
    if spec['desired_gap_minutes'] != 'indifferent':
        # The model uses both EVENT START dates, not gap endpoint dates.
        for (a, b), (c, _) in zip(events, events[1:]):
            gap = (c-b)//60
            if (gap <= weights['nearby_limit'] and datetime.fromtimestamp(a, timezone).date()
                    == datetime.fromtimestamp(c, timezone).date()):
                result += abs(gap-spec['desired_gap_minutes'])*weights['gap_weight']
    return result


@unittest.skipUnless(os.environ.get('CDMCS_I3A_BINARY') and os.environ.get('CDMCS_I3A_SHA256'),
                     'Pinned native CDMCS binary required')
class NativePreferenceTests(unittest.TestCase):
    def call(self, request):
        path, expected = os.environ['CDMCS_I3A_BINARY'], os.environ['CDMCS_I3A_SHA256']
        self.assertEqual(file_sha256(path), expected)
        result = execute([path], request, timeout=5, memory_bytes=256*1024**2,
                         input_limit=4*1024**2, output_limit=64*1024).payload
        validate_cdmcs(result, request)
        return result

    def oracle(self, compiled, specs, weights):
        request = compiled.to_request()
        anchor = compiled.delay_reference.universe[0]-request['candidate_starts'][0]*60
        events = [(anchor+e['start']*60, anchor+(e['start']+e['duration'])*60, e['people'])
                  for e in request['existing']]
        by_owner = {p['owner']: p for p in specs}
        timezone = ZoneInfo(compiled.delay_reference.timezone)
        before = {p: full_score(events, p, by_owner[p], weights, timezone) for p in request['required_people']}
        expected = []
        for minute in request['candidate_starts']:
            a, b = anchor+minute*60, anchor+(minute+request['duration'])*60
            if any(a < end and start < b and set(people).intersection(request['required_people'])
                   for start, end, people in events):
                continue
            after = events+[(a, b, request['required_people'])]
            burdens = [full_score(after, p, by_owner[p], weights, timezone)-before[p]
                       for p in request['required_people']]
            cost = sum(burdens)+(datetime.fromtimestamp(a, timezone).date().toordinal()
                                 - compiled.delay_reference.earliest_day)*weights['delay_per_day']
            expected.append((cost, max(0, *burdens), minute))
        return sorted(expected)

    def assert_scores(self, compiled, specs, weights):
        result = self.call(compiled.to_request())
        actual = [(r['total_cost'], r['fairness_max_burden'], r['start_minute']) for r in result['recommendations']]
        self.assertEqual(actual, self.oracle(compiled, specs, weights)[:100])
        return result

    def test_complete_neighbor_changes_ranking_in_the_actual_cpp_engine(self):
        value = calendar()
        value['duration_minutes'] = 10
        value['candidates'] = {'mode': 'explicit', 'anchor_participant': 'professor-A', 'starts': [stamp(0), stamp(10)]}
        facts = context(value, coverage=period(-180, 360), left_boundary='open', right_boundary='open',
                        commitments=[commitment('earlier-meeting', ['organizer'], -15, -5)])
        weights = policy(preferred_rate=0, outside_window_rate=0, outside_day_rate=0)
        specs = [preference(), preference('professor-A')]
        compiled = compile_case(value, specs, weights, facts)
        result = self.assert_scores(compiled, specs, weights)
        self.assertEqual([(r['start_minute'], r['total_cost']) for r in result['recommendations']], [(190, 0), (180, 10)])

    def test_touching_cross_midnight_events_preserve_the_true_event_start_day(self):
        value = rebase(calendar(), '2030-01-06T20:45:00+00:00')
        value['duration_minutes'] = 5
        value['commitments'] = [commitment('late-Sunday', ['organizer'], 0, 15),
                                commitment('early-Monday', ['organizer'], 15, 25)]
        value['candidates'] = {'mode': 'explicit', 'anchor_participant': 'professor-A',
                                'starts': [stamp(25, value['utc_anchor'])]}
        # Rebase only the explicitly built original events, not unrelated calendars.
        for row, (a, b) in zip(value['commitments'], ((0, 15), (15, 25))):
            row['interval'] = period(a, b, value['utc_anchor'])
        weights = policy(preferred_rate=0, outside_window_rate=0, outside_day_rate=0)
        specs = [preference(), preference('professor-A')]
        result = self.assert_scores(compile_case(value, specs, weights), specs, weights)
        self.assertEqual(result['recommendations'][0]['total_cost'], 15)

    def test_global_day_delay_counterexample_and_guard_are_native_verified(self):
        value = calendar()
        value['duration_minutes'] = 1
        value['horizon'] = period(0, 1441)
        value['participants'][1]['published'] = [period(0, 1441)]
        value['candidates'] = {'mode': 'explicit', 'anchor_participant': 'professor-A', 'starts': [stamp(0), stamp(1440)]}
        weights = policy(preferred_rate=0, outside_window_rate=0, outside_day_rate=3, gap_weight=0, delay_per_day=5)
        specs = [preference(preferred_weekdays=[2], desired_gap_minutes='indifferent'),
                 preference('professor-A', desired_gap_minutes='indifferent')]
        compiled = compile_case(value, specs, weights)
        result = self.assert_scores(compiled, specs, weights)
        self.assertEqual([r['total_cost'] for r in result['recommendations']], [3, 5])
        with self.assertRaises(PreferenceUnavailable):
            compiled.delay_reference.check_candidates((compiled.delay_reference.universe[-1],))
        # This deliberately invalid CONTRACT scope demonstrates why D2 must not
        # silently narrow a v1 request. No narrowing API is provided by D1.
        wrong_scope = compiled.to_request()
        wrong_scope['candidate_starts'] = [1440]
        self.assertEqual(self.call(wrong_scope)['recommendations'][0]['total_cost'], 0)

    def test_weekly_rates_and_gap_costs_match_independent_full_recomputation(self):
        rng = random.Random(7301)
        for case in range(20):
            value = calendar()
            value['duration_minutes'] = 10
            value['commitments'] = [commitment('class', ['organizer', 'professor-A'], 45, 60),
                                    commitment('next', ['organizer'], 100, 115)]
            value['candidates'] = {'mode': 'explicit', 'anchor_participant': 'professor-A',
                                    'starts': [stamp(t) for t in (0, 15, 30, 60, 75, 90, 115, 140)]}
            weights = policy(preferred_rate=rng.randrange(3), outside_window_rate=3,
                             outside_day_rate=6, gap_weight=rng.randrange(5), nearby_limit=rng.randrange(121))
            specs = [preference(desired_gap_minutes=rng.randrange(31), preferred_weekdays=[1], preferred_windows=[
                {'weekday': 1, 'start': '09:00', 'end': '10:30'}]), preference('professor-A', desired_gap_minutes=rng.randrange(31))]
            with self.subTest(case=case):
                self.assert_scores(compile_case(value, specs, weights), specs, weights)

    def test_original_model_cutoff_and_net_burden_are_not_replaced(self):
        value = calendar()
        value['duration_minutes'] = 1
        value['commitments'] = [commitment('earlier', ['organizer'], 0, 10)]
        value['candidates'] = {'mode': 'explicit', 'anchor_participant': 'professor-A',
                                'starts': [stamp(t) for t in (10, 40, 130, 131)]}
        weights = policy(preferred_rate=0, outside_window_rate=0, outside_day_rate=0)
        specs = [preference(), preference('professor-A')]
        result = self.assert_scores(compile_case(value, specs, weights), specs, weights)
        self.assertEqual({r['start_minute']: r['total_cost'] for r in result['recommendations']}, {10: 15, 40: 15, 130: 105, 131: 0})

    def test_64_bit_costs_are_exact_not_floats(self):
        weights = policy(preferred_rate=10**8, outside_window_rate=10**8, outside_day_rate=10**8,
                         gap_weight=100000, exception_fee=10**7, move_fixed_cost=10**7, move_participant_cost=10**7)
        result = self.call(compile_case(weights=weights).to_request())
        self.assertEqual(result['recommendations'][0]['total_cost'], 6_000_000_000)
        self.assertEqual(result['recommendations'][0]['fairness_max_burden'], 3_000_000_000)

    def test_successor_outside_search_is_included_in_native_gap_cost(self):
        value = calendar()
        value['candidates'] = {'mode': 'explicit', 'anchor_participant': 'professor-A',
                                'starts': [stamp(145), stamp(150)]}
        facts = context(value, coverage=period(-180, 360), left_boundary='open', right_boundary='open',
                        commitments=[commitment('after-search', ['organizer'], 190, 210)])
        weights = policy(preferred_rate=0, outside_window_rate=0, outside_day_rate=0)
        specs = [preference(), preference('professor-A')]
        result = self.assert_scores(compile_case(value, specs, weights, facts), specs, weights)
        self.assertEqual([(r['start_minute'], r['total_cost']) for r in result['recommendations']], [(325, 0), (330, 5)])

    def test_negative_net_cost_is_not_clamped_and_fairness_is_positive_part(self):
        value = calendar()
        value['duration_minutes'] = 10
        value['commitments'] = [commitment('before', ['organizer'], 0, 10),
                                commitment('after', ['organizer'], 110, 120)]
        value['candidates'] = {'mode': 'explicit', 'anchor_participant': 'professor-A', 'starts': [stamp(55)]}
        weights = policy(preferred_rate=0, outside_window_rate=0, outside_day_rate=0)
        specs = [preference(), preference('professor-A')]
        row = self.assert_scores(compile_case(value, specs, weights), specs, weights)['recommendations'][0]
        self.assertEqual((row['total_cost'], row['fairness_max_burden']), (-25, 0))

    def fairness_case(self, outside_window, outside_day, gap):
        value = calendar()
        value['duration_minutes'] = 1
        value['horizon'] = period(0, 1470)
        value['participants'][1]['published'] = [period(0, 1470)]
        value['commitments'] = [commitment('Tuesday-before', ['organizer'], 1430-gap-10, 1440-gap)]
        value['candidates'] = {'mode': 'explicit', 'anchor_participant': 'professor-A', 'starts': [stamp(0), stamp(1440)]}
        weights = policy(preferred_rate=0, outside_window_rate=outside_window, outside_day_rate=outside_day)
        specs = [preference(preferred_weekdays=[2]), preference('professor-A', preferred_weekdays=[1, 2],
                    preferred_windows=[{'weekday': 1, 'start': '09:00', 'end': '09:01'}])]
        return self.assert_scores(compile_case(value, specs, weights), specs, weights)['recommendations']

    def test_fairness_breaks_total_cost_ties_before_earliest_start(self):
        rows = self.fairness_case(1, 2, 16)
        self.assertEqual([(r['total_cost'], r['fairness_max_burden'], r['start_minute']) for r in rows],
                         [(2, 1, 1440), (2, 2, 0)])

    def test_fairness_does_not_replace_total_cost_as_primary_objective(self):
        rows = self.fairness_case(2, 3, 17)
        self.assertEqual([(r['total_cost'], r['fairness_max_burden'], r['start_minute']) for r in rows],
                         [(3, 3, 0), (4, 2, 1440)])

    def test_dst_compiled_rates_match_native_full_calendar_scores(self):
        value = rebase(calendar(), '2030-03-31T00:00:00+00:00')
        value['timezone'] = 'Europe/Berlin'
        value['candidates'] = {'mode': 'explicit', 'anchor_participant': 'professor-A',
                                'starts': [stamp(t, value['utc_anchor']) for t in (0, 60, 120)]}
        specs = [preference(timezone='Europe/Berlin', preferred_weekdays=[7], preferred_windows=[
            {'weekday': 7, 'start': '01:00', 'end': '04:00'}]), preference('professor-A', timezone='Europe/Berlin')]
        weights = policy()
        result = self.assert_scores(compile_case(value, specs, weights), specs, weights)
        self.assertEqual([r['total_cost'] for r in result['recommendations']], [60, 60, 90])

    def test_original_overnight_endpoints_span_a_missing_midnight(self):
        value = rebase(calendar(), '2018-11-04T01:00:00+00:00')
        value['timezone'] = 'America/Sao_Paulo'
        effective = {'from': '2018-11-01', 'until': '2018-11-06'}
        specs = [preference(timezone=value['timezone'], effective=effective, preferred_weekdays=[6, 7],
                            preferred_windows=[{'weekday': 6, 'start': '23:00', 'end': '03:00'}]),
                 preference('professor-A', timezone=value['timezone'], effective=effective)]
        weights = policy()
        result = self.assert_scores(compile_case(value, specs, weights), specs, weights)
        self.assertEqual((result['recommendations'][0]['start_minute'],
                          result['recommendations'][0]['total_cost']), (60, 60))

    def test_repeated_compilation_and_native_output_are_deterministic(self):
        first = compile_case()
        self.assertEqual(self.call(first.to_request()), self.call(compile_case().to_request()))

    def test_delay_uses_earliest_submitted_candidate_not_first_feasible_candidate(self):
        value = calendar()
        value['horizon'] = period(0, 1470)
        value['participants'][1]['published'] = [period(0, 1470)]
        value['commitments'] = [commitment('unavailable-first-day', ['organizer'], 0, 30)]
        value['candidates'] = {'mode': 'explicit', 'anchor_participant': 'professor-A', 'starts': [stamp(0), stamp(1440)]}
        weights = policy(preferred_rate=0, outside_window_rate=0, outside_day_rate=0, gap_weight=0, delay_per_day=5)
        specs = [preference(), preference('professor-A')]
        result = self.assert_scores(compile_case(value, specs, weights), specs, weights)
        self.assertEqual([(r['start_minute'], r['total_cost']) for r in result['recommendations']], [(1440, 5)])

    def test_top_k_output_does_not_shrink_the_declared_candidate_universe(self):
        value = calendar()
        value['horizon'] = period(0, 1530)
        value['participants'][1]['published'] = [period(0, 1530)]
        value['candidates'] = {'mode': 'explicit', 'anchor_participant': 'professor-A',
                                'starts': [stamp(15*i) for i in range(101)]}
        compiled = compile_case(value)
        result = self.call(compiled.to_request())
        self.assertEqual((result['solutions_evaluated'], result['returned_count'], result['truncated']), (101, 100, True))
        self.assertEqual(len(compiled.delay_reference.universe), 101)
        self.assertEqual(len(compiled.to_request()['candidate_starts']), 101)

    def test_valid_but_empty_feasible_set_is_not_a_compilation_failure(self):
        value = calendar()
        value['commitments'] = [commitment('fully-booked', ['organizer'], 0, 180)]
        result = self.call(compile_case(value).to_request())
        self.assertEqual(result['status'], 'NO_FEASIBLE_PROPOSAL')
        self.assertEqual(result['recommendations'], [])

    def test_all_organizer_role_labels_use_one_unchanged_compiler_and_engine(self):
        expected = self.call(compile_case().to_request())
        for role in ('student', 'professor', 'administrator', 'committee organizer'):
            value = calendar()
            value['participants'][0]['role_label'] = role
            with self.subTest(role=role):
                self.assertEqual(self.call(compile_case(value).to_request()), expected)

    @unittest.skipUnless(os.environ.get('CDMCS_I3A_PRODUCTION'), 'Production binary explicitly required')
    def test_feasibility_matches_unchanged_production_on_identical_intervals(self):
        value = calendar()
        value['commitments'] = [commitment('busy', ['professor-A'], 30, 60)]
        compiled = compile_case(value)
        result = self.call(compiled.to_request())
        feasible = {r['start_minute'] for r in result['recommendations']}
        normalized = normalize(parse_snapshot(value))
        production = resolve_backend_executable(Path(__file__).resolve().parents[5], os.environ['CDMCS_I3A_PRODUCTION'])
        for stamp_value in normalized.candidates:
            request = production_request(normalized, stamp_value)
            response = execute([str(production.path), '--appointments-json'], request,
                timeout=5, memory_bytes=256*1024**2, input_limit=4*1024**2, output_limit=64*1024).payload
            validate_appointment_result(response, request)
            self.assertEqual(response['feasible'], (stamp_value-normalized.snapshot.anchor)//60 in feasible)
