import copy
from dataclasses import replace
import unittest

from research.cdmcs.i3a.adapter import cdmcs_request, normalize, production_request
from research.cdmcs.i3a.fixtures import commitment, participant, period, rebase, stamp
from research.cdmcs.i3a.snapshot import parse_snapshot
from research.cdmcs.i3d.d1.compiler import compile_preferences
from research.cdmcs.i3d.d1.contract import PreferenceError, PreferenceUnavailable
from research.cdmcs.i3d.d1.tests.fixtures import calendar, compile_case, context, policy, preference


class CompilationTests(unittest.TestCase):
    def test_exact_integer_rates_replace_synthetic_snapshot_defaults(self):
        result = compile_case()
        request = result.to_request()
        self.assertEqual(request['profiles']['organizer']['rate_prefix'], list(range(181)))
        self.assertEqual(request['profiles']['organizer']['preferred_break'], 15)
        self.assertEqual(request['profiles']['organizer']['gap_weight'], 1)
        self.assertEqual(request['replacement_starts'], [])
        self.assertEqual(request['required_resources'], [])
        self.assertEqual(request['delay_per_day'], 0)

    def test_weekday_specific_hours_use_one_nonadditive_rate(self):
        spec = preference(preferred_weekdays=[1], preferred_windows=[
            {'weekday': 1, 'start': '09:00', 'end': '10:00'}])
        request = compile_case(specs=[spec, preference('professor-A')]).to_request()
        self.assertEqual(request['profiles']['organizer']['rate_prefix'][60], 60)
        self.assertEqual(request['profiles']['organizer']['rate_prefix'][-1], 60+120*2)

    def test_outside_preferred_day_is_not_also_an_hour_penalty(self):
        request = compile_case(specs=[preference(preferred_weekdays=[2], preferred_windows=[
            {'weekday': 2, 'start': '09:00', 'end': '10:00'}]), preference('professor-A')]).to_request()
        self.assertEqual(request['profiles']['organizer']['rate_prefix'][-1], 180*4)

    def test_cross_midnight_preferences_count_elapsed_minutes(self):
        value = rebase(calendar(), '2030-01-07T18:00:00+00:00')
        value['horizon']['end'] = '2030-01-07T23:00:00+00:00'
        value['participants'][1]['published'] = [copy.deepcopy(value['horizon'])]
        spec = preference(preferred_weekdays=[1, 2], preferred_windows=[
            {'weekday': 1, 'start': '22:00', 'end': '02:00'}])
        result = compile_case(value, [spec, preference('professor-A')])
        self.assertEqual(result.to_request()['profiles']['organizer']['rate_prefix'][-1], 60*2+240)

    def test_neutral_gap_is_explicit_and_zero_is_a_real_desired_gap(self):
        neutral = compile_case(specs=[preference(desired_gap_minutes='indifferent'), preference('professor-A')])
        self.assertEqual(neutral.to_request()['profiles']['organizer']['gap_weight'], 0)
        zero = compile_case(specs=[preference(desired_gap_minutes=0), preference('professor-A')])
        self.assertEqual(zero.to_request()['profiles']['organizer']['gap_weight'], 1)

    def test_every_owner_is_required_and_duplicates_unknown_owners_fail(self):
        for specs in ([], [preference()], [preference(), preference()],
                      [preference(), preference('professor-A'), preference('unrelated')]):
            with self.subTest(count=len(specs)), self.assertRaises(PreferenceError):
                compile_case(specs=specs)

    def test_unavailable_states_are_not_converted_to_zero(self):
        for state in ('missing', 'unknown', 'unsupported'):
            spec = preference(state=state, effective=None, preferred_weekdays=None,
                              preferred_windows=None, desired_gap_minutes=None)
            with self.assertRaises(PreferenceUnavailable) as caught:
                compile_case(specs=[spec, preference('professor-A')])
            self.assertEqual(caught.exception.code, 'PREFERENCE_'+state.upper())

    def test_database_origin_cannot_enter_compilation_or_export(self):
        snapshot = replace(parse_snapshot(calendar()), origin='authorized_calendar')
        with self.assertRaises(PreferenceError) as caught:
            compile_preferences(snapshot, [], policy(), context())
        self.assertEqual(caught.exception.code, 'SYNTHETIC_ONLY')
        normalized = normalize(snapshot)
        for export in (cdmcs_request, production_request):
            with self.assertRaises(ValueError):
                export(normalized)

    def test_original_objects_and_returned_requests_do_not_mutate_compilation(self):
        value, specs, weights, facts = calendar(), [preference(), preference('professor-A')], policy(), context()
        before = copy.deepcopy((value, specs, weights, facts))
        compiled = compile_case(value, specs, weights, facts)
        compiled.to_request()['profiles'].clear()
        self.assertEqual((value, specs, weights, facts), before)
        self.assertEqual(len(compiled.to_request()['profiles']), 2)
        self.assertNotIn('organizer', repr(compiled))

    def test_canonical_results_ignore_role_labels_dictionary_and_owner_order(self):
        value = calendar()
        first = compile_case(value)
        value['participants'].reverse()
        for person in value['participants']:
            person['role_label'] = 'committee administrator student professor'
        second = compile_case(value, [preference('professor-A'), preference()])
        self.assertEqual(first, second)

    def test_production_grid_anchor_and_manual_off_grid_starts_remain_unchanged(self):
        value = calendar()
        value['horizon'] = period(10, 180)
        value['participants'][1]['published'] = [period(7, 75), period(75, 180)]
        expected = normalize(parse_snapshot(value)).candidates
        self.assertEqual(compile_case(value).delay_reference.universe, expected)
        value['candidates'] = {'mode': 'explicit', 'anchor_participant': 'professor-A', 'starts': [stamp(13)]}
        self.assertEqual(compile_case(value).to_request()['candidate_starts'], [13])

    def test_optional_unavailable_and_unknown_invitees_do_not_become_required(self):
        value = calendar()
        guest = participant('guest', required=False, published_required=False)
        guest['calendar_state'] = 'unresolved'
        value['participants'].append(guest)
        value['commitments'] = [commitment('guest-only', ['guest'], 0, 180)]
        request = compile_case(value).to_request()
        self.assertNotIn('guest', request['required_people'])
        self.assertNotIn('guest', request['profiles'])
        self.assertEqual(request['existing'], [])

    def test_unresolved_required_calendar_remains_unsupported(self):
        value = calendar()
        value['participants'][1]['calendar_state'] = 'unresolved'
        with self.assertRaises(PreferenceUnavailable):
            compile_case(value)

    def test_profiles_must_cover_the_cost_dates_and_share_the_day_index_timezone(self):
        for change in ({'timezone': 'UTC'}, {'effective': {'from': '2030-01-08', 'until': '2031-01-01'}}):
            with self.subTest(change=change), self.assertRaises(PreferenceUnavailable):
                compile_case(specs=[preference(**change), preference('professor-A')])

    def test_touching_original_meetings_are_not_merged(self):
        value = calendar()
        value['commitments'] = [commitment('first', ['professor-A'], 0, 30),
                                commitment('second', ['professor-A'], 30, 60)]
        request = compile_case(value).to_request()
        self.assertEqual([e['id'] for e in request['existing']], ['first', 'second'])
        self.assertEqual([e['duration'] for e in request['existing']], [30, 30])

    def test_overlapping_original_events_are_not_silently_reinterpreted_as_meetings(self):
        value = calendar()
        value['commitments'] = [commitment('first', ['professor-A'], 0, 45),
                                commitment('overlap', ['professor-A'], 30, 60)]
        with self.assertRaises(PreferenceUnavailable) as caught:
            compile_case(value)
        self.assertEqual(caught.exception.code, 'OVERLAPPING_COST_CONTEXT')

    def test_missing_unknown_and_unsupported_context_are_explicit(self):
        for state in ('missing', 'unknown', 'unsupported'):
            with self.assertRaises(PreferenceUnavailable) as caught:
                compile_case(facts=context(state=state))
            self.assertEqual(caught.exception.code, 'COST_CONTEXT_'+state.upper())
        with self.assertRaises(PreferenceUnavailable):
            compile_case(facts=context(complete_for=['organizer']))

    def test_open_boundaries_without_neighbors_fail_closed_even_at_zero_cutoff(self):
        for cutoff in (0, 120):
            with self.subTest(cutoff=cutoff), self.assertRaises(PreferenceUnavailable):
                compile_case(weights=policy(nearby_limit=cutoff), facts=context(left_boundary='open', right_boundary='open'))

    def test_explicit_no_gap_cost_does_not_require_irrelevant_outside_neighbors(self):
        self.assertIsNotNone(compile_case(weights=policy(gap_weight=0),
                                         facts=context(left_boundary='open', right_boundary='open')))

    def test_complete_outside_neighbors_are_kept_without_widening_candidates(self):
        value = calendar()
        facts = context(value, coverage=period(-180, 360), left_boundary='open', right_boundary='open',
                        commitments=[commitment('predecessor', ['organizer'], -15, -5),
                                     commitment('successor', ['organizer'], 190, 210)])
        result = compile_case(value, facts=facts)
        request = result.to_request()
        self.assertEqual(request['horizon_minutes'], 540)
        self.assertEqual(request['candidate_starts'][0], 180)
        self.assertEqual(request['candidate_starts'][-1], 330)
        self.assertEqual([e['start'] for e in request['existing']], [165, 370])
        self.assertEqual(result.delay_reference.universe, normalize(parse_snapshot(value)).candidates)

    def test_context_cannot_erase_or_add_busy_time_inside_the_search(self):
        value = calendar()
        value['commitments'] = [commitment('class', ['organizer'], 0, 30)]
        for facts in (context(value, commitments=[]), context(value, commitments=[
                commitment('class', ['organizer'], 0, 30), commitment('extra', ['organizer'], 40, 50)])):
            with self.subTest(facts=facts), self.assertRaises(PreferenceUnavailable):
                compile_case(value, facts=facts)

    def test_context_never_clips_a_partly_known_event(self):
        facts = context(commitments=[commitment('too-early', ['organizer'], -30, -10)])
        with self.assertRaises(PreferenceUnavailable) as caught:
            compile_case(facts=facts)
        self.assertEqual(caught.exception.code, 'UNCLIPPED_EVENT_CONTEXT_REQUIRED')

    def test_empty_candidate_universe_has_no_fabricated_delay_origin(self):
        value = calendar()
        value['candidates'] = {'mode': 'explicit', 'anchor_participant': 'professor-A', 'starts': []}
        with self.assertRaises(PreferenceUnavailable) as caught:
            compile_case(value)
        self.assertEqual(caught.exception.code, 'EMPTY_CANDIDATE_UNIVERSE')

    def test_full_context_horizon_and_candidate_budgets_are_bounded(self):
        with self.assertRaises(PreferenceUnavailable):
            compile_case(facts=context(coverage=period(-1, 32*1440)))
        value = calendar()
        value['horizon'] = period(0, 4000)
        value['participants'][1]['published'] = [period(0, 4000)]
        with self.assertRaises(PreferenceUnavailable) as caught:
            compile_case(value)
        self.assertEqual(caught.exception.code, 'CANDIDATE_BUDGET')

    def test_exact_prefix_bound_and_one_minute_overflow(self):
        for length in (10000, 10001):
            value = calendar()
            value['horizon'] = period(0, length)
            value['participants'][1]['published'] = [period(0, length)]
            value['candidates'] = {'mode': 'explicit', 'anchor_participant': 'professor-A', 'starts': [stamp()]}
            weights = policy(preferred_rate=10**8, outside_window_rate=10**8, outside_day_rate=10**8)
            if length == 10000:
                self.assertEqual(compile_case(value, weights=weights).to_request()['profiles']['organizer']['rate_prefix'][-1], 10**12)
            else:
                with self.assertRaises(PreferenceUnavailable) as caught:
                    compile_case(value, weights=weights)
                self.assertEqual(caught.exception.code, 'PREFIX_COST_BOUND')

    def test_shared_resource_and_unprotected_context_are_not_enabled(self):
        value = calendar()
        value['required_resources'] = ['room']
        with self.assertRaises(PreferenceUnavailable):
            compile_case(value)
        facts = context(commitments=[{**commitment('class', ['organizer'], 0, 30), 'protected': False}])
        with self.assertRaises(PreferenceError):
            compile_case(facts=facts)

    def test_total_prefix_entries_are_checked_before_compiling_large_calendars(self):
        for length in (39999, 40000):
            value = calendar()
            value['horizon'] = period(0, length)
            value['participants'].extend(participant('prof-'+str(i), end=length) for i in range(3))
            value['participants'][1]['published'] = [period(0, length)]
            value['candidates'] = {'mode': 'explicit', 'anchor_participant': 'professor-A', 'starts': [stamp()]}
            if length == 39999:
                result = compile_case(value).to_request()
                self.assertEqual(sum(len(p['rate_prefix']) for p in result['profiles'].values()), 200000)
            else:
                with self.assertRaises(PreferenceUnavailable) as caught:
                    compile_case(value)
                self.assertEqual(caught.exception.code, 'COST_CONTEXT_BUDGET')

    def test_context_membership_budget_rejects_excessive_group_fanout(self):
        value = calendar()
        value['participants'].extend(participant('prof-'+str(i)) for i in range(9))
        members = [p['id'] for p in value['participants']]
        facts = context(value, coverage=period(0, 2000), commitments=[
            commitment('group-'+str(i), members, i, i+1) for i in range(1000)])
        with self.assertRaises(PreferenceError) as caught:
            compile_case(value, facts=facts)
        self.assertEqual(caught.exception.code, 'CONTEXT_MEMBERSHIP_BUDGET')

    def test_error_messages_do_not_contain_calendar_markers(self):
        facts = context()
        facts['PRIVATE-CALENDAR-MARKER'] = 'PRIVATE-CALENDAR-MARKER'
        with self.assertRaises(PreferenceError) as caught:
            compile_case(facts=facts)
        self.assertNotIn('PRIVATE', str(caught.exception))


class DelayContractTests(unittest.TestCase):
    def case(self, weight):
        value = calendar()
        value['horizon'] = period(0, 1470)
        value['participants'][1]['published'] = [period(0, 1470)]
        value['candidates'] = {'mode': 'explicit', 'anchor_participant': 'professor-A',
                                'starts': [stamp(0), stamp(15), stamp(1440)]}
        return compile_case(value, weights=policy(delay_per_day=weight))

    def test_global_reference_is_full_universe_and_cannot_reset_per_day(self):
        result = self.case(5)
        reference = result.delay_reference
        reference.check_candidates(reference.universe)
        reference.check_candidates((reference.universe[1],))
        with self.assertRaises(PreferenceUnavailable) as caught:
            reference.check_candidates((reference.universe[-1],))
        self.assertEqual(caught.exception.code, 'GLOBAL_DELAY_REFERENCE')
        self.assertEqual(result.to_request()['candidate_starts'], [0, 15, 1440])

    def test_zero_delay_is_explicit_and_the_reference_is_still_recorded(self):
        reference = self.case(0).delay_reference
        reference.check_candidates((reference.universe[-1],))
        self.assertEqual(reference.weight, 0)
        self.assertIsInstance(reference.earliest_day, int)

    def test_no_batch_serializer_or_automatic_cost_correction_is_implemented(self):
        result = self.case(5)
        with self.assertRaises(TypeError):
            result.to_request((result.delay_reference.universe[-1],))
        for bad in ((), (True,), (0,), (result.delay_reference.universe[0],)*2):
            with self.subTest(bad=bad), self.assertRaises(PreferenceError):
                result.delay_reference.check_candidates(bad)


class TimezoneTests(unittest.TestCase):
    def case(self, anchor, minutes, start='01:00', end='04:00'):
        value = rebase(calendar(), anchor)
        value['timezone'] = 'Europe/Berlin'
        value['horizon']['end'] = stamp(minutes, anchor)
        value['participants'][1]['published'] = [copy.deepcopy(value['horizon'])]
        spec = preference(timezone='Europe/Berlin', preferred_weekdays=[7], preferred_windows=[
            {'weekday': 7, 'start': start, 'end': end}])
        return compile_case(value, [spec, preference('professor-A', timezone='Europe/Berlin')])

    def test_spring_transition_counts_actual_minutes_not_wall_minutes(self):
        request = self.case('2030-03-31T00:00:00+00:00', 180).to_request()
        self.assertEqual(request['profiles']['organizer']['rate_prefix'][-1], 120+60*2)

    def test_fall_transition_applies_same_clock_preference_to_both_folds(self):
        request = self.case('2030-10-26T23:00:00+00:00', 240).to_request()
        self.assertEqual(request['profiles']['organizer']['rate_prefix'][-1], 240)

    def test_ambiguous_or_nonexistent_window_endpoints_fail_explicitly(self):
        for anchor in ('2030-03-31T00:00:00+00:00', '2030-10-26T23:00:00+00:00'):
            with self.subTest(anchor=anchor), self.assertRaises(PreferenceUnavailable) as caught:
                self.case(anchor, 180, '02:15', '03:30')
            self.assertEqual(caught.exception.code, 'AMBIGUOUS_OR_NONEXISTENT_PREFERENCE_WINDOW')
