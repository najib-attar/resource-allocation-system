import csv
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from sqlalchemy import func, select

from postgres_fixtures import PostgresTestCase, ROOT
from web.persistence.importer import CsvInputs, ImportValidationError, import_csv
from web.persistence.models import ApplicationState, RequestParticipant, ResourceRequest, User
from web.persistence.repository import Repository


INPUTS = ("users.csv", "spaces.csv", "requests.csv", "user_busy_slots.csv", "request_participants.csv", "config.txt")


def copy_inputs(destination):
    for filename in INPUTS:
        shutil.copy2(ROOT / "data" / filename, destination / filename)


def rewrite_csv(path, change):
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        headers, rows = reader.fieldnames, list(reader)
    rows = change(rows)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


class PostgresImportTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        temporary = TemporaryDirectory(prefix="postgres-import-")
        self.addCleanup(temporary.cleanup)
        self.data = Path(temporary.name)
        copy_inputs(self.data)
        self.repository = Repository(self.database)

    def test_normal_data_round_trips_all_engine_fields_and_order(self):
        expected = CsvInputs(self.data).snapshot()
        report = import_csv(self.database, self.data)
        actual = self.repository.snapshot()
        expected.pop("runId"); actual.pop("runId")
        self.assertEqual(actual, expected)
        self.assertEqual(report["counts"], {"users": 9, "spaces": 9, "requests": 14, "busySlots": 6})
        self.assertEqual(report["participants"], 13)

    def test_dry_run_does_not_modify_database_or_inputs(self):
        before = {name: (self.data / name).read_bytes() for name in INPUTS}
        report = import_csv(self.database, self.data, dry_run=True)
        self.assertTrue(report["dryRun"])
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(User)), 0)
            self.assertEqual(session.get(ApplicationState, 1).input_revision, 0)
        self.assertEqual(before, {name: (self.data / name).read_bytes() for name in INPUTS})

    def test_second_import_refuses_to_overwrite_existing_data(self):
        import_csv(self.database, self.data)
        before = self.repository.snapshot()
        with self.assertRaisesRegex(ImportValidationError, "already contains"):
            import_csv(self.database, self.data)
        after = self.repository.snapshot()
        before.pop("runId"); after.pop("runId")
        self.assertEqual(before, after)

    def test_quoted_unicode_empty_optional_and_newline_metadata_are_preserved(self):
        title = 'Advanced Algorithms, "Part II" \u00d6\nDiscussion'
        def change(rows):
            rows[0].update(title=title, purpose="", requiredBuilding="None")
            return rows
        rewrite_csv(self.data / "requests.csv", change)
        import_csv(self.database, self.data)
        request = self.repository.snapshot()["requests"][0]
        self.assertEqual(request["title"], title)
        self.assertEqual(request["purpose"], "")
        self.assertEqual(request["requiredBuilding"], "")

    def test_missing_reference_aborts_import_without_partial_records(self):
        def change(rows):
            rows[-1]["userId"] = "999999"
            return rows
        rewrite_csv(self.data / "request_participants.csv", change)
        with self.assertRaisesRegex(ImportValidationError, "participant reference"):
            import_csv(self.database, self.data)
        self.assertEqual(self.repository.snapshot()["users"], [])

    def test_duplicate_ids_unknown_types_and_invalid_numeric_values_are_reported(self):
        original = (self.data / "spaces.csv").read_bytes()
        for field, value, message in (("spaceId", "101", "duplicate IDs"), ("type", "GPU", "unknown space type"),
                                      ("capacity", "not-a-number", "Invalid capacity")):
            with self.subTest(field=field):
                (self.data / "spaces.csv").write_bytes(original)
                def change(rows):
                    rows[-1][field] = value
                    return rows
                rewrite_csv(self.data / "spaces.csv", change)
                with self.assertRaisesRegex(ImportValidationError, message):
                    import_csv(self.database, self.data)
                self.assertEqual(self.repository.snapshot()["spaces"], [])

    def test_failure_after_inserts_rolls_back_the_entire_import(self):
        with mock.patch("web.persistence.importer.advance_identity", side_effect=RuntimeError("abort import")):
            with self.assertRaisesRegex(RuntimeError, "abort import"):
                import_csv(self.database, self.data)
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(User)), 0)
            self.assertEqual(session.get(ApplicationState, 1).input_revision, 0)

    def test_nonmonotonic_ids_preserve_submission_order_and_identity_advances(self):
        def change(rows):
            rows = rows[:2]
            rows[0]["requestId"], rows[1]["requestId"] = "20", "10"
            return rows
        rewrite_csv(self.data / "requests.csv", change)
        rewrite_csv(self.data / "request_participants.csv", lambda rows: [])
        import_csv(self.database, self.data)
        self.assertEqual([item["id"] for item in self.repository.snapshot()["requests"]], [20, 10])
        item = {"type": "OneTime", "requesterId": 2, "spaceId": 301, "participantCount": 5,
                "slots": [{"day": 1, "startMinutes": 600, "endMinutes": 660}]}
        self.assertEqual(self.repository.save_request(item), 21)
        self.assertEqual([row["id"] for row in self.repository.snapshot()["requests"]], [20, 10, 21])

    def test_missing_required_file_and_malformed_row_fail_clearly(self):
        (self.data / "users.csv").unlink()
        with self.assertRaisesRegex(ImportValidationError, "Missing input file"):
            import_csv(self.database, self.data)
        shutil.copy2(ROOT / "data" / "users.csv", self.data / "users.csv")
        with (self.data / "requests.csv").open("a", encoding="utf-8") as file:
            file.write("900,OneTime\n")
        with self.assertRaisesRegex(ImportValidationError, "column count"):
            import_csv(self.database, self.data)

    def test_empty_unknown_and_missing_config_keep_legacy_greedy_fallback(self):
        for value in ("", "allocation_strategy=\n", "allocation_strategy=Unknown\n"):
            with self.subTest(value=value):
                (self.data / "config.txt").write_text(value)
                self.assertEqual(import_csv(self.database, self.data, dry_run=True)["strategy"], "greedy")
        (self.data / "config.txt").unlink()
        self.assertEqual(import_csv(self.database, self.data, dry_run=True)["strategy"], "greedy")
