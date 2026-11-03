"""Run phase-specific, real database regression suites and retain exact results."""
import json
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]

if __name__ == '__main__':
    phase, *modules = sys.argv[1:]
    output = ROOT / 'docs' / 'ui' / 'student-portal' / phase
    output.mkdir(parents=True, exist_ok=True)
    suite = unittest.defaultTestLoader.loadTestsFromNames(modules)
    started = time.monotonic()
    with (output / 'tests.log').open('w', encoding='utf-8') as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    report = dict(modules=modules, run=result.testsRun,
                  passed=result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
                  failures=len(result.failures), errors=len(result.errors),
                  skipped=[dict(test=str(test), reason=reason) for test, reason in result.skipped],
                  seconds=round(time.monotonic()-started, 2))
    (output / 'tests.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    sys.exit(0 if result.wasSuccessful() else 1)
