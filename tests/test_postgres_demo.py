from unittest import TestCase
from sqlalchemy import event, select

from postgres_fixtures import PostgresTestCase, ROOT
from web.allocation_workflow import execute_allocation
from web.engine_gateway import EngineGateway
from web.persistence.demo import demo_snapshot, seed_demo_database
from web.persistence.importer import ImportValidationError
from web.persistence.models import OrganizationUnit, STRATEGIES
from web.persistence.repository import Repository


class DemoGenerationTests(TestCase):
    def test_seed_is_reproducible_and_does_not_create_fake_results(self):
        first, _ = demo_snapshot(41)
        self.assertEqual(demo_snapshot(41)[0], first)
        self.assertNotEqual(demo_snapshot(42)[0]["requests"], first["requests"])
        self.assertEqual({item["type"] for item in first["requests"]}, {"OneTime", "Recurring", "Exam", "CommitteeMeeting"})
        self.assertEqual({item["role"] for item in first["users"]}, {"Student", "Instructor", "Staff", "Administrator", "TeachingAssistant"})
        self.assertTrue(all(item["email"].endswith("@example.invalid") for item in first["users"]))
        self.assertNotIn("allocations", first)

    def test_large_dataset_stays_within_protocol_limits(self):
        snapshot, _ = demo_snapshot(41, "large")
        self.assertEqual(len(snapshot["requests"]), 1200)
        self.assertEqual(len(snapshot["users"]), 1060)
        self.assertEqual(len(snapshot["spaces"]), 200)


class PostgresDemoTests(PostgresTestCase):
    def test_large_snapshot_uses_bounded_queries_and_returns_connections(self):
        seed_demo_database(self.database, size="large")
        statements = []
        def record(connection, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        event.listen(self.database.engine, "before_cursor_execute", record)
        try:
            snapshot, document, _ = Repository(self.database).read_view()
        finally:
            event.remove(self.database.engine, "before_cursor_execute", record)
        self.assertEqual(len(snapshot["requests"]), 1200)
        self.assertIsNone(document)
        self.assertLessEqual(len(statements), 15)
        self.assertEqual(self.database.engine.pool.checkedout(), 0)
    def test_seed_preserves_units_identities_and_refuses_populated_target(self):
        report = seed_demo_database(self.database)
        self.assertEqual(report["counts"], {"users": 106, "spaces": 20, "requests": 120, "busySlots": 12})
        repository = Repository(self.database)
        self.assertIsNone(repository.read_view()[2])
        with self.database.transaction(read_only=True) as session:
            units = list(session.scalars(select(OrganizationUnit)))
            self.assertEqual(sum(item.unit_type == "Department" and item.parent_id is not None for item in units), 4)
        with self.assertRaisesRegex(ImportValidationError, "already contains"):
            seed_demo_database(self.database)
        item = dict(repository.snapshot()["requests"][0])
        item.pop("id")
        self.assertGreater(repository.save_request(item), 120)

    def test_demo_runs_all_five_real_strategies_and_persists_results(self):
        seed_demo_database(self.database)
        repository = Repository(self.database)
        for strategy in STRATEGIES:
            with self.subTest(strategy=strategy):
                repository.set_strategy(strategy)
                result = execute_allocation(repository, EngineGateway(ROOT))
                self.assertEqual(repository.read_view()[1]["result"], result)
                self.assertEqual(len(result["requestResults"]), 120)
                self.assertTrue(result["allocations"])
                self.assertTrue(any(item["status"] == "Rejected" for item in result["requestResults"]))
                if strategy in {"multi_room_exam_greedy", "multi_room_exam_best_fit", "shared_room_exam_best_fit"}:
                    exam = next(item for item in result["requestResults"] if item["requestId"] == 3)
                    self.assertEqual(exam["status"], "Approved")
                    self.assertGreater(exam["allocationCount"], 1)
                self.assertTrue(any(group["items"] for group in result["suggestions"]))
