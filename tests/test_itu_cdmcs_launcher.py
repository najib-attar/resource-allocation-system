import json
from pathlib import Path
from subprocess import CompletedProcess
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch

from scripts import run_itu_cdmcs as launcher


class ItuCdmcsLauncherTests(TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(TemporaryDirectory())).resolve() / launcher.PROFILE
        self.directory.mkdir()
        self.settings_path = self.directory / "settings.json"
        data = self.directory / "postgres-data"
        data.mkdir()
        self.marker = data / "local-demo-owner"
        values = {
            "kind": "university-local-demo", "version": 1, "dataset": "itu", "seeded": True, "seed": 42,
            "databaseName": "ras_itu_demo", "postgresUser": "ras_demo", "postgresPort": 55546,
            "academicStart": "2026-09-28", "academicEnd": "2027-01-08", "profileId": "o" * 32,
            "postgresPassword": "p" * 24, "demoPassword": "d" * 24, "sessionSecret": "s" * 32,
        }
        self.marker.write_text(values["profileId"], encoding="utf-8")
        self.settings_path.write_text(json.dumps(values), encoding="utf-8")

    def test_missing_settings_refuse_without_generating_a_profile(self):
        self.settings_path.unlink()
        with self.assertRaisesRegex(ValueError, "existing initialized"):
            launcher.profile_settings(self.directory)
        self.assertFalse(self.settings_path.exists())

    def test_refuses_an_unowned_or_wrong_port_profile(self):
        self.marker.write_text("unrelated", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "owner marker"):
            launcher.profile_settings(self.directory)
        values = json.loads(self.settings_path.read_text(encoding="utf-8"))
        values["postgresPort"] = 5432
        self.settings_path.write_text(json.dumps(values), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Saved demo settings differ"):
            launcher.profile_settings(self.directory)

    def test_read_only_check_refuses_wrong_database(self):
        path, settings = launcher.profile_settings(self.directory)
        db = MagicMock()
        session = db.transaction.return_value.__enter__.return_value
        session.execute.return_value.one.return_value = ("unrelated", 55546)
        with patch.object(launcher, "verify_itu_owner") as owner:
            with self.assertRaisesRegex(ValueError, "does not match"):
                launcher.inspect_database(db, path, settings)
        owner.assert_called_once_with(db, path, settings)
        db.transaction.assert_called_once_with(read_only=True)

    def test_refuses_to_serve_an_older_schema(self):
        command = ["run_itu_cdmcs", "--state-dir", str(self.directory), "--serve"]
        with (
            patch("sys.argv", command),
            patch.object(launcher, "inspect_database", return_value={"0051e"}),
            patch.object(launcher, "serve") as serve,
            patch("sys.stderr") as error,
        ):
            self.assertEqual(launcher.main(), 1)
        serve.assert_not_called()
        self.assertIn("separately approved migration", error.write.call_args_list[0].args[0])

    def test_verified_schema_reaches_the_existing_application(self):
        command = ["run_itu_cdmcs", "--state-dir", str(self.directory), "--serve", "--port", "5080"]
        with (
            patch("sys.argv", command),
            patch.object(launcher, "inspect_database", return_value=launcher.required_revisions()),
            patch.object(launcher, "serve") as serve,
        ):
            self.assertEqual(launcher.main(), 0)
        self.assertEqual(serve.call_args.args[2], 5080)

    def test_pilot_only_revision_keeps_regular_0051h_profile_compatible(self):
        command = ["run_itu_cdmcs", "--state-dir", str(self.directory), "--serve"]
        with (
            patch("sys.argv", command),
            patch.object(launcher, "required_revisions", return_value={"0051i"}),
            patch.object(launcher, "inspect_database", return_value={"0051h"}),
            patch.object(launcher, "serve") as serve,
        ):
            self.assertEqual(launcher.main(), 0)
        serve.assert_called_once()
        with patch.object(launcher, "required_revisions", return_value={"a_future_revision"}):
            self.assertFalse(launcher.can_serve({"0051h"}))

    def test_pg_ctl_console_output_is_separate_from_the_server_log(self):
        data = self.directory / "postgres-data"
        (data / "postmaster.pid").write_text(f"1234\n{data}\n5678\n55546\n", encoding="utf-8")
        with patch.object(launcher.subprocess, "run", side_effect=[
            CompletedProcess([], 3), CompletedProcess([], 0), CompletedProcess([], 0),
        ]) as run:
            with launcher.existing_postgres(self.directory, self.directory / "bin"):
                pass
        launch = run.call_args_list[1]
        self.assertIn(str(self.directory / "postgres.log"), launch.args[0])
        self.assertEqual(Path(launch.kwargs["stdout"].name), self.directory / "postgres-control.log")
        self.assertEqual(run.call_args.args[0][-1], "stop")
