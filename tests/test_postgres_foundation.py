import os
from unittest import TestCase, mock

from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from postgres_fixtures import PostgresTestCase
from web.persistence.database import Database, DatabaseConfigurationError, database_url
from web.persistence.models import Base, OrganizationUnit, Resource


class DatabaseConfigurationTests(TestCase):
    def test_missing_database_url_has_no_csv_fallback(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(DatabaseConfigurationError, "CSV fallback is disabled"):
                database_url()

    def test_only_postgresql_psycopg_is_allowed(self):
        for value in ("sqlite://", "mysql://host/db", "not-a-url"):
            with self.subTest(value=value), self.assertRaises(DatabaseConfigurationError):
                database_url(value)
        self.assertEqual(database_url("postgresql://user@localhost/db").drivername, "postgresql+psycopg")

    def test_invalid_lock_timeout_is_rejected(self):
        for value in (0, -1, float("inf"), float("nan")):
            with self.subTest(value=value), self.assertRaises(DatabaseConfigurationError):
                Database("postgresql://user@localhost/db", value)


class PostgresFoundationTests(PostgresTestCase):
    def test_fresh_alembic_migration_creates_all_mapped_tables(self):
        self.assertTrue(set(Base.metadata.tables) <= set(inspect(self.database.engine).get_table_names()))

    def test_transaction_rolls_back_all_changes(self):
        with self.assertRaisesRegex(RuntimeError, "abort"):
            with self.database.transaction() as session:
                session.add(OrganizationUnit(name="Rollback unit"))
                session.flush()
                raise RuntimeError("abort")
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(list(session.scalars(select(OrganizationUnit))), [])

    def test_resource_capacity_and_type_are_constrained(self):
        for capacity, resource_type in ((0, "Classroom"), (10, "Unknown")):
            with self.subTest(capacity=capacity, resource_type=resource_type), self.assertRaises(IntegrityError):
                with self.database.transaction() as session:
                    session.add(Resource(source_order=1, type=resource_type, name="Bad", capacity=capacity))

    def test_organization_parent_foreign_key_is_enforced(self):
        with self.assertRaises(IntegrityError):
            with self.database.transaction() as session:
                session.add(OrganizationUnit(name="Invalid parent", parent_id=999))
