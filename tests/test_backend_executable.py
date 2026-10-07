"""Run with: python -m unittest discover -s tests -p test_backend_executable.py -v."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main, mock
from urllib.parse import parse_qs, urlparse
import json
import os
import shutil
import subprocess

from web.backend_executable import (
    BackendExecutableError,
    default_backend_path,
    file_sha256,
    manifest_path,
    resolve_backend_executable,
    source_fingerprint,
)


class BackendFixture:
    def setUp(self):
        self.temporary = TemporaryDirectory(prefix="backend-resolution-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "src").mkdir()
        self.source = self.root / "src" / "main.cpp"
        self.source.write_text("int main() { return 0; }\n", encoding="utf-8")

    def make_backend(self, path=None):
        path = path or default_backend_path(self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test backend artifact")
        path.chmod(0o755)
        metadata = {
            "schema_version": 1,
            "source_sha256": source_fingerprint(self.root),
            "binary_sha256": file_sha256(path),
            "built_at": "2026-10-07T00:00:00+00:00",
            "compiler": "test compiler",
        }
        manifest_path(path).write_text(json.dumps(metadata), encoding="utf-8")
        return path


class BackendExecutableTests(BackendFixture, TestCase):
    def test_default_is_authoritative_build_artifact(self):
        path = self.make_backend()
        backend = resolve_backend_executable(self.root)
        self.assertEqual(backend.path, path.resolve())
        self.assertEqual(backend.metadata["compiler"], "test compiler")
        self.assertEqual(path.name, "allocation_system.exe" if os.name == "nt" else "allocation_system")

    def test_old_root_binaries_are_not_fallbacks(self):
        for name in ("allocation_system.exe", "allocation_system_test.exe", "allocation_system"):
            (self.root / name).write_bytes(b"old")
        with self.assertRaisesRegex(BackendExecutableError, "missing"):
            resolve_backend_executable(self.root)

    def test_relative_configuration_is_project_relative_not_working_directory(self):
        path = self.make_backend(self.root / "engine artifacts" / "engine.exe")
        backend = resolve_backend_executable(self.root, str(path.relative_to(self.root)))
        self.assertEqual(backend.path, path.resolve())

    def test_absolute_configured_path_with_spaces(self):
        path = self.make_backend(self.root / "engine artifacts" / "engine.exe")
        self.assertEqual(resolve_backend_executable(self.root, str(path)).path, path.resolve())

    def test_empty_configuration_is_not_a_fallback(self):
        self.make_backend()
        with self.assertRaisesRegex(BackendExecutableError, "must not be empty"):
            resolve_backend_executable(self.root, " ")

    def test_missing_configured_path_does_not_fall_back_to_valid_default(self):
        self.make_backend()
        with self.assertRaisesRegex(BackendExecutableError, "missing"):
            resolve_backend_executable(self.root, "missing-engine.exe")

    def test_directory_is_not_an_executable(self):
        with self.assertRaisesRegex(BackendExecutableError, "missing"):
            resolve_backend_executable(self.root, str(self.root))

    def test_missing_build_manifest_fails(self):
        path = self.make_backend()
        manifest_path(path).unlink()
        with self.assertRaisesRegex(BackendExecutableError, "Cannot validate"):
            resolve_backend_executable(self.root)

    def test_invalid_build_manifest_fails(self):
        path = self.make_backend()
        for contents in ("not json", "[]", '{"schema_version": 1}'):
            with self.subTest(contents=contents):
                manifest_path(path).write_text(contents, encoding="utf-8")
                with self.assertRaises(BackendExecutableError):
                    resolve_backend_executable(self.root)

    def test_replaced_binary_fails(self):
        path = self.make_backend()
        path.write_bytes(b"different executable")
        with self.assertRaisesRegex(BackendExecutableError, "does not match"):
            resolve_backend_executable(self.root)

    def test_changed_source_fails_even_with_preserved_timestamp(self):
        self.make_backend()
        timestamp = self.source.stat().st_mtime
        self.source.write_text("int main() { return 1; }\n", encoding="utf-8")
        os.utime(self.source, (timestamp, timestamp))
        with self.assertRaisesRegex(BackendExecutableError, "stale"):
            resolve_backend_executable(self.root)

    def test_new_header_invalidates_build(self):
        self.make_backend()
        (self.root / "src" / "new.h").write_text("#pragma once\n", encoding="utf-8")
        with self.assertRaisesRegex(BackendExecutableError, "stale"):
            resolve_backend_executable(self.root)

    def test_packaged_build_without_sources_still_checks_binary(self):
        path = self.make_backend()
        self.source.unlink()
        self.source.parent.rmdir()
        self.assertEqual(resolve_backend_executable(self.root).path, path.resolve())
        path.write_bytes(b"tampered package")
        with self.assertRaisesRegex(BackendExecutableError, "does not match"):
            resolve_backend_executable(self.root)

    def test_empty_source_directory_is_not_treated_as_packaged_deployment(self):
        self.make_backend()
        self.source.unlink()
        with self.assertRaisesRegex(BackendExecutableError, r"empty C\+\+ source tree"):
            resolve_backend_executable(self.root)

    def test_linux_execute_permission_is_checked(self):
        if os.name == "nt":
            self.skipTest("POSIX permission check runs on Linux.")
        path = self.make_backend()
        path.chmod(0o644)
        with self.assertRaisesRegex(BackendExecutableError, "not executable"):
            resolve_backend_executable(self.root)


class BackendExecutionTests(BackendFixture, TestCase):
    def setUp(self):
        super().setUp()
        from web import app as web_app
        self.web_app = web_app
        patch = mock.patch.object(web_app, "PROJECT_ROOT", self.root)
        patch.start()
        self.addCleanup(patch.stop)
        data = self.root / "data"
        data.mkdir()
        for attribute, value in (("DATA_DIR", data),
                                 ("backend_results", web_app.BackendResultAdapter(data, web_app.RAW_DATA_FILES))):
            patch = mock.patch.object(web_app, attribute, value)
            patch.start()
            self.addCleanup(patch.stop)
        environment = mock.patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_invalid_artifact_is_never_executed(self):
        with mock.patch.object(self.web_app.subprocess, "run") as run:
            result = self.web_app.run_backend_allocation()
        self.assertEqual(result["status"], "error")
        self.assertIn("missing", result["message"])
        run.assert_not_called()

    def test_stale_artifact_is_never_executed(self):
        self.make_backend()
        self.source.write_text("changed\n", encoding="utf-8")
        with mock.patch.object(self.web_app.subprocess, "run") as run:
            result = self.web_app.run_backend_allocation()
        self.assertEqual(result["status"], "error")
        self.assertIn("stale", result["message"])
        run.assert_not_called()

    def test_verified_absolute_path_is_executed_and_logged(self):
        path = self.make_backend()
        completed = subprocess.CompletedProcess([str(path)], 0, "done", "")
        with mock.patch.object(self.web_app.subprocess, "run", return_value=completed) as run, \
                mock.patch.object(self.web_app.SharedFileState, "publish") as publish:
            with self.assertLogs(self.web_app.app.logger, level="INFO") as logs:
                result = self.web_app.run_backend_allocation()
        self.assertEqual(result["status"], "success")
        self.assertEqual(run.call_args.args[0], [str(path.resolve())])
        workspace = run.call_args.kwargs["cwd"]
        self.assertEqual(workspace.parent, self.root / "data" / ".runtime")
        self.assertTrue((workspace / "data").is_dir())
        publish.assert_called_once()
        self.assertFalse(run.call_args.kwargs.get("shell", False))
        self.assertTrue(any("source=" in entry and "compiler=" in entry for entry in logs.output))

    def test_os_loader_failure_is_reported(self):
        self.make_backend()
        with mock.patch.object(self.web_app.subprocess, "run", side_effect=OSError("missing runtime DLL")):
            result = self.web_app.run_backend_allocation()
        self.assertEqual(result["status"], "error")
        self.assertIn("could not start", result["message"])

    def test_run_route_redirects_to_clear_validation_error(self):
        with mock.patch.object(self.web_app.subprocess, "run") as run:
            response = self.web_app.app.test_client().post("/run-allocation")
        self.assertEqual(response.status_code, 302)
        query = parse_qs(urlparse(response.location).query)
        self.assertEqual(query["run_status"], ["error"])
        self.assertIn("missing", query["run_message"][0])
        run.assert_not_called()


class BackendWebSmokeTests(TestCase):
    def test_real_backend_and_dashboard_use_isolated_outputs(self):
        from web import app as web_app
        root = Path(__file__).resolve().parent.parent
        try:
            backend = resolve_backend_executable(root)
        except BackendExecutableError as error:
            self.skipTest(f"Build scripts/build_backend.py before the live smoke check: {error}")

        with TemporaryDirectory(prefix="backend-web-smoke-") as temporary:
            workspace = Path(temporary)
            shutil.copytree(root / "src", workspace / "src")
            data = workspace / "data"
            data.mkdir()
            for name in ("users.csv", "spaces.csv", "requests.csv", "user_busy_slots.csv",
                         "request_participants.csv", "config.txt"):
                shutil.copy2(root / "data" / name, data / name)
            executable = default_backend_path(workspace)
            executable.parent.mkdir(parents=True)
            shutil.copy2(backend.path, executable)
            shutil.copy2(manifest_path(backend.path), manifest_path(executable))

            adapter = web_app.BackendResultAdapter(data, web_app.RAW_DATA_FILES)
            with mock.patch.object(web_app, "PROJECT_ROOT", workspace), \
                    mock.patch.object(web_app, "DATA_DIR", data), \
                    mock.patch.object(web_app, "backend_results", adapter), \
                    mock.patch.dict(os.environ, {"RESOURCE_ALLOCATION_BACKEND": str(executable)}):
                client = web_app.app.test_client()
                response = client.post("/run-allocation")
                self.assertEqual(response.status_code, 302)
                self.assertEqual(parse_qs(urlparse(response.location).query)["run_status"], ["success"])
                for route in ("/", "/allocation-summary", "/request/1", "/request/40", "/schedules",
                              "/schedules?type=user&id=2", "/schedules?type=space&id=301",
                              "/raw-data?file=request_summaries.csv",
                              "/raw-data?file=allocation_summaries.csv", "/add-request?type=CommitteeMeeting"):
                    with self.subTest(route=route):
                        self.assertEqual(client.get(route).status_code, 200)
                for name in ("allocations.csv", "request_results.csv", "request_summaries.csv",
                             "allocation_summaries.csv"):
                    published = web_app.SharedFileState(data).current_data_dir()
                    self.assertGreater((published / name).stat().st_size, 0)
                    self.assertFalse((data / name).exists())
                adapter = adapter.pin()
                request_ids = {row["requestId"] for row in adapter.read_csv_table("requests.csv")["rows"]}
                for row in adapter.read_csv_table("allocations.csv")["rows"]:
                    self.assertIn(row["requestId"], request_ids)


if __name__ == "__main__":
    main()
