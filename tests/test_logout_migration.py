"""Upgrade existing accounts without resetting logins or dropping logout denials."""

import os
from unittest import mock

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text

from postgres_fixtures import PostgresTestCase, ROOT
from web.account_service import AccountService
from web.persistence.models import LoggedOutSession, LoginAccount, Role, User


class LogoutMigrationTests(PostgresTestCase):
    migration_target = '0051a'

    def setUp(self):
        super().setUp()
        # Seed only tables present in the old schema, using its existing contract.
        # The modern importer correctly requires every current application table.
        with self.database.transaction() as session:
            session.add(Role(id=1, name='Instructor'))
            session.flush()
            session.add(User(id=2, source_order=1, name='Synthetic legacy instructor', primary_role_id=1))
        AccountService(self.database).provision(2, 'logout-migration', 'Synthetic-logout-migration-password')
        self.token = 'SyntheticLegacySessionNonce_0123456789'

    def migrate(self, target, *, downgrade=False):
        with mock.patch.dict(os.environ, {'DATABASE_URL': self.url}):
            (command.downgrade if downgrade else command.upgrade)(Config(str(ROOT / 'alembic.ini')), target)

    def test_upgrade_preserves_account_and_starts_without_guessed_denials(self):
        with self.database.transaction(read_only=True) as session:
            before = session.get(LoginAccount, 2)
            expected = (before.username, before.password_hash, before.session_version)
        self.migrate('head')
        with self.database.transaction(read_only=True) as session:
            after = session.get(LoginAccount, 2)
            self.assertEqual((after.username, after.password_hash, after.session_version), expected)
            self.assertEqual(list(session.scalars(select(LoggedOutSession))), [])
        accounts = AccountService(self.database)
        self.assertIsNotNone(accounts.identity(2, 1, session_token=self.token))
        accounts.revoke_session(2, 1, self.token)
        self.assertIsNone(accounts.identity(2, 1, session_token=self.token))

    def test_empty_downgrade_and_reupgrade_are_reversible(self):
        self.migrate('head')
        self.migrate('0051a', downgrade=True)
        self.assertNotIn('logged_out_session', inspect(self.database.engine).get_table_names())
        self.assertIsNotNone(AccountService(self.database).identity(2, 1))
        self.migrate('head')
        self.assertIsNotNone(AccountService(self.database).identity(2, 1, session_token=self.token))

    def test_populated_downgrade_refuses_to_reactivate_logged_out_cookies(self):
        self.migrate('head')
        AccountService(self.database).revoke_session(2, 1, self.token)
        with self.assertRaisesRegex(RuntimeError, 'Cannot discard logout revocations'):
            self.migrate('0051a', downgrade=True)
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(text('SELECT version_num FROM alembic_version')), self.head_revision)
            self.assertEqual(len(list(session.scalars(select(LoggedOutSession)))), 1)
        self.assertIsNone(AccountService(self.database).identity(2, 1, session_token=self.token))
