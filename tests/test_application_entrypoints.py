"""Supported Flask entry points keep working with package-only internal imports."""

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase


ROOT = Path(__file__).resolve().parent.parent


class ApplicationEntrypointTests(TestCase):
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
