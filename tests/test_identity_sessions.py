"""Identity reads must not trust cached edits, flush or own the caller transaction."""

import secrets
from datetime import timedelta
from unittest import mock

from sqlalchemy import event

from postgres_fixtures import PostgresTestCase
from test_appointments import seed_appointments, START
from web.account_service import AccountService
from web.persistence.models import CalendarBlock, LoginAccount, Role, User


class IdentitySessionTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        seed_appointments(self.database)
        self.accounts = AccountService(self.database)
        self.accounts.provision(1, "identity-session-fixture", secrets.token_urlsafe(24))

    def test_owned_and_supplied_session_resolve_the_same_identity_without_nested_transaction(self):
        expected = self.accounts.identity(1, 1)
        with self.database.transaction(read_only=True) as session:
            with mock.patch.object(self.database, "transaction", side_effect=AssertionError("No nested transaction")):
                actual = self.accounts.identity(1, 1, session=session)
            self.assertEqual(actual, expected)
            self.assertTrue(session.in_transaction())
            self.assertTrue(session.autoflush)

    def test_dirty_privilege_cannot_become_a_principal_or_flush_to_database(self):
        statements = []
        def capture(_, __, statement, *args):
            statements.append(statement.lstrip().split()[0].upper())
        with self.database.sessions() as session:
            account = session.get(LoginAccount, 1)
            account.administrator = True
            event.listen(self.database.engine, "before_cursor_execute", capture)
            try:
                principal = self.accounts.identity(1, 1, session=session)
                self.assertIsNone(principal)
                self.assertFalse(set(statements) & {"UPDATE", "INSERT", "DELETE"})
                self.assertIn(account, session.dirty)
                self.assertTrue(session.in_transaction())
                self.assertTrue(session.autoflush)
            finally:
                event.remove(self.database.engine, "before_cursor_execute", capture)
                session.rollback()
        self.assertFalse(self.accounts.identity(1, 1).administrator)

    def test_clean_identity_cache_from_an_earlier_transaction_does_not_hide_revocation(self):
        with self.database.sessions() as session:
            cached = [session.get(LoginAccount, 1), session.get(User, 1)]
            session.commit()
            self.accounts.revoke(1)
            try:
                self.assertIsNone(self.accounts.identity(1, 1, session=session))
                self.assertEqual(cached[0].session_version, 2)
            finally:
                session.rollback()

    def test_clean_user_cache_from_an_earlier_transaction_does_not_hide_inactivation(self):
        with self.database.sessions() as session:
            cached = [session.get(LoginAccount, 1), session.get(User, 1)]
            session.commit()
            with self.database.transaction() as writer:
                writer.get(User, 1).status = "inactive"
            try:
                self.assertIsNone(self.accounts.identity(1, 1, session=session))
                self.assertEqual(cached[1].status, "inactive")
            finally:
                session.rollback()

    def test_clean_role_cache_is_refreshed_from_the_current_transaction(self):
        with self.database.sessions() as session:
            user = session.get(User, 1)
            cached = session.get(Role, user.primary_role_id)
            session.commit()
            with self.database.transaction() as writer:
                writer.get(Role, cached.id).name = "Synthetic former student role"
            try:
                self.assertEqual(self.accounts.identity(1, 1, session=session).role, "Synthetic former student role")
            finally:
                session.rollback()

    def test_pending_insert_and_delete_are_denied_without_flush_or_transaction_ownership(self):
        with self.database.transaction() as writer:
            block = CalendarBlock(user_id=1, start_at=START, end_at=START + timedelta(hours=1), reason="Synthetic")
            writer.add(block)
            writer.flush()
            key = block.id
        for kind in ("insert", "delete"):
            with self.subTest(kind=kind), self.database.sessions() as session:
                if kind == "insert":
                    session.add(CalendarBlock(user_id=1, start_at=START, end_at=START + timedelta(hours=1), reason="Pending synthetic"))
                else:
                    session.delete(session.get(CalendarBlock, key))
                try:
                    with mock.patch.object(session, "flush", side_effect=AssertionError("Identity must not flush")), \
                         mock.patch.object(session, "commit", side_effect=AssertionError("Caller owns commit")), \
                         mock.patch.object(session, "rollback", side_effect=AssertionError("Caller owns rollback")):
                        self.assertIsNone(self.accounts.identity(1, 1, session=session))
                finally:
                    session.rollback()

    def test_refresh_respects_the_supplied_repeatable_read_snapshot(self):
        with self.database.transaction(read_only=True) as session:
            previous = self.accounts.identity(1, 1, session=session)
            self.accounts.revoke(1)
            self.assertEqual(self.accounts.identity(1, 1, session=session), previous)
        self.assertIsNone(self.accounts.identity(1, 1))

    def test_invalid_identity_keys_do_not_open_an_owned_transaction(self):
        with mock.patch.object(self.database, "transaction", side_effect=AssertionError("Invalid keys cannot query")):
            for uid, version in ((True, 1), (1, True), (None, 1), (1, "1")):
                self.assertIsNone(self.accounts.identity(uid, version))
