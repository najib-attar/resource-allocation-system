"""Real PostgreSQL tests own a random schema and never reset an application database."""

import os
import re
import uuid
from pathlib import Path
from unittest import TestCase, mock

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from web.persistence.database import Database, database_url


ROOT = Path(__file__).resolve().parent.parent


class PostgresTestCase(TestCase):
    def setUp(self):
        configured = os.environ.get("TEST_DATABASE_URL")
        if not configured:
            self.skipTest("Real PostgreSQL integration requires an isolated TEST_DATABASE_URL.")
        self.schema = "ras_test_" + uuid.uuid4().hex
        self.owner = create_engine(database_url(configured))
        with self.owner.begin() as connection:
            connection.execute(CreateSchema(self.schema))
        self.addCleanup(self.cleanup_schema)
        self.url = database_url(configured).set(query={"options": "-csearch_path=" + self.schema}).render_as_string(hide_password=False)
        with mock.patch.dict(os.environ, {"DATABASE_URL": self.url}):
            command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
        self.database = Database(self.url)
        self.addCleanup(self.database.dispose)

    def cleanup_schema(self):
        if not re.fullmatch(r"ras_test_[0-9a-f]{32}", self.schema):
            raise RuntimeError("Refusing to clean an unowned test schema.")
        with self.owner.begin() as connection:
            connection.execute(DropSchema(self.schema, cascade=True))
        self.owner.dispose()
