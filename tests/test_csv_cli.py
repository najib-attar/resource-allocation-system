"""Isolated standalone C++ CSV compatibility smoke; not web persistence."""

from pathlib import Path
import csv
import subprocess
from tempfile import TemporaryDirectory
from unittest import TestCase

from csv_cli_fixtures import validate_cli_outputs
from postgres_fixtures import ROOT
from web.backend_executable import resolve_backend_executable


def read_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


class IsolatedCliSmokeTests(TestCase):
    def test_real_cli_writes_only_inside_temporary_workspace(self):
        backend = resolve_backend_executable(ROOT)
        with TemporaryDirectory(prefix="isolated-cli-") as temporary:
            data = Path(temporary) / "data"
            data.mkdir()
            for source in (ROOT / "tests" / "fixtures" / "runtime_no_demo").iterdir():
                (data / source.name).write_bytes(source.read_bytes())
            completed = subprocess.run([str(backend.path)], cwd=temporary, capture_output=True, text=True, timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            validate_cli_outputs(data)
            self.assertEqual(read_rows(data / "request_results.csv")[0]["status"], "Approved")
