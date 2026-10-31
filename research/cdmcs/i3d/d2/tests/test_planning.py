import copy
from dataclasses import replace
import unittest

from research.cdmcs.i3a.fixtures import commitment, participant, period, stamp
from research.cdmcs.i3c.admission import synthetic_fixture, synthetic_projection
from research.cdmcs.i3c.tests.test_shadow import database_projection, response
from research.cdmcs.i3d.d1.contract import PreferenceError, PreferenceUnavailable
from research.cdmcs.i3d.d2.planning import admitted, batches, batch_request, complete_response, prepare
from research.cdmcs.i3d.d2.tests.fixtures import fixture, prepared, policy, preference, context


class PlanningTests(unittest.TestCase):
    def test_every_candidate_is_target_once_for_all_boundary_sizes(self):
        for count in (1, 2, 8, 32, 99, 100, 101, 128, 191, 256):
            value = prepared(fixture(count))
            for size in (1, 2, 8, 32, 99, 100):
                with self.subTest(count=count, size=size):
                    plan = batches(value.compiled, size)
                    self.assertEqual(tuple(i for b in plan for i in b.targets), tuple(range(count)))
                    self.assertTrue(all(0 < len(b.submitted) <= size for b in plan))
                    self.assertEqual(sum(len(b.submitted) for b in plan), count)

    def test_positive_delay_retains_global_reference_without_double_target_count(self):
        value = prepared(fixture(256), weights=policy(delay_per_day=5))
        for size in (2, 8, 32, 99, 100):
            with self.subTest(size=size):
                plan = batches(value.compiled, size)
                self.assertEqual(tuple(i for b in plan for i in b.targets), tuple(range(256)))
                self.assertTrue(any(b.submitted != b.targets for b in plan))
                for batch in plan:
                    self.assertLessEqual(len(batch.submitted), size)
                    self.assertEqual(len(batch.submitted), len(set(batch.submitted)))
                    value.compiled.delay_reference.check_candidates(tuple(
                        value.compiled.delay_reference.universe[i] for i in batch.submitted))

    def test_size_one_cannot_silently_reset_positive_multiday_delay(self):
        value = prepared(fixture(128), weights=policy(delay_per_day=5))
        with self.assertRaises(PreferenceUnavailable) as caught:
            batches(value.compiled, 1)
        self.assertEqual(caught.exception.code, 'BATCH_DELAY_CAPACITY')
        self.assertEqual(len(batches(prepared().compiled, 1)), 8)

    def test_shuffled_noncontiguous_starts_are_exact_not_a_new_grid(self):
        raw = fixture()
        raw['candidates']['starts'] = [stamp(i) for i in (73, 0, 17, 99)]
        value = prepared(raw)
        base = value.compiled.to_request()
        selected = [t for batch in batches(value.compiled, 2)
                    for t in batch_request(base, value.compiled, batch)['candidate_starts']]
        self.assertEqual(selected, [0, 17, 73, 99])

    def test_only_candidate_selection_and_limit_change(self):
        value = prepared(fixture(128), weights=policy(delay_per_day=5))
        base = value.compiled.to_request()
        before = copy.deepcopy(base)
        for batch in batches(value.compiled, 32):
            request = batch_request(base, value.compiled, batch)
            self.assertEqual({k:v for k,v in request.items() if k not in ('candidate_starts','limit')},
                             {k:v for k,v in base.items() if k not in ('candidate_starts','limit')})
        self.assertEqual(base, before)

    def test_invalid_batch_sizes_are_not_coerced(self):
        for size in (0, 101, True, 2.0, '2', None):
            with self.subTest(size=size), self.assertRaises(ValueError):
                batches(prepared().compiled, size)

    def test_input_is_immutable_bound_to_scope_and_costs(self):
        value, other = prepared(), prepared()
        for invalid in (value.scope, replace(value, seal=None), replace(value, scope=other.scope),
                        replace(value, compiled=other.compiled)):
            with self.subTest(kind=type(invalid).__name__), self.assertRaises(ValueError):
                admitted(invalid)
        with self.assertRaises(AttributeError):
            value.compiled = None
        self.assertNotIn('professor', repr(value))

    def test_no_missing_preferences_or_implicit_weights(self):
        for specs in ([], [preference()]):
            with self.assertRaises(PreferenceUnavailable):
                prepared(specs=specs)
        weights = policy(); del weights['delay_per_day']
        with self.assertRaises(PreferenceError):
            prepared(weights=weights)

    def test_database_origin_and_unresolved_calendars_do_not_enter(self):
        projection = synthetic_projection(database_projection(), disposable_fixture=True)
        with self.assertRaises(PreferenceError):
            prepare(projection, [], policy(), context())
        for required in (True, False):
            raw = fixture()
            raw['participants'].append(participant('unknown', required=required, published_required=required))
            raw['participants'][-1]['calendar_state'] = 'unresolved'
            with self.assertRaises(PreferenceUnavailable):
                prepared(raw)

    def test_known_unavailable_invitee_remains_optional(self):
        raw = fixture()
        raw['participants'].append(participant('guest', required=False, published_required=False))
        raw['commitments'] = [commitment('guest-only', ['guest'], 0, 120)]
        value = prepared(raw)
        self.assertNotIn('guest', value.compiled.to_request()['required_people'])

    def test_unsupported_resources_and_overlapping_baseline_rejected(self):
        raw = fixture(); raw['required_resources'] = ['room']
        with self.assertRaises(PreferenceUnavailable): prepared(raw)
        raw = fixture()
        raw['commitments'] = [commitment('a', ['organizer'], 0, 30), commitment('b', ['organizer'], 15, 45)]
        with self.assertRaises(PreferenceUnavailable): prepared(raw)


class ResponseTests(unittest.TestCase):
    def test_only_a_complete_response_licenses_missing_start_as_infeasible(self):
        request = prepared().compiled.to_request()
        request['candidate_starts'] = [0, 15]
        rows = complete_response(response(request), request)
        self.assertEqual(rows, {0: (0, 0)})

    def test_truncated_duplicate_foreign_and_multiple_arrangement_results_fail(self):
        request = prepared().compiled.to_request()
        request['candidate_starts'] = [0, 15]
        normal = response(request)
        invalid = []
        for changes in ({'truncated': True}, {'returned_count': 0}, {'solutions_evaluated': 3},
                        {'status': 'UNRESOLVED_CALENDAR'}, {'returned_count': 2, 'solutions_evaluated': 2,
                         'recommendations': normal['recommendations']*2}):
            invalid.append({**copy.deepcopy(normal), **changes})
        foreign = copy.deepcopy(normal); foreign['recommendations'][0]['start_minute'] = 1
        invalid.append(foreign)
        moved = copy.deepcopy(normal); moved['recommendations'][0]['moved_meeting_id'] = 'not-allowed'
        invalid.append(moved)
        for payload in invalid:
            with self.subTest(keys=list(payload)), self.assertRaises(ValueError):
                complete_response(payload, request)

    def test_count_metadata_cannot_hide_top_k_truncation(self):
        request = prepared(fixture(101)).compiled.to_request()
        with self.assertRaises(ValueError):
            complete_response(response(request, feasible=False), request)
