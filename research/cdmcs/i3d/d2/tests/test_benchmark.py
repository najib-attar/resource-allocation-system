from contextlib import redirect_stderr
import io
import sys
import unittest
from unittest import mock

from research.cdmcs.i3d.d2 import benchmark


class BenchmarkTests(unittest.TestCase):
    def test_fixture_problem_json_is_identical_with_explicit_neutral_preferences(self):
        for count in (1,8,32,128,256):
            raw,specs,policy,context=benchmark.fixture(count)
            self.assertTrue(raw['synthetic'])
            self.assertEqual(len(raw['candidates']['starts']),count)
            self.assertEqual(policy['delay_per_day'],0)
            self.assertEqual(len(specs),2)
            self.assertEqual(context['state'],'complete')

    def test_sample_tail_and_variability_are_reported_not_population_claims(self):
        stats=benchmark.statistics([{'end_to_end_ns':v} for v in (1,2,3,4,10)])
        self.assertEqual((stats['median_ns'],stats['sample_p95_ns'],stats['max_ns']),(3,10,10))
        self.assertGreater(stats['stdev_ns'],0)
        self.assertGreater(stats['coefficient_of_variation'],0)

    def test_cli_rejects_excessive_or_invalid_experiments_before_constructing_runner(self):
        base=['benchmark','--cdmcs','unused','--cdmcs-sha256','0'*64,'--production','unused']
        for extra in (['--candidates','257'],['--batch-size','101'],['--repetitions','0'],
                      ['--candidates','128','128'],['--candidates','256','255','254','253',
                                                '--repetitions','7','--warmups','2']):
            with self.subTest(extra=extra), mock.patch.object(sys,'argv',base+extra), \
                 mock.patch.object(benchmark,'ShadowRunner') as create,redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught: benchmark.main()
                self.assertEqual(caught.exception.code,2)
                create.assert_not_called()
