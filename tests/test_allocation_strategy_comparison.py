"""Verify the real offline comparison uses all requests for all five strategies."""
from unittest import TestCase, mock

from scripts.compare_allocation_strategies import compare
from web.persistence.models import STRATEGIES


class AllocationStrategyComparisonTests(TestCase):
    def test_real_engine_comparison_counts_deterministic_synthetic_decisions(self):
        with mock.patch.dict('os.environ', {'DATABASE_URL': 'invalid-for-offline-comparison'}):
            report = compare(repeats=2)
        self.assertEqual(report['counts']['requests'], 120)
        self.assertEqual(tuple(report['strategies']), STRATEGIES)
        self.assertRegex(report['corpusSha256'], r'^[a-f0-9]{64}$')
        self.assertRegex(report['build']['binary_sha256'], r'^[a-f0-9]{64}$')
        for name, result in report['strategies'].items():
            with self.subTest(strategy=name):
                self.assertEqual(result['approved'] + result['rejected'], 120)
                self.assertEqual(result['rejected'], len(result['rejections']))
                self.assertEqual(result['rejected'], sum(result['rejectionCounts'].values()))
                self.assertEqual(len({row['requestId'] for row in result['rejections']}), result['rejected'])
                self.assertTrue(all(row['code'] and row['reason'] for row in result['rejections']))
                self.assertEqual(sum(sum(counts.values()) for counts in result['byType'].values()), 120)
                self.assertEqual(len(result['gatewaySamplesMs']), 2)
                self.assertGreater(result['gatewayMedianMs'], 0)
                self.assertGreaterEqual(result['allocationSegments'], result['approved'])
        for name in STRATEGIES[2:]:
            with self.subTest(strategy=name):
                self.assertNotIn(3, [row['requestId'] for row in report['strategies'][name]['rejections']])

    def test_invalid_repetition_count_fails_before_engine_execution(self):
        for value in (False, 0, 31):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, '1 to 30'):
                compare(repeats=value)
