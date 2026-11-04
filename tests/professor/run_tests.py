"""Run selected existing suites, preserving exact Professor Services evidence."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tests'), str(ROOT)]


def main():
    if sys.argv[1] == '--parallel':
        return parallel(sys.argv[2], sys.argv[3:])
    args = sys.argv[1:]
    child = args[0] == '--child'
    if child:
        args = args[1:]
    output = ROOT / ('build/professor-tests' if child else 'docs/professor-services') / args[0]
    output.mkdir(parents=True, exist_ok=True)
    suite = unittest.defaultTestLoader.loadTestsFromNames(args[1:])
    expected = suite.countTestCases()
    started = time.monotonic()
    with (output / 'tests.txt').open('w', encoding='utf-8') as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    report = dict(modules=args[1:], expected=expected, run=result.testsRun,
        passed=result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
        failures=len(result.failures), errors=len(result.errors),
        skipped=[dict(test=str(test), reason=reason) for test, reason in result.skipped],
        seconds=round(time.monotonic()-started, 2))
    (output / 'tests.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0 if result.wasSuccessful() and expected == result.testsRun else 1


def parallel(phase, modules):
    if not os.environ.get('TEST_DATABASE_URL'):
        raise RuntimeError('Real PostgreSQL must be configured, not silently skipped.')
    modules = modules or sorted(p.stem for p in (ROOT/'tests').glob('test_*.py'))
    output = ROOT/'docs/professor-services'/phase
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    def run(module):
        label = phase+'/'+module
        result = subprocess.run([sys.executable,'-B',__file__,'--child',label,module],
            cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        child = ROOT/'build/professor-tests'/label
        if not (child/'tests.json').exists():
            raise RuntimeError(module+' failed without a report: '+result.stderr[-3000:])
        report = json.loads((child/'tests.json').read_text(encoding='utf-8'))
        report['exitCode'] = result.returncode
        print(f"{module}: {report['passed']}/{report['run']} passed; {len(report['skipped'])} skipped",flush=True)
        return module, report, (child/'tests.txt').read_text(encoding='utf-8')
    reports, logs = {}, {}
    with ThreadPoolExecutor(max_workers=int(os.environ.get('PROFESSOR_TEST_WORKERS','4'))) as pool:
        for future in as_completed([pool.submit(run, module) for module in modules]):
            module, report, log = future.result()
            reports[module], logs[module] = report, log
    report = dict(modules=modules, expected=sum(r['expected'] for r in reports.values()),
        run=sum(r['run'] for r in reports.values()), passed=sum(r['passed'] for r in reports.values()),
        failures=sum(r['failures'] for r in reports.values()), errors=sum(r['errors'] for r in reports.values()),
        skipped=[skip for r in reports.values() for skip in r['skipped']],
        seconds=round(time.monotonic()-started,2), results=reports)
    (output/'tests.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    (output/'tests.txt').write_text('\n'.join(logs[m] for m in modules),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='results'},indent=2))
    return 0 if all(r['exitCode']==0 and r['run']==r['expected'] for r in reports.values()) else 1


if __name__ == '__main__':
    sys.exit(main())
