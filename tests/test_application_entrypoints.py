"""Supported Flask entry points keep working with package-only internal imports."""

import os
from pathlib import Path
import subprocess
import sys
import textwrap
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless


ROOT = Path(__file__).resolve().parent.parent


class ApplicationEntrypointTests(TestCase):
    def test_full_ci_launcher_supports_spawn_workers(self):
        workflow = (ROOT / '.github/workflows/backend-postgresql-regression.yml').read_text(encoding='utf-8')
        step = workflow.split('- name: Run Python, PostgreSQL, gateway, CLI and Flask tests', 1)[1]
        command = next(line.strip() for line in step.splitlines() if line.strip().startswith('python -B '))
        gate = textwrap.dedent(step.split("<<'PY'\n", 1)[1].split('          PY', 1)[0])
        # Exercise the real gate's interpreter mode, without discovering application tests.
        harness = '''
import multiprocessing, time, types, unittest
class ProbeRunner:
    def __init__(self, **kwargs): pass
    def run(self, suite):
        worker = multiprocessing.get_context('spawn').Process(target=time.sleep, args=(0,))
        worker.start()
        try:
            worker.join(5)
            if worker.exitcode != 0:
                raise RuntimeError('CI interpreter cannot bootstrap spawn workers')
        finally:
            if worker.is_alive():
                worker.terminate()
                worker.join(5)
            worker.close()
        return types.SimpleNamespace(testsRun=553, skipped=[], wasSuccessful=lambda: True)
unittest.TextTestRunner = ProbeRunner
unittest.TestLoader = lambda: types.SimpleNamespace(discover=lambda *args, **kwargs: unittest.TestSuite())
'''
        source = textwrap.dedent(harness) + '\n' + gate
        if command.startswith('python -B -c '):
            arguments, stdin = ['-c', source], None
        else:
            self.assertTrue(command.startswith("python -B - <<'PY'"))
            arguments, stdin = ['-'], source
        result = subprocess.run([sys.executable, '-B', *arguments], input=stdin, capture_output=True,
            text=True, timeout=20, cwd=ROOT, env=dict(os.environ, TEST_DATABASE_URL='synthetic-no-connection'))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @skipUnless(os.name == 'nt', 'PowerShell runner cleanup is exercised on Windows.')
    def test_cpp_runner_cleans_owned_artifacts_and_preserves_compile_failure_status(self):
        with TemporaryDirectory(prefix='cpp-runner-isolation-') as directory:
            root = Path(directory)
            repository, scratch = root / 'repository', root / 'scratch'
            (repository / 'src').mkdir(parents=True)
            (repository / 'tests').mkdir()
            scratch.mkdir()
            runner = repository / 'tests' / 'run_tests.ps1'
            runner.write_text((ROOT / 'tests' / 'run_tests.ps1').read_text(encoding='utf-8-sig'), encoding='utf-8')
            # A failing compiler leaves a partial artifact, without invoking C++
            # or touching any existing repository executable.
            script = """
function global:g++ {
    $index = [Array]::IndexOf($args, '-o')
    [IO.File]::WriteAllText([string]$args[$index + 1], 'owned partial compiler output')
    $global:LASTEXITCODE = 23
}
& '%s'
exit $LASTEXITCODE
""" % str(runner).replace("'", "''")
            result = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', script],
                cwd=repository, env=dict(os.environ, TEMP=str(scratch), TMP=str(scratch)),
                capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
            self.assertEqual(list(repository.glob('*.exe')), [])
            self.assertEqual(list(scratch.iterdir()), [])

    def test_flask_cli_registers_all_workflows_without_database_access(self):
        environment = dict(os.environ, DATABASE_URL="postgresql+psycopg://invalid@127.0.0.1:1/unavailable")
        result = subprocess.run([sys.executable, "-m", "flask", "--app", "web.app", "routes"],
            cwd=ROOT, env=environment, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        for endpoint in ("student.home", "appointments.index", "rooms.index", "equipment.index",
                         "equipment.catalog", "equipment.custodians", "notifications.feed", "allocation_summary"):
            with self.subTest(endpoint=endpoint):
                self.assertIn(endpoint, result.stdout)

    def test_direct_script_bootstraps_package_outside_repository_directory(self):
        # Stub only the server loop: execute the actual direct-script import path.
        code = """
import runpy, sys
from unittest.mock import patch
from flask import Flask
with patch.object(Flask, 'run') as serve:
    namespace = runpy.run_path(sys.argv[1], run_name='__main__')
serve.assert_called_once()
application = namespace['app']
assert application.blueprints.keys() >= {'student', 'appointments', 'rooms', 'equipment', 'notifications'}
for name in application.jinja_env.list_templates():
    application.jinja_env.get_template(name)
"""
        with TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, "-c", code, str(ROOT / "web" / "app.py")],
                cwd=directory, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
