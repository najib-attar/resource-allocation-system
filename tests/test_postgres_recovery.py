"""Fresh-schema upgrades and real dump/restore into newly created isolated databases."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import mock
import uuid

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.exc import IntegrityError

from postgres_fixtures import PostgresTestCase, ROOT
from test_postgres_import import copy_inputs
from test_postgres_workflow import new_request
from web.allocation_workflow import execute_allocation
from web.engine_gateway import EngineGateway
from web.persistence.database import Database, database_url
from web.persistence.importer import import_csv
from web.persistence.models import RequestSlot
from web.persistence.repository import Repository


class PostgresUpgradeTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        with TemporaryDirectory() as directory:
            copy_inputs(Path(directory))
            import_csv(self.database, directory)
        self.repository = Repository(self.database)

    def test_additive_upgrade_preserves_inputs_results_and_identity_sequences(self):
        before = execute_allocation(self.repository, EngineGateway(ROOT))
        snapshot = self.repository.snapshot()
        with mock.patch.dict(os.environ, {"DATABASE_URL": self.url}):
            # Only this owned disposable schema is downgraded. Current ORM fields
            # cannot initialize a historical schema missing the newer columns.
            command.downgrade(Config(str(ROOT / "alembic.ini")), "0041a")
            command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
        after = self.repository.snapshot()
        snapshot.pop("runId"); after.pop("runId")
        self.assertEqual(after, snapshot)
        self.assertEqual(self.repository.read_view()[1]["result"], before)
        self.assertGreater(self.repository.save_request(new_request()), 45)

    def test_invalid_old_rows_abort_upgrade_without_deleting_or_partially_migrating(self):
        with mock.patch.dict(os.environ, {"DATABASE_URL": self.url}):
            command.downgrade(Config(str(ROOT / "alembic.ini")), "0041a")
        with self.database.transaction() as session:
            session.add(RequestSlot(request_id=1, ordinal=-1, day=1, start_minutes=540, end_minutes=600))
        with mock.patch.dict(os.environ, {"DATABASE_URL": self.url}), self.assertRaises(IntegrityError):
            command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(text("SELECT version_num FROM alembic_version")), "0041a")
            self.assertIsNotNone(session.get(RequestSlot, (1, -1)))
            self.assertEqual(session.scalar(text("SELECT count(*) FROM pg_constraint WHERE conname = 'ck_user_source_order' AND connamespace = current_schema()::regnamespace")), 0)

    def test_incomplete_historical_subtype_aborts_upgrade_without_deleting_data(self):
        with mock.patch.dict(os.environ, {"DATABASE_URL": self.url}):
            command.downgrade(Config(str(ROOT / "alembic.ini")), "0041c")
        with self.database.transaction() as session:
            session.execute(delete(RequestSlot).where(RequestSlot.request_id == 1))
        with mock.patch.dict(os.environ, {"DATABASE_URL": self.url}), self.assertRaises(IntegrityError):
            command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(text("SELECT version_num FROM alembic_version")), "0041c")
            self.assertEqual(session.scalar(text("SELECT count(*) FROM resource_request")), 14)
            self.assertEqual(session.scalar(text("SELECT count(*) FROM pg_proc WHERE proname = 'ras_check_request_shape' AND pronamespace = current_schema()::regnamespace")), 0)


class PostgresRecoveryTests(PostgresTestCase):
    def test_real_backup_restore_preserves_published_results_and_survives_app_restart(self):
        container = os.environ.get("POSTGRES_TEST_TOOLS_CONTAINER")
        tools = os.environ.get("POSTGRES_TEST_TOOLS_DIR", "")
        def tool(name):
            if container:
                return ["docker", "exec", "-i", "-e", "PGUSER", "-e", "PGPASSWORD", container, name]
            executable = str(Path(tools) / (name + ".exe" if os.name == "nt" else name)) if tools else shutil.which(name)
            if not executable or not Path(executable).is_file():
                self.skipTest("Real recovery requires matching PostgreSQL pg_dump/pg_restore tools.")
            return [executable]
        dump, restore = tool("pg_dump"), tool("pg_restore")
        with TemporaryDirectory() as directory:
            copy_inputs(Path(directory))
            import_csv(self.database, directory)
        repository = Repository(self.database)
        result = execute_allocation(repository, EngineGateway(ROOT))
        original_view = repository.read_view()
        url = database_url(self.url)
        env = os.environ.copy()
        env.update(PGHOST=url.host or "localhost", PGPORT=str(url.port or 5432), PGUSER=url.username or "postgres",
                   PGPASSWORD=url.password or "")
        backup = subprocess.run(dump + ["--format=custom", "--schema=" + self.schema, "--dbname=" + url.database],
                                env=env, capture_output=True, check=True, timeout=60).stdout
        self.assertTrue(backup.startswith(b"PGDMP"))
        restored_name = "ras_restore_" + uuid.uuid4().hex
        admin = create_engine(url.set(database="postgres", query={}), isolation_level="AUTOCOMMIT")
        try:
            with admin.connect() as connection:
                connection.execute(text('CREATE DATABASE "' + restored_name + '"'))
        finally:
            admin.dispose()
        # Never overwrite/drop an existing DB. The newly created recovery DB is retained.
        subprocess.run(restore + ["--exit-on-error", "--no-owner", "--no-privileges", "--dbname=" + restored_name],
                       input=backup, env=env, capture_output=True, check=True, timeout=60)
        recovered = Database(url.set(database=restored_name))
        try:
            restored = Repository(recovered)
            self.assertEqual(restored.read_view()[1:], original_view[1:])
            self.assertGreater(restored.save_request(new_request()), 45)
            recovered.dispose()
            # New pool/session/application instance, not an in-memory result cache.
            self.assertEqual(Repository(recovered).read_view()[1]["result"], result)
            app_env = env | {"DATABASE_URL": url.set(database=restored_name).render_as_string(hide_password=False)}
            restarted = subprocess.run([sys.executable, "-c",
                                       "from web.app import app; r=app.test_client().get('/allocation-summary'); "
                                       "assert r.status_code == 200; assert b'Approved' in r.data; print('Flask restart passed')"],
                                      cwd=ROOT, env=app_env, capture_output=True, text=True, timeout=30)
            self.assertEqual(restarted.returncode, 0, restarted.stderr)
            print("Verified isolated restore database: " + restored_name)
        finally:
            recovered.dispose()
