"""Run independent test modules/classes in separate processes with owned schemas.

No tests share Flask globals between processes. Each child uses the standard
phase runner; the combined report verifies discovery and executed counts.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]


def main():
    phase, *modules = sys.argv[1:]
    if not os.environ.get('TEST_DATABASE_URL'):
        raise SystemExit('An isolated TEST_DATABASE_URL is required; database tests must run.')
    modules = modules or sorted(path.stem for path in (ROOT / 'tests').glob('test_*.py'))
    expected = {name:unittest.defaultTestLoader.loadTestsFromName(name).countTestCases() for name in modules}
    output = ROOT / 'docs' / 'ui' / 'student-portal' / phase
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()

    def run(name):
        child_phase = phase + '/modules/' + name.replace('.', '_')
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'tests/ui/run_portal_tests.py'), child_phase, name],
                                cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
        child = ROOT / 'docs/ui/student-portal' / child_phase
        if not (child / 'tests.json').is_file():
            raise RuntimeError(name + ' failed before recording results: ' + result.stderr[-3000:])
        report = json.loads((child / 'tests.json').read_text(encoding='utf-8'))
        report['exitCode'] = result.returncode
        report['expected'] = expected[name]
        print(f"{name}: {report['passed']}/{report['run']} passed; {len(report['skipped'])} skipped", flush=True)
        return name, report, (child / 'tests.txt').read_text(encoding='utf-8')

    reports, details = {}, {}
    with ThreadPoolExecutor(max_workers=int(os.environ.get('PORTAL_TEST_WORKERS', '4'))) as pool:
        futures = [pool.submit(run, name) for name in modules]
        for completed in as_completed(futures):
            name, report, detail = completed.result()
            reports[name], details[name] = report, detail
    aggregate = dict(modules=modules, expected=sum(expected.values()),
        run=sum(r['run'] for r in reports.values()), passed=sum(r['passed'] for r in reports.values()),
        failures=sum(r['failures'] for r in reports.values()), errors=sum(r['errors'] for r in reports.values()),
        skipped=[skip for r in reports.values() for skip in r['skipped']],
        seconds=round(time.monotonic()-started, 2), results=reports)
    (output / 'tests.json').write_text(json.dumps(aggregate, indent=2)+'\n', encoding='utf-8')
    (output / 'tests.txt').write_text('\n'.join(details[name] for name in modules), encoding='utf-8')
    print(json.dumps({k:v for k,v in aggregate.items() if k != 'results'}, indent=2))
    return 0 if all(r['exitCode'] == 0 and r['run'] == r['expected'] for r in reports.values()) else 1


if __name__ == '__main__':
    sys.exit(main())
