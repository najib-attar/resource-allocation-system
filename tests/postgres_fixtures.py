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
    migration_target = "head"
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
            command.upgrade(Config(str(ROOT / "alembic.ini")), self.migration_target)
        self.database = Database(self.url)
        self.addCleanup(self.database.dispose)

    def configure_web(self):
        from web import app as web_app
        patch = mock.patch.dict(web_app.app.config, {"TESTING": True, "PROPAGATE_EXCEPTIONS": True,
                                                     "DATABASE_URL": self.url, "DATABASE_LOCK_TIMEOUT": 5,
                                                     "SECRET_KEY": "isolated-test-session-key-not-for-production-use"})
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self.dispose_web_database)
        from sqlalchemy import select
        from web.account_service import AccountService
        from web.persistence.models import LoginAccount, User
        from auth_fixtures import authorized_client
        with self.database.transaction(read_only=True) as session:
            actor = session.scalar(select(User.id).order_by(User.id))
            account = session.get(LoginAccount, actor)
            version = account.session_version if account else 1
        if account is None:
            AccountService(self.database).provision(actor, "fixture-admin", uuid.uuid4().hex, administrator=True)
        return authorized_client(web_app.app, actor, version)

    def dispose_web_database(self):
        from web import app as web_app
        cached = web_app.app.extensions.get("allocation_database")
        if cached and cached[0][0] == self.url:
            web_app.app.extensions.pop("allocation_database")[1].dispose()

    def cleanup_schema(self):
        if not re.fullmatch(r"ras_test_[0-9a-f]{32}", self.schema):
            raise RuntimeError("Refusing to clean an unowned test schema.")
        with self.owner.begin() as connection:
            connection.execute(DropSchema(self.schema, cascade=True))
        self.owner.dispose()
