"""Database cutover, migration parity, protocol and view integrity acceptance tests."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock
import os

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from alembic import command
from alembic.config import Config

from postgres_fixtures import PostgresTestCase, ROOT
from test_postgres_import import copy_inputs
from test_shared_file_concurrency import form
from web import app as web_app
from web.allocation_workflow import execute_allocation
from web.database_result_adapter import DatabaseResultAdapter
from web.engine_gateway import EngineGateway, execution_snapshot
from web.backend_result_adapter import BackendResultAdapter
from web.persistence.importer import import_csv
from web.persistence.models import Base, STRATEGIES, RequestHistory
from web.persistence.repository import Repository


class PostgresWebTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        with TemporaryDirectory() as directory:
            data = Path(directory)
            copy_inputs(data)
            import_csv(self.database, data)
        # The seed CSVs no longer exist when the application is exercised.
        self.repository = Repository(self.database)
        self.client = self.configure_web()

    def test_normal_views_and_execution_never_use_csv_or_local_result_json(self):
        with mock.patch("legacy_shared_file_state.SharedFileState.__init__", side_effect=AssertionError("Operational files used")), \
                mock.patch.object(BackendResultAdapter, "read_csv_table", side_effect=AssertionError("File reader used")):
            response = self.client.post("/run-allocation")
            self.assertIn("run_status=success", response.location)
            for route in ("/", "/requests", "/users", "/spaces", "/allocation-summary", "/request/1", "/request/40",
                          "/request/999999", "/schedules", "/schedules?type=user&id=2", "/schedules?type=space&id=301",
                          "/raw-data?file=not_allowed.csv", "/raw-data?file=allocation_summaries.csv", "/raw-data?file=request_summaries.csv",
                          "/raw-data?file=config.txt", "/add-request?type=CommitteeMeeting"):
                with self.subTest(route=route):
                    self.assertEqual(self.client.get(route).status_code, 200)

    def test_database_and_original_csv_produce_identical_results_for_all_strategies(self):
        gateway = EngineGateway(ROOT)
        for strategy in STRATEGIES:
            with self.subTest(strategy=strategy):
                self.repository.set_strategy(strategy)
                published = execute_allocation(self.repository, gateway)
                csv_input = execution_snapshot(BackendResultAdapter(ROOT / "data", []), strategy)
                csv_input["runId"] = published["runId"]
                expected, _ = gateway.execute(csv_input)
                self.assertEqual(published, expected)
                self.assertEqual(self.repository.read_view()[1]["result"], expected)

    def test_schedule_events_and_resource_attributes_match_published_allocations(self):
        execute_allocation(self.repository, EngineGateway(ROOT))
        adapter = DatabaseResultAdapter(self.repository, web_app.RAW_DATA_FILES)
        spaces = {row["spaceId"]: row for row in adapter.read_csv_table("spaces.csv")["rows"]}
        for allocation in adapter.engine_result["allocations"]:
            space = spaces[str(allocation["spaceId"])]
            self.assertEqual(allocation["spaceName"], space["name"])
            self.assertEqual(allocation["spaceType"], space["type"])
            self.assertEqual(allocation["building"], space["building"])
            self.assertEqual(allocation["spaceCapacity"], int(space["capacity"]))
            context = adapter.get_schedule_context("space", str(allocation["spaceId"]))
            ids = {event["request_id"] for row in context["schedule_rows"] for day in row["days"] for event in day["events"]}
            self.assertIn(str(allocation["requestId"]), ids)
            for uid in allocation["requiredParticipantIds"]:
                context = adapter.get_schedule_context("user", str(uid))
                ids = {event["request_id"] for row in context["schedule_rows"] for day in row["days"] for event in day["events"]}
                self.assertIn(str(allocation["requestId"]), ids)

    def test_structured_suggestions_and_history_survive_database_roundtrip(self):
        result = execute_allocation(self.repository, EngineGateway(ROOT))
        self.assertTrue(any(group["items"] for group in result["suggestions"]))
        suggested_request = next(group["requestId"] for group in result["suggestions"] if group["items"])
        with mock.patch("web.backend_result_adapter.extract_meeting_suggestions", side_effect=AssertionError("History parser used")):
            self.assertEqual(self.client.get("/request/40").status_code, 200)
            self.assertIn("Suggested least-change", self.client.get(f"/request/{suggested_request}").get_data(as_text=True))
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(RequestHistory)), 2 * len(result["requestResults"]))

    def test_invalid_strategy_and_forms_leave_database_inputs_unchanged(self):
        before = self.repository.snapshot()
        response = self.client.post("/set-strategy", data={"strategy": "unknown"})
        self.assertIn("strategy_status=error", response.location)
        for changes in ({"requestType": "Recurring", "timeData": "not a slot"},
                        {"participantCount": "2147483648"}, {"requiredParticipantIds": ["2", "2"]},
                        {"spaceId": "999999"}):
            with self.subTest(changes=changes):
                data = form("Invalid") | changes
                response = self.client.post("/add-request", data=data)
                self.assertEqual(response.status_code, 200)
                self.assertIn('class="form-message form-message-error"', response.get_data(as_text=True))
        after = self.repository.snapshot()
        before.pop("runId"); after.pop("runId")
        self.assertEqual(before, after)

    def test_alembic_schema_matches_models_and_upgrading_again_is_non_destructive(self):
        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext
        with self.database.engine.connect() as connection:
            self.assertEqual(compare_metadata(MigrationContext.configure(connection), Base.metadata), [])
        before = self.repository.snapshot()
        with mock.patch.dict(os.environ, {"DATABASE_URL": self.url}):
            command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
        after = self.repository.snapshot()
        before.pop("runId"); after.pop("runId")
        self.assertEqual(before, after)


class DatabaseFailureWebTests(TestCase):
    def test_missing_configuration_returns_clear_error_without_file_fallback(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.dict(web_app.app.config, {"DATABASE_URL": None}), \
                mock.patch("legacy_shared_file_state.SharedFileState.__init__", side_effect=AssertionError("CSV fallback used")):
            response = web_app.app.test_client().get("/")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL is required", response.get_data(as_text=True))

    def test_database_errors_do_not_expose_sql_credentials_or_sensitive_parameters(self):
        repository = mock.Mock()
        repository.read_view.side_effect = OperationalError("private SQL", {}, RuntimeError("secret-password"))
        with mock.patch.object(web_app, "get_repository", return_value=repository), self.assertLogs(web_app.app.logger) as logs:
            response = web_app.app.test_client().get("/")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("secret-password", response.get_data(as_text=True) + " ".join(logs.output))
        self.assertNotIn("private SQL", response.get_data(as_text=True) + " ".join(logs.output))
