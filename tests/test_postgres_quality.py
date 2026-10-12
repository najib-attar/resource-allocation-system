"""Physical integrity and publication contract regressions for the existing schema."""

from pathlib import Path
from tempfile import TemporaryDirectory
from copy import deepcopy

from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from postgres_fixtures import PostgresTestCase, ROOT
from test_postgres_import import copy_inputs
from web.engine_gateway import EngineGateway
from web.persistence.importer import ImportValidationError, import_csv
from web.persistence.models import Base, RequestDecision, RequestSlot, ResourceRequest
from web.persistence.repository import PersistenceError, Repository


class PostgresQualityTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        with TemporaryDirectory() as directory:
            copy_inputs(Path(directory))
            import_csv(self.database, directory)
        self.repository = Repository(self.database)

    def test_negative_occurrence_ordinal_is_rejected(self):
        with self.assertRaises(IntegrityError):
            with self.database.transaction() as session:
                session.add(RequestSlot(request_id=1, ordinal=-1, day=1, start_minutes=540, end_minutes=600))

    def test_duplicate_decision_order_is_rejected(self):
        run_id, _ = self.repository.start_run()
        with self.assertRaises(IntegrityError):
            with self.database.transaction() as session:
                for request_id in (1, 2):
                    session.add(RequestDecision(run_id=run_id, request_id=request_id, ordinal=1,
                                                status="Rejected", reason="test", payload={}))

    def test_all_foreign_keys_have_a_leading_index(self):
        inspector = inspect(self.database.engine)
        for table in Base.metadata.sorted_tables:
            if table.name == "application_state":
                continue  # A singleton row needs no reverse-lookup performance index.
            indexes = [item["column_names"] for item in inspector.get_indexes(table.name)]
            indexes += [item["column_names"] for item in inspector.get_unique_constraints(table.name)]
            indexes.append(inspector.get_pk_constraint(table.name)["constrained_columns"])
            for foreign_key in inspector.get_foreign_keys(table.name):
                columns = foreign_key["constrained_columns"]
                with self.subTest(table=table.name, columns=columns):
                    self.assertTrue(any(index[:len(columns)] == columns for index in indexes))

    def test_inconsistent_result_totals_cannot_be_published(self):
        run_id, snapshot = self.repository.start_run()
        result, build = EngineGateway(ROOT).execute(snapshot)
        decision = next(item for item in result["requestResults"] if item["status"] == "Approved")
        decision["allocationCount"] += 1
        with self.assertRaisesRegex(PersistenceError, "allocation summary"):
            self.repository.publish_run(run_id, result, build)
        self.assertIsNone(self.repository.read_view()[2])

    def test_inconsistent_room_metadata_cannot_be_published(self):
        run_id, snapshot = self.repository.start_run()
        result, build = EngineGateway(ROOT).execute(snapshot)
        result["allocations"][0]["spaceCapacity"] += 1
        with self.assertRaisesRegex(PersistenceError, "resource metadata"):
            self.repository.publish_run(run_id, result, build)
        self.assertIsNone(self.repository.read_view()[2])

    def test_referenced_requests_cannot_be_deleted_implicitly(self):
        with self.assertRaises(IntegrityError):
            with self.database.transaction() as session:
                session.delete(session.get(ResourceRequest, 1))

    def test_connection_pool_is_reused_and_sessions_are_returned(self):
        for _ in range(3):
            self.repository.read_view()
            self.assertEqual(self.database.engine.pool.checkedout(), 0)

    def test_malformed_request_metadata_rolls_back_without_python_attribute_errors(self):
        original = self.repository.snapshot()["requests"][0]
        for changes in ({"slots": [None]}, {"title": []}, {"type": "CommitteeMeeting", "participants": [None]},
                        {"type": "Exam", "exam": {"canSplitAcrossRooms": True, "courseCode": []}}):
            item = deepcopy(original) | changes
            item.pop("id")
            with self.subTest(changes=changes), self.assertRaises(ImportValidationError):
                self.repository.save_request(item)
        self.assertEqual(len(self.repository.snapshot()["requests"]), 14)
