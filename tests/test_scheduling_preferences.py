"""Internal self-preference persistence against owned synthetic PostgreSQL schemas."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import date
import json
import os
import threading
import traceback
from unittest import mock

from alembic import command
from alembic.config import Config
from alembic.operations import Operations
from flask import Flask, g, session as login_session
from sqlalchemy import delete, event, func, inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError

from postgres_fixtures import PostgresTestCase, ROOT
from test_preference_values import preference_values
from web.account_service import AccountService, Principal
from web.persistence.database import Database
from web.persistence.models import Base, LoginAccount, Role, SchedulingPreferenceRevision as Revision, User
from web.preference_values import PreferenceError, PreferenceUnavailable
from web.scheduling_preference_service import (MAX_REVISION, PreferenceAccessDenied, PreferenceConflict,
    PreferenceStorageError, SchedulingPreferenceService)


def document(**changes):
    return {'preference_version': 1, **preference_values(**changes)}


class SchedulingPreferenceTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        self.app = Flask(__name__)
        self.app.secret_key = 'isolated-preference-fixture-not-production'
        with self.database.transaction() as session:
            for uid, role in enumerate(('Student', 'Instructor', 'Staff', 'TeachingAssistant', 'Administrator'), 1):
                session.add(Role(id=uid, name=role))
            session.flush()
            for uid in range(1, 6):
                session.add(User(id=uid, source_order=uid, name=f'Fictional preference owner {uid}', primary_role_id=uid))
            session.flush()
            for uid in range(1, 6):
                session.add(LoginAccount(user_id=uid, username=f'preference-fixture-{uid}',
                    password_hash='not-a-real-password-hash', session_version=1))
        self.service = SchedulingPreferenceService(self.database)

    @contextmanager
    def authenticated(self, uid=1, version=1):
        with self.app.test_request_context('/internal-test-only'):
            login_session['user_id'], login_session['session_version'] = uid, version
            g.principal = AccountService(self.database).identity(uid, version)
            g.authenticated_database_url = self.database.engine.url
            yield

    def count(self):
        with self.database.transaction(read_only=True) as session:
            return session.scalar(select(func.count()).select_from(Revision))

    def test_each_existing_role_can_only_manage_its_own_complete_profile(self):
        for uid in range(1, 6):
            with self.subTest(uid=uid), self.authenticated(uid):
                self.assertEqual((self.service.current().state, self.service.current().revision), ('missing', 0))
                saved = self.service.replace(0, document(desired_gap_minutes=uid))
                self.assertEqual((saved.state, saved.revision, saved.values.desired_gap), ('configured', 1, uid))
                self.assertIsNotNone(saved.created_at.tzinfo)
                self.assertEqual(len(self.service.history().entries), 1)
        self.assertEqual(self.count(), 5)

    def test_no_context_or_untrusted_principal_is_rejected(self):
        with self.assertRaises(PreferenceAccessDenied):
            self.service.current()
        with self.authenticated():
            for fake in (None, {'user_id': 1}, Principal(2, 'Forged', 'Administrator', True, 1),
                         replace(g.principal, administrator=True), replace(g.principal, name='Forged')):
                with self.subTest(fake=type(fake).__name__):
                    original = g.principal
                    g.principal = fake
                    with self.assertRaises(PreferenceAccessDenied):
                        self.service.replace(0, document())
                    g.principal = original
        self.assertEqual(self.count(), 0)

    def test_cookie_identifiers_must_match_server_principal_and_types(self):
        with self.authenticated():
            for uid, version in ((2, 1), (True, 1), (1, True), (1, '1'), (1, 2)):
                login_session['user_id'], login_session['session_version'] = uid, version
                with self.subTest(uid=uid, version=version), self.assertRaises(PreferenceAccessDenied):
                    self.service.current()

    def test_owner_fields_and_synthetic_provenance_cannot_be_supplied(self):
        with self.authenticated():
            for key in ('owner', 'owner_id', 'actor_id', 'revision', 'synthetic', 'origin', 'provenance', 'state'):
                with self.subTest(key=key), self.assertRaises(PreferenceError):
                    self.service.replace(0, {**document(), key: 2})
            with self.assertRaises(TypeError):
                self.service.current(owner_id=2)
        self.assertEqual(self.count(), 0)

    def test_administrator_and_invitee_have_no_cross_user_history_access(self):
        with self.authenticated(1):
            self.service.replace(0, document())
        for uid in (2, 3, 5):
            with self.authenticated(uid):
                self.assertEqual(self.service.current().state, 'missing')
                self.assertEqual(self.service.history().entries, ())

    def test_revocation_disabled_user_and_disabled_account_deny_stale_context(self):
        for kind in ('revoked', 'user', 'account'):
            with self.subTest(kind=kind), self.authenticated():
                with self.database.transaction() as writer:
                    account = writer.get(LoginAccount, 1)
                    if kind == 'revoked':
                        account.session_version += 1
                    elif kind == 'account':
                        account.enabled = False
                    else:
                        writer.get(User, 1).status = 'inactive'
                with self.assertRaises(PreferenceAccessDenied):
                    self.service.replace(0, document())
            with self.database.transaction() as writer:
                account = writer.get(LoginAccount, 1)
                account.session_version, account.enabled = 1, True
                writer.get(User, 1).status = 'active'
        self.assertEqual(self.count(), 0)

    def test_deleting_login_retains_identity_history_but_denies_access(self):
        with self.authenticated():
            self.service.replace(0, document())
            with self.database.transaction() as writer:
                writer.execute(delete(LoginAccount).where(LoginAccount.user_id == 1))
            with self.assertRaises(PreferenceAccessDenied):
                self.service.current()
            with self.assertRaises(PreferenceAccessDenied):
                self.service.deactivate(1)
        with self.database.transaction(read_only=True) as session:
            self.assertIsNotNone(session.get(User, 1))
        self.assertEqual(self.count(), 1)

    def test_reprovision_with_new_session_version_retains_owner_not_login_identity(self):
        with self.authenticated():
            self.service.replace(0, document())
        with self.database.transaction() as writer:
            writer.execute(delete(LoginAccount).where(LoginAccount.user_id == 1))
        with self.database.transaction() as writer:
            writer.add(LoginAccount(user_id=1, username='replacement-fixture-login',
                password_hash='not-a-real-password', session_version=2))
        with self.authenticated(version=1), self.assertRaises(PreferenceAccessDenied):
            self.service.current()
        with self.authenticated(version=2):
            self.assertEqual(self.service.current().revision, 1)

    def test_supported_password_reset_preserves_history_and_rejects_old_sessions(self):
        with self.authenticated():
            self.service.replace(0, document())
            AccountService(self.database).provision(1, 'reset-fixture', 'fictional-reset-password', reset=True)
            for action in (self.service.current, self.service.history, lambda: self.service.deactivate(1)):
                with self.assertRaises(PreferenceAccessDenied):
                    action()
        with self.authenticated(version=2):
            self.assertEqual(self.service.current().revision, 1)
        self.assertEqual(self.count(), 1)

    def test_every_role_can_deactivate_only_its_own_preferences(self):
        for uid in range(1, 6):
            with self.authenticated(uid):
                self.service.replace(0, document())
                self.service.deactivate(1)
                self.assertEqual(self.service.current().stored_status, 'deactivated')
                self.assertEqual([row.revision for row in self.service.history().entries], [2, 1])
        self.assertEqual(self.count(), 10)

    def test_wrong_authenticated_database_and_session_binding_are_denied(self):
        other = Database(self.database.url.set(database='not-the-authenticated-database'))
        self.addCleanup(other.dispose)
        with self.authenticated():
            with mock.patch.object(other, 'transaction', side_effect=AssertionError('Do not connect')):
                with self.assertRaises(PreferenceAccessDenied):
                    SchedulingPreferenceService(other).current()
            g.authenticated_database_url = str(self.database.url)
            with self.assertRaises(PreferenceAccessDenied):
                self.service.current()

    def test_same_database_another_pool_is_allowed_and_dirty_session_is_denied(self):
        other = Database(self.database.url)
        self.addCleanup(other.dispose)
        with self.authenticated():
            self.assertEqual(SchedulingPreferenceService(other).current().state, 'missing')
            with self.database.sessions() as dirty:
                dirty.get(User, 1).name = 'PRIVATE-MARKER'
                @contextmanager
                def injected(**kwargs):
                    yield dirty
                with mock.patch.object(self.database, 'transaction', injected):
                    with self.assertRaises(PreferenceAccessDenied):
                        self.service.current()
                dirty.rollback()

    def test_misbound_session_is_denied_before_identity_or_preference_queries(self):
        foreign = Database(self.database.url.set(database='unrelated-fixture-database'))
        self.addCleanup(foreign.dispose)
        @contextmanager
        def injected(**kwargs):
            fake = mock.Mock()
            fake.no_autoflush = mock.MagicMock()
            fake.get_bind.return_value = foreign.engine
            yield fake
        with self.authenticated(), mock.patch.object(self.database, 'transaction', injected), \
                mock.patch.object(AccountService, 'identity', side_effect=AssertionError('Must not query')):
            with self.assertRaises(PreferenceAccessDenied):
                self.service.current()

    def test_missing_locked_account_cannot_be_replaced_by_a_later_identity_read(self):
        transaction = self.database.transaction
        @contextmanager
        def injected(**kwargs):
            with transaction(**kwargs) as session:
                original = session.get
                def missing(model, *args, **kwargs):
                    if model is LoginAccount and kwargs.get('with_for_update'):
                        return None
                    return original(model, *args, **kwargs)
                with mock.patch.object(session, 'get', side_effect=missing):
                    yield session
        with self.authenticated(), mock.patch.object(self.database, 'transaction', injected), \
                mock.patch.object(AccountService, 'identity', side_effect=AssertionError('No unlocked identity fallback')):
            with self.assertRaises(PreferenceAccessDenied):
                self.service.replace(0, document())
        self.assertEqual(self.count(), 0)

    def test_latest_future_revision_supersedes_and_deactivation_never_resurrects(self):
        with self.authenticated():
            self.service.replace(0, document())
            self.service.replace(1, document(effective={'from': '2090-01-01', 'until': '2090-12-31'}))
            self.assertEqual(self.service.current().values.first, date(2090, 1, 1))
            self.service.deactivate(2)
            current = self.service.current()
            self.assertEqual((current.state, current.stored_status, current.revision), ('missing', 'deactivated', 3))
            self.assertIsNone(current.values)
            self.assertEqual([r.revision for r in self.service.history().entries], [3, 2, 1])

    def test_history_is_bounded_cursor_scoped_and_private_in_repr(self):
        with self.authenticated():
            for revision in range(4):
                self.service.replace(revision, document())
            page = self.service.history(limit=2)
            self.assertEqual([r.revision for r in page.entries], [4, 3])
            self.assertEqual(page.next_before_revision, 3)
            tail = self.service.history(limit=2, before_revision=page.next_before_revision)
            self.assertEqual([r.revision for r in tail.entries], [2, 1])
            self.assertIsNone(tail.next_before_revision)
            for value in (page, page.entries[0], page.entries[0].values):
                self.assertNotIn('2030', repr(value))
                self.assertNotIn('Istanbul', repr(value))
            for kwargs in ({'limit': 0}, {'limit': 101}, {'limit': True}, {'before_revision': 0}):
                with self.assertRaises(PreferenceError):
                    self.service.history(**kwargs)

    def test_versions_missing_zero_indifference_and_signed_revision_boundaries(self):
        with self.authenticated():
            for gap in (0, 'indifferent'):
                revision = self.service.current().revision
                self.assertEqual(self.service.replace(revision, document(desired_gap_minutes=gap)).values.desired_gap, gap)
            for invalid in (True, -1, 1.0, '2', 2**63):
                with self.subTest(invalid=invalid), self.assertRaises(PreferenceError):
                    self.service.deactivate(invalid)
            with self.assertRaises(PreferenceConflict):
                self.service.replace(0, document())
            with self.assertRaises(PreferenceUnavailable):
                self.service.replace(2, {**document(), 'preference_version': 2})
            with self.database.transaction() as writer:
                writer.add(Revision(owner_id=1, revision=MAX_REVISION, contract_version=1, status='deactivated'))
            with self.assertRaises(PreferenceConflict):
                self.service.deactivate(MAX_REVISION)

    def test_unknown_and_unsupported_stored_data_do_not_become_neutral(self):
        with self.authenticated():
            self.service.replace(0, document())
            with self.database.transaction() as writer:
                writer.add(Revision(owner_id=1, revision=2, contract_version=2, status='deactivated'))
            self.assertEqual(self.service.current().state, 'unsupported')
            self.assertIsNone(self.service.current().values)
            with self.database.transaction() as writer:
                writer.add(Revision(owner_id=1, revision=3, contract_version=1, status='configured',
                    timezone='UTC', effective_from=date(2030, 1, 1), effective_until=date(2030, 12, 31),
                    preferred_weekdays=[], preferred_windows=[{'private': 'PRIVATE-MARKER'}],
                    gap_indifferent=True))
            result = self.service.current()
            self.assertEqual(result.state, 'unknown')
            self.assertNotIn('PRIVATE-MARKER', json.dumps(result.document()))

    def test_overnight_foreign_timezone_and_original_endpoints_roundtrip(self):
        with self.authenticated():
            windows = [{'weekday': 7, 'start': '22:00', 'end': '02:00'}]
            self.service.replace(0, document(timezone='America/New_York', preferred_windows=windows))
            self.assertEqual(self.service.current().values.document()['preferred_windows'], windows)
            self.assertEqual(self.service.current().values.timezone, 'America/New_York')

    def test_historical_updates_deletes_truncate_and_owner_deletion_are_blocked(self):
        with self.authenticated():
            self.service.replace(0, document())
        for sql in ('UPDATE scheduling_preference_revision SET revision=2',
                    'DELETE FROM scheduling_preference_revision', 'TRUNCATE scheduling_preference_revision'):
            with self.subTest(sql=sql), self.assertRaises(IntegrityError), self.database.transaction() as session:
                session.execute(text(sql))
        # Retire the login first; the university-identity FK still retains history.
        with self.database.transaction() as session:
            session.execute(delete(LoginAccount).where(LoginAccount.user_id == 1))
        with self.assertRaises(IntegrityError), self.database.transaction() as session:
            session.execute(delete(User).where(User.id == 1))
        self.assertEqual(self.count(), 1)

    def test_database_constraints_and_no_default_or_seeded_preference_values(self):
        self.assertEqual(self.count(), 0)
        for changes in ({'revision': 0}, {'contract_version': 0}, {'status': 'unknown'}, {'owner_id': 999},
                        {'timezone': 'UTC'}, {'gap_indifferent': True}, {'preferred_windows': []}):
            values = dict(owner_id=1, revision=1, contract_version=1, status='deactivated')
            values.update(changes)
            with self.subTest(changes=changes), self.assertRaises(IntegrityError), self.database.transaction() as session:
                session.add(Revision(**values))
                session.flush()

    def race(self, initial, operations):
        barrier = threading.Barrier(2)
        def worker(operation):
            with self.authenticated():
                barrier.wait(timeout=10)
                try:
                    return operation(initial)
                except PreferenceConflict:
                    return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker, op) for op in operations]
            results = [future.result(timeout=20) for future in futures]
        self.assertEqual(results.count('conflict'), 1)

    def test_concurrent_initial_creation_has_one_winner(self):
        self.race(0, (lambda r: self.service.replace(r, document()), lambda r: self.service.replace(r, document())))
        self.assertEqual(self.count(), 1)

    def test_concurrent_update_and_deactivation_have_one_winner(self):
        with self.authenticated():
            self.service.replace(0, document())
        self.race(1, (lambda r: self.service.replace(r, document(desired_gap_minutes=0)), self.service.deactivate))
        self.assertEqual(self.count(), 2)
        with self.authenticated():
            self.assertEqual(self.service.current().revision, 2)

    def test_concurrent_updates_with_the_same_revision_have_one_winner(self):
        with self.authenticated():
            self.service.replace(0, document())
        self.race(1, (lambda r: self.service.replace(r, document(desired_gap_minutes=5)),
                      lambda r: self.service.replace(r, document(desired_gap_minutes=10))))
        self.assertEqual(self.count(), 2)

    def test_concurrent_deactivations_have_one_winner_without_resurrection(self):
        with self.authenticated():
            self.service.replace(0, document())
        self.race(1, (self.service.deactivate, self.service.deactivate))
        self.assertEqual(self.count(), 2)
        with self.authenticated():
            current = self.service.current()
            self.assertEqual((current.revision, current.state, current.stored_status), (2, 'missing', 'deactivated'))

    def test_account_lock_timeout_is_sanitized_and_saves_nothing(self):
        short = Database(self.database.url, lock_timeout=.1)
        self.addCleanup(short.dispose)
        with self.database.transaction() as blocker, self.authenticated():
            blocker.get(LoginAccount, 1, with_for_update=True)
            with self.assertRaises(PreferenceStorageError) as caught:
                SchedulingPreferenceService(short).replace(0, document())
            self.assertIsNone(caught.exception.__cause__)
            self.assertNotIn('login_account', str(caught.exception))
        self.assertEqual(self.count(), 0)

    def test_real_database_deadlock_is_sanitized_and_rolls_back(self):
        locked, share_attempt = threading.Event(), threading.Event()
        other = Database(self.database.url)
        self.addCleanup(other.dispose)
        transaction = self.database.transaction

        @contextmanager
        def fast_deadlock_detection(**kwargs):
            with transaction(**kwargs) as session:
                session.execute(text("SET LOCAL deadlock_timeout='100ms'"))
                yield session

        def capture(_, __, statement, *args):
            if 'FOR SHARE' in statement:
                share_attempt.set()

        def blocker():
            with other.transaction() as session:
                session.execute(text("SET LOCAL deadlock_timeout='5s'"))
                session.get(User, 1, with_for_update=True)
                locked.set()
                if not share_attempt.wait(10):
                    raise AssertionError('Preference writer did not request the user lock')
                session.get(LoginAccount, 1, with_for_update=True)

        with self.authenticated(), ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(blocker)
            self.assertTrue(locked.wait(10))
            event.listen(self.database.engine, 'before_cursor_execute', capture)
            try:
                with mock.patch.object(self.database, 'transaction', fast_deadlock_detection):
                    with self.assertRaises(PreferenceStorageError):
                        self.service.replace(0, document())
            finally:
                event.remove(self.database.engine, 'before_cursor_execute', capture)
            pending.result(timeout=10)
        self.assertEqual(self.count(), 0)

    def test_commit_failure_never_returns_success_or_persists_a_revision(self):
        def fail_commit(connection):
            raise DBAPIError('PRIVATE-MARKER', {'private': 'PRIVATE-MARKER'}, Exception('PRIVATE-MARKER'))
        with self.authenticated():
            event.listen(self.database.engine, 'commit', fail_commit)
            try:
                with self.assertRaises(PreferenceStorageError) as caught:
                    self.service.replace(0, document())
                self.assertNotIn('PRIVATE-MARKER', str(caught.exception))
            finally:
                event.remove(self.database.engine, 'commit', fail_commit)
            self.assertEqual(self.service.current().state, 'missing')
        self.assertEqual(self.count(), 0)

    def test_other_schema_binding_is_denied_even_with_matching_identity_rows(self):
        # A second owned schema has the same fictional IDs, version, names and roles.
        fixture = SchedulingPreferenceTests('test_each_existing_role_can_only_manage_its_own_complete_profile')
        try:
            fixture.setUp()
            with fixture.authenticated():
                fixture.service.replace(0, document(desired_gap_minutes=123))
            with self.authenticated(), mock.patch.object(AccountService, 'identity', side_effect=AssertionError('No cross-schema read')):
                with self.assertRaises(PreferenceAccessDenied):
                    fixture.service.current()
                with self.assertRaises(PreferenceAccessDenied):
                    fixture.service.history()
                with self.assertRaises(PreferenceAccessDenied):
                    fixture.service.deactivate(1)
        finally:
            fixture.doCleanups()
        self.assertEqual(self.count(), 0)

    def test_direct_sql_semantic_corruption_fails_closed_without_older_fallback(self):
        invalid = ({'preferred_weekdays': [1, 1]},
                   {'preferred_windows': [{'weekday': 1, 'start': '11:00', 'end': '11:00'}]},
                   {'preferred_windows': [{'private': 'PRIVATE-MARKER'}]},
                   {'preferred_windows': [{'weekday': 1, 'start': '09:00', 'end': '11:00'},
                                          {'weekday': 1, 'start': '10:00', 'end': '12:00'}]})
        with self.authenticated():
            self.service.replace(0, document())
            for revision, changes in enumerate(invalid, 2):
                values = dict(owner_id=1, revision=revision, contract_version=1, status='configured',
                    timezone='UTC', effective_from=date(2030, 1, 1), effective_until=date(2030, 12, 31),
                    preferred_weekdays=[], preferred_windows=[], gap_indifferent=True)
                values.update(changes)
                with self.database.transaction() as writer:
                    writer.add(Revision(**values))
                current = self.service.current()
                self.assertEqual((current.revision, current.state, current.values), (revision, 'unknown', None))
                self.assertNotIn('PRIVATE-MARKER', json.dumps(current.document()))

    def test_revocation_serializes_with_an_in_progress_write(self):
        locked, release, revoked = threading.Event(), threading.Event(), threading.Event()
        original = self.service._latest
        def pause(session, owner):
            locked.set()
            if not release.wait(8):
                raise AssertionError('Writer release missing')
            return original(session, owner)
        def writer():
            with self.authenticated(), mock.patch.object(self.service, '_latest', pause):
                return self.service.replace(0, document())
        def revoke():
            AccountService(self.database).revoke(1)
            revoked.set()
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = pool.submit(writer)
            self.assertTrue(locked.wait(8))
            other = pool.submit(revoke)
            try:
                self.assertFalse(revoked.wait(.15))
            finally:
                release.set()
            self.assertEqual(pending.result(timeout=10).revision, 1)
            other.result(timeout=10)
        with self.authenticated(version=1), self.assertRaises(PreferenceAccessDenied):
            self.service.current()

    def test_read_snapshot_does_not_mix_identity_with_later_preference_revision(self):
        reading, release = threading.Event(), threading.Event()
        original = self.service._latest
        def pause(session, owner):
            reading.set()
            if not release.wait(8):
                raise AssertionError('Reader release missing')
            return original(session, owner)
        def reader():
            with self.authenticated(), mock.patch.object(self.service, '_latest', pause):
                return self.service.current()
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(reader)
            self.assertTrue(reading.wait(8))
            try:
                # Separate service avoids the deliberately paused read helper.
                with self.authenticated():
                    SchedulingPreferenceService(self.database).replace(0, document())
            finally:
                release.set()
            self.assertEqual(pending.result(timeout=10).state, 'missing')
        with self.authenticated():
            self.assertEqual(self.service.current().revision, 1)

    def test_database_failure_rolls_back_without_private_parameters_or_credentials(self):
        marker = 'PRIVATE-MARKER'
        with self.authenticated():
            def fail(row):
                raise DBAPIError('SQL-'+marker, {'private': marker}, Exception(marker))
            with mock.patch.object(self.service, '_view', fail):
                with self.assertRaises(PreferenceStorageError) as caught:
                    self.service.replace(0, document())
            self.assertEqual(caught.exception.state, 'unknown')
            self.assertNotIn(marker, str(caught.exception))
            self.assertEqual(self.count(), 0)
            self.assertEqual(self.service.current().state, 'missing')
            with mock.patch.object(self.service, '_latest', side_effect=DBAPIError(marker, {}, Exception(marker))):
                try:
                    self.service.current()
                except PreferenceStorageError:
                    rendered = traceback.format_exc()
            self.assertNotIn(marker, rendered)

    def test_get_uses_readonly_repeatable_read_and_sanitizes_write_attempt(self):
        with self.authenticated():
            original = self.service._latest
            def inspect(session, owner):
                self.assertFalse(session.autoflush)
                self.assertEqual(session.scalar(text('SHOW transaction_read_only')), 'on')
                self.assertEqual(session.scalar(text('SHOW transaction_isolation')), 'repeatable read')
                return original(session, owner)
            with mock.patch.object(self.service, '_latest', inspect):
                self.service.current()
            def mutate(session, owner):
                session.execute(text("UPDATE university_user SET name='PRIVATE-MARKER' WHERE id=1"))
            with mock.patch.object(self.service, '_latest', mutate), self.assertRaises(PreferenceStorageError):
                self.service.current()

    def test_writes_do_not_query_calendars_invoke_engines_or_modify_other_tables(self):
        def snapshot():
            with self.database.transaction(read_only=True) as session:
                return {name: session.execute(text(f'SELECT to_jsonb(t)::text FROM "{name}" t ORDER BY to_jsonb(t)::text')).scalars().all()
                        for name in Base.metadata.tables if name != Revision.__tablename__}
        before, statements = snapshot(), []
        def capture(_, __, statement, *args):
            statements.append(statement.lower())
        with self.authenticated():
            event.listen(self.database.engine, 'before_cursor_execute', capture)
            try:
                with mock.patch('subprocess.Popen', side_effect=AssertionError('No engine invocation')):
                    view = self.service.replace(0, json.dumps(document()).encode())
                    self.service.current()
                    self.service.history()
                    self.service.deactivate(1)
            finally:
                event.remove(self.database.engine, 'before_cursor_execute', capture)
        self.assertEqual(snapshot(), before)
        self.assertFalse(any(any(name in sql for name in ('appointment', 'calendar_block', 'application_state', 'professor_availability')) for sql in statements))
        from research.cdmcs.i3d.d1.contract import parse_preference
        with self.assertRaises(PreferenceError):
            parse_preference(view.document())
        self.assertFalse(any('preference' in str(rule) for rule in self.app.url_map.iter_rules()))


class PreferenceMigrationTests(PostgresTestCase):
    migration_target = '0049b'

    def setUp(self):
        super().setUp()
        with self.database.transaction() as session:
            session.add(Role(id=1, name='Student'))
            session.flush()
            session.add(User(id=1, source_order=1, name='Fictional retained identity', primary_role_id=1))

    def migrate(self, direction, target):
        with mock.patch.dict(os.environ, {'DATABASE_URL': self.url}):
            getattr(command, direction)(Config(str(ROOT / 'alembic.ini')), target)

    def test_additive_upgrade_creates_empty_table_and_matches_metadata(self):
        before = set(inspect(self.database.engine).get_table_names())
        self.migrate('upgrade', 'head')
        after = set(inspect(self.database.engine).get_table_names())
        self.assertEqual(after - before, {'scheduling_preference_revision', 'scheduling_cost_policy_revision',
            'scheduling_cost_policy_authority_revision', 'scheduling_cost_policy_event', 'scheduling_cost_policy_head',
            'request_eligibility', 'eligibility_event', 'allocation_eligibility'})
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Revision)), 0)
            self.assertEqual(session.get(User, 1).name, 'Fictional retained identity')
        with mock.patch.dict(os.environ, {'DATABASE_URL': self.url}):
            command.check(Config(str(ROOT / 'alembic.ini')))

    def test_empty_downgrade_is_reversible_and_preserves_identity(self):
        self.migrate('upgrade', 'head')
        self.migrate('downgrade', '0049b')
        self.assertNotIn('scheduling_preference_revision', inspect(self.database.engine).get_table_names())
        self.migrate('upgrade', 'head')
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.get(User, 1).name, 'Fictional retained identity')

    def test_populated_history_blocks_downgrade_without_data_loss(self):
        self.migrate('upgrade', 'head')
        with self.database.transaction() as session:
            session.add(Revision(owner_id=1, revision=1, contract_version=1, status='deactivated'))
        with self.assertRaisesRegex(RuntimeError, 'history'):
            self.migrate('downgrade', '0049b')
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(text('SELECT version_num FROM alembic_version')), '0051a')
            self.assertEqual(session.scalar(select(func.count()).select_from(Revision)), 1)

    def test_downgrade_locks_before_empty_check_so_a_concurrent_append_cannot_be_lost(self):
        self.migrate('upgrade', 'head')
        checked, release, committed = threading.Event(), threading.Event(), threading.Event()
        original = Operations.drop_table

        def pause(operations, name, *args, **kwargs):
            if name == Revision.__tablename__:
                checked.set()
                if not release.wait(10):
                    raise AssertionError('Downgrade release missing')
            return original(operations, name, *args, **kwargs)

        def append():
            try:
                with self.database.transaction() as session:
                    session.add(Revision(owner_id=1, revision=1, contract_version=1, status='deactivated'))
                committed.set()
                return 'committed'
            except ProgrammingError as error:
                self.assertEqual(error.orig.sqlstate, '42P01')
                return 'table_removed'

        with ThreadPoolExecutor(max_workers=2) as pool, mock.patch.object(Operations, 'drop_table', pause):
            downgrade = pool.submit(self.migrate, 'downgrade', '0049b')
            self.assertTrue(checked.wait(10))
            writer = pool.submit(append)
            try:
                self.assertFalse(committed.wait(.4), 'A committed append could be silently dropped')
            finally:
                release.set()
            downgrade.result(timeout=10)
            self.assertEqual(writer.result(timeout=10), 'table_removed')
        self.migrate('upgrade', 'head')

    def test_privileged_approved_erasure_is_possible_and_transactional_not_an_app_api(self):
        self.migrate('upgrade', 'head')
        with self.database.transaction() as session:
            session.add(Revision(owner_id=1, revision=1, contract_version=1, status='deactivated'))
        # DBA-owned disposable table only. Normal SQL is still rejected, even here.
        with self.assertRaisesRegex(RuntimeError, 'rollback'), self.database.transaction() as session:
            session.execute(text('ALTER TABLE scheduling_preference_revision DISABLE TRIGGER preference_history_immutable'))
            session.execute(delete(Revision).where(Revision.owner_id == 1))
            raise RuntimeError('fixture rollback')
        with self.assertRaises(IntegrityError), self.database.transaction() as session:
            session.execute(delete(Revision))
        with self.database.transaction() as session:
            session.execute(text('ALTER TABLE scheduling_preference_revision DISABLE TRIGGER preference_history_immutable'))
            session.execute(delete(Revision).where(Revision.owner_id == 1))
            session.execute(text('ALTER TABLE scheduling_preference_revision ENABLE TRIGGER preference_history_immutable'))
        self.migrate('downgrade', '0049b')
        with self.database.transaction(read_only=True) as session:
            self.assertIsNotNone(session.get(User, 1))
