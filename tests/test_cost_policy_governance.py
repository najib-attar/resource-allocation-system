"""Internal governance against disposable PostgreSQL and fictional authorities."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import threading
from unittest import mock

from flask import Flask, g, session as login_session
from sqlalchemy import event, func, select, text, update
from sqlalchemy.exc import OperationalError

from postgres_fixtures import PostgresTestCase
from test_cost_policy_persistence import authority_row, policy_row
from test_cost_policy_values import policy_document, parse
from web.account_service import AccountService, Principal
from web.cost_policy_service import (CostPolicyService, MAX_REVISION, PolicyAccessDenied,
    PolicyConflict, PolicyStorageError)
from web.persistence.database import Database
from web.persistence.models import (LoginAccount, Role, User, SchedulingCostPolicyAuthorityRevision as Authority,
    SchedulingCostPolicyRevision as Revision, SchedulingCostPolicyEvent as Event, SchedulingCostPolicyHead as Head)
from web.preference_values import PreferenceError, PreferenceUnavailable
from research.cdmcs.i3d.d1.contract import parse_policy as synthetic_policy


NOW = datetime(2030, 6, 1, tzinfo=timezone.utc)


class CostPolicyGovernanceTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        self.app = Flask(__name__)
        self.app.secret_key = 'fictional-internal-governance-test-only'
        with self.database.transaction() as session:
            for uid, role in enumerate(('Student', 'Instructor', 'Staff', 'TeachingAssistant', 'Administrator'), 1):
                session.add(Role(id=uid, name=role))
            session.flush()
            for uid in range(1, 11):
                session.add(User(id=uid, source_order=uid, name=f'Fictional policy person {uid}', primary_role_id=(uid-1)%5+1))
            session.flush()
            for uid in range(1, 11):
                session.add(LoginAccount(user_id=uid, username=f'policy-fixture-{uid}',
                    password_hash='fictional-not-a-password-hash', session_version=1))
            session.add_all([authority_row(1), authority_row(2, 'approve'), authority_row(3, 'audit')])
        self.service = CostPolicyService(self.database, university_timezone='Europe/Istanbul')
        timer = mock.patch.object(CostPolicyService, '_now', return_value=NOW)
        timer.start(); self.addCleanup(timer.stop)

    @contextmanager
    def authenticated(self, uid=1, version=1):
        with self.app.test_request_context('/internal-fixture-only'):
            login_session['user_id'], login_session['session_version'] = uid, version
            g.principal = AccountService(self.database).identity(uid, version)
            g.authenticated_database_url = self.database.engine.url
            yield

    def propose(self, expected=0, revision=1, **changes):
        with self.authenticated(1):
            return self.service.propose(expected, policy_document(revision=revision, **changes))

    def decide(self, kind, expected, revision=1, digest=None):
        digest = digest or parse(policy_document(revision=revision)).content_digest
        with self.authenticated(2):
            return getattr(self.service, kind)(expected, revision, digest, 'Fictional explicit governance rationale')

    def active(self):
        self.propose(); self.decide('approve', 1); return self.decide('activate', 2)

    def read(self):
        with self.authenticated(3): return self.service.current()

    def totals(self):
        with self.database.transaction(read_only=True) as session:
            return tuple(session.scalar(select(func.count()).select_from(model)) for model in (Revision, Event, Head))

    def test_missing_head_read_does_not_initialize_and_roles_grant_nothing(self):
        self.assertEqual((self.read().head_version, self.read().state), (0, 'missing'))
        for uid in range(6, 11):
            with self.authenticated(uid):
                for action in (self.service.current, self.service.history,
                        lambda: self.service.propose(0, policy_document())):
                    with self.subTest(uid=uid), self.assertRaises(PolicyAccessDenied): action()
        self.assertEqual(self.totals(), (0, 0, 0))

    def test_complete_linear_lifecycle_and_immutable_audit(self):
        proposed = self.propose()
        self.assertEqual((proposed.head_version, proposed.status), (1, 'Proposed'))
        self.assertEqual(self.read().state, 'missing')
        approved = self.decide('approve', 1)
        self.assertEqual((approved.status, self.read().state), ('Approved', 'missing'))
        activated = self.decide('activate', 2)
        current = self.read()
        self.assertEqual((current.head_version, current.state, current.policy.content_digest), (3, 'active', proposed.digest))
        self.decide('deactivate', 3)
        self.assertEqual((self.read().state, self.read().policy), ('deactivated', None))
        with self.authenticated(3):
            entry = self.service.history().entries[0]
            self.assertEqual([e[1] for e in entry.events], ['Approved', 'Activated', 'Deactivated'])
            self.assertEqual(entry.events[1][-1], approved.event_id)
            self.assertEqual(entry.events[2][-1], activated.event_id)
            self.assertEqual((entry.proposer_id, entry.proposer_authority_revision), (1, 1))
            self.assertTrue(all(e[2:4] == (2, 1) and e[5].tzinfo is not None for e in entry.events))
        self.assertEqual(self.totals(), (1, 3, 1))

    def test_rejection_is_terminal_and_does_not_activate(self):
        self.propose(); self.decide('reject', 1)
        for action in ('approve', 'reject', 'activate', 'deactivate'):
            with self.subTest(action=action), self.assertRaises(PolicyConflict): self.decide(action, 2)
        self.assertEqual((self.read().state, self.totals()), ('missing', (1, 1, 1)))

    def test_self_approval_and_wrong_capabilities_are_denied(self):
        proposed = self.propose()
        with self.database.transaction() as session: session.add(authority_row(1, 'approve'))
        with self.authenticated(1), self.assertRaises(PolicyConflict):
            self.service.approve(1, 1, proposed.digest, 'Cannot self approve')
        with self.authenticated(3), self.assertRaises(PolicyAccessDenied):
            self.service.approve(1, 1, proposed.digest, 'Audit is not approval')
        with self.authenticated(2), self.assertRaises(PolicyAccessDenied): self.service.current()
        self.assertEqual(self.totals(), (1, 0, 1))

    def test_duplicate_and_out_of_order_decisions_are_rejected(self):
        self.propose()
        for action in ('activate', 'deactivate'):
            with self.assertRaises(PolicyConflict): self.decide(action, 1)
        self.decide('approve', 1)
        for action in ('approve', 'reject', 'deactivate'):
            with self.assertRaises(PolicyConflict): self.decide(action, 2)
        self.decide('activate', 2)
        with self.assertRaises(PolicyConflict): self.decide('activate', 3)
        self.decide('deactivate', 3)
        with self.assertRaises(PolicyConflict): self.decide('activate', 4)

    def test_activation_requires_effective_interval_and_does_not_fall_back(self):
        start, end = NOW + timedelta(days=1), NOW + timedelta(days=2)
        value = policy_document(effective={'from': start.isoformat(), 'until': end.isoformat()})
        with self.authenticated(): proposed = self.service.propose(0, value)
        self.decide('approve', 1, digest=proposed.digest)
        with self.assertRaises(PolicyConflict): self.decide('activate', 2, digest=proposed.digest)
        with mock.patch.object(self.service, '_now', return_value=start): self.decide('activate', 2, digest=proposed.digest)
        with mock.patch.object(self.service, '_now', return_value=end):
            current = self.read(); self.assertEqual((current.state, current.policy), ('expired', None))
            self.decide('deactivate', 3, digest=proposed.digest)
        self.assertEqual(self.read().state, 'deactivated')

    def test_replacement_requires_explicit_deactivation_and_new_revision(self):
        self.active(); self.propose(3, 2); self.decide('approve', 4, 2)
        with self.assertRaises(PolicyConflict): self.decide('activate', 5, 2)
        self.decide('deactivate', 5)
        self.assertEqual(self.read().state, 'deactivated')
        self.decide('activate', 6, 2)
        self.assertEqual(self.read().policy.revision, 2)

    def test_stale_head_digest_revision_and_inputs_never_commit(self):
        proposed = self.propose()
        for head, rev, digest in ((0, 1, proposed.digest), (1, 2, proposed.digest), (1, 1, '0'*64)):
            with self.assertRaises(PolicyConflict): self.decide('approve', head, rev, digest)
        with self.authenticated():
            for bad in (True, -1, 1.0, MAX_REVISION+1):
                with self.assertRaises(PreferenceError): self.service.propose(bad, policy_document(revision=2))
        with self.authenticated(2):
            for reason in ('', ' ', '\0', 'x'*2001, None):
                with self.assertRaises(PreferenceError): self.service.approve(1, 1, proposed.digest, reason)
        self.assertEqual(self.totals(), (1, 0, 1))

    def test_invalid_policy_contract_provenance_and_coefficients_are_rejected(self):
        with self.authenticated():
            for changes in ({'timezone': 'UTC'}, {'origin': 'synthetic'}, {'objective_version': 2},
                    {'coefficients': {}}, {'effective': {'from': '2031-01-01T00:00Z', 'until': '2030-01-01T00:00Z'}}):
                with self.assertRaises(PreferenceError): self.service.propose(0, policy_document(**changes))
            with self.assertRaises(PolicyConflict): self.service.propose(0, policy_document(revision=2))
        self.assertEqual(self.totals(), (0, 0, 0))

    def test_latest_applicable_revocation_or_expiry_never_falls_back(self):
        with self.database.transaction() as session:
            row = authority_row(1, revision=2); row.decision = 'Revoked'; session.add(row)
            future = authority_row(1, revision=3); future.effective_from = NOW + timedelta(days=1); session.add(future)
        with self.assertRaises(PolicyAccessDenied): self.propose()
        with mock.patch.object(self.service, '_now', return_value=NOW + timedelta(days=2)): self.propose()
        with mock.patch.object(self.service, '_now', return_value=datetime(2031, 1, 1, tzinfo=timezone.utc)), \
                self.assertRaises(PolicyAccessDenied): self.propose(1, 2)

    def test_future_authority_does_not_take_effect_early(self):
        with self.database.transaction() as session:
            row = authority_row(1, revision=2); row.decision = 'Revoked'
            row.effective_from = NOW + timedelta(days=1); session.add(row)
        self.propose()
        with mock.patch.object(self.service, '_now', return_value=NOW + timedelta(days=1)), \
                self.assertRaises(PolicyAccessDenied): self.propose(1, 2)

    def test_forged_principals_cookie_types_and_anonymous_context_are_denied(self):
        with self.assertRaises(PolicyAccessDenied): self.service.current()
        with self.authenticated():
            real = g.principal
            for fake in (None, {'user_id': 1}, replace(real, administrator=True), replace(real, user_id=2),
                    replace(real, user_id=True), replace(real, session_version=True)):
                g.principal = fake
                with self.assertRaises(PolicyAccessDenied): self.service.propose(0, policy_document())
            g.principal = real
            for uid, version in ((True, 1), (1, True), (2, 1), (1, '1'), (1, 2)):
                login_session['user_id'], login_session['session_version'] = uid, version
                with self.assertRaises(PolicyAccessDenied): self.service.propose(0, policy_document())
        self.assertEqual(self.totals(), (0, 0, 0))

    def test_disabled_users_accounts_and_stale_sessions_are_denied(self):
        for kind in ('user', 'account', 'session'):
            with self.authenticated():
                with self.database.transaction() as session:
                    if kind == 'user': session.get(User, 1).status = 'inactive'
                    elif kind == 'account': session.get(LoginAccount, 1).enabled = False
                    else: session.get(LoginAccount, 1).session_version += 1
                with self.assertRaises(PolicyAccessDenied): self.service.propose(0, policy_document())
            with self.database.transaction() as session:
                session.get(User, 1).status = 'active'; account = session.get(LoginAccount, 1)
                account.enabled, account.session_version = True, 1
        self.assertEqual(self.totals(), (0, 0, 0))

    def test_cross_database_schema_and_misbound_sessions_are_denied(self):
        for url in (self.database.url.set(database='unrelated-fictional-database'),
                    self.database.url.set(query={'options': '-csearch_path=unrelated_schema'})):
            other = Database(url); self.addCleanup(other.dispose)
            with self.authenticated(), mock.patch.object(other, 'transaction', side_effect=AssertionError('Must not connect')):
                with self.assertRaises(PolicyAccessDenied): CostPolicyService(other, university_timezone='Europe/Istanbul').current()
        with self.authenticated(3):
            g.authenticated_database_url = str(self.database.url)
            with self.assertRaises(PolicyAccessDenied): self.service.history()

    def test_dirty_session_is_denied_without_autoflush(self):
        with self.database.sessions() as dirty, self.authenticated():
            dirty.get(User, 1).name = 'PRIVATE-MARKER'
            @contextmanager
            def injected(**kwargs): yield dirty
            with mock.patch.object(self.database, 'transaction', injected), self.assertRaises(PolicyAccessDenied):
                self.service.propose(0, policy_document())
            dirty.rollback()
        with self.database.transaction(read_only=True) as session: self.assertNotIn('PRIVATE', session.get(User, 1).name)

    def test_history_is_bounded_private_and_never_synthetic(self):
        for revision in range(1, 4): self.propose(revision-1, revision)
        with self.authenticated(3):
            page = self.service.history(limit=2)
            self.assertEqual([e.policy.revision for e in page.entries], [3, 2])
            self.assertEqual(page.next_before_revision, 2)
            self.assertEqual([e.policy.revision for e in self.service.history(before_revision=2).entries], [1])
            self.assertNotIn('Fictional', repr(page))
            with self.assertRaises(PreferenceError): synthetic_policy(page.entries[0].policy.document())
            for bad in (0, 101, True, 1.0):
                with self.assertRaises(PreferenceError): self.service.history(limit=bad)

    def test_readonly_snapshots_and_no_booking_calendar_notification_effects(self):
        self.active()
        original = self.service._active
        def inspect_read(session, head):
            self.assertEqual(session.scalar(text('SHOW transaction_read_only')), 'on')
            self.assertEqual(session.scalar(text('SHOW transaction_isolation')), 'repeatable read')
            self.assertFalse(session.autoflush)
            return original(session, head)
        with self.authenticated(3), mock.patch.object(self.service, '_active', side_effect=inspect_read):
            self.service.current(); self.service.history()
        with self.database.transaction(read_only=True) as session:
            for table in ('appointment', 'room_reservation', 'notification', 'scheduling_preference_revision'):
                self.assertEqual(session.scalar(text('SELECT count(*) FROM '+table)), 0)
            self.assertEqual(session.scalar(text('SELECT calendar_revision FROM application_state')), 0)
        from web import app as application
        self.assertFalse(any('cost_policy' in str(rule) or 'cost-policy' in str(rule) for rule in application.app.url_map.iter_rules()))

    def test_corrupt_digest_and_stale_active_pointer_fail_closed(self):
        self.active()
        with self.database.transaction() as session:
            session.execute(text('ALTER TABLE scheduling_cost_policy_revision DISABLE TRIGGER cost_revision_immutable'))
            session.execute(update(Revision).values(content_digest='0'*64))
            session.execute(text('ALTER TABLE scheduling_cost_policy_revision ENABLE TRIGGER cost_revision_immutable'))
        self.assertEqual((self.read().state, self.read().policy), ('unknown', None))
        with self.authenticated(3), self.assertRaises(PreferenceError): self.service.history()

    def test_stale_pointer_cannot_reactivate_a_deactivated_revision(self):
        self.active(); self.decide('deactivate', 3)
        with self.database.transaction() as session:
            active = session.scalar(select(Event.id).where(Event.event_type == 'Activated'))
            head = session.get(Head, 1); head.version, head.active_event_id = 5, active
        self.assertEqual((self.read().state, self.read().policy), ('unknown', None))
        with self.assertRaises(PolicyStorageError): self.propose(5, 2)

    def test_storage_errors_are_sanitized_and_commit_failure_rolls_back(self):
        def broken_commit(connection): raise OperationalError('PRIVATE SQL', {'password': 'PRIVATE-MARKER'}, RuntimeError('PRIVATE-MARKER'))
        with self.authenticated(), mock.patch.object(self.database, 'transaction', side_effect=OperationalError(
                'PRIVATE SQL', {'password': 'PRIVATE-MARKER'}, RuntimeError('PRIVATE-MARKER'))):
            with self.assertRaises(PolicyStorageError) as raised: self.service.propose(0, policy_document())
            self.assertNotIn('PRIVATE', str(raised.exception)); self.assertTrue(raised.exception.__suppress_context__)
        with self.authenticated():
            event.listen(self.database.engine, 'commit', broken_commit)
            try:
                with self.assertRaises(PolicyStorageError): self.service.propose(0, policy_document())
            finally: event.remove(self.database.engine, 'commit', broken_commit)
        self.assertEqual(self.totals(), (0, 0, 0))

    def test_revision_overflow_fails_before_any_decision(self):
        with self.database.transaction() as session: session.add(Head(id=1, version=MAX_REVISION))
        with self.assertRaises(PolicyConflict): self.propose(MAX_REVISION)
        self.assertEqual(self.totals(), (0, 0, 1))

    def test_expiry_while_transaction_is_open_rolls_back(self):
        self.service._now = mock.Mock(side_effect=[NOW, datetime(2031, 1, 1, tzinfo=timezone.utc)])
        with self.assertRaises(PolicyAccessDenied): self.propose()
        self.assertEqual(self.totals(), (0, 0, 0))

    def test_competing_first_proposals_have_one_winner(self):
        barrier = threading.Barrier(2)
        def attempt(_):
            with self.authenticated():
                barrier.wait(timeout=10)
                try: self.service.propose(0, policy_document()); return 'accepted'
                except PolicyConflict: return 'stale'
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(attempt, range(2))), ['accepted', 'stale'])
        self.assertEqual(self.totals(), (1, 0, 1))

    def test_competing_approval_and_rejection_have_one_atomic_winner(self):
        proposed = self.propose(); barrier = threading.Barrier(2)
        def attempt(kind):
            with self.authenticated(2):
                barrier.wait(timeout=10)
                try: getattr(self.service, kind)(1, 1, proposed.digest, 'Fictional competing decision'); return 'accepted'
                except PolicyConflict: return 'stale'
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(attempt, ('approve', 'reject'))), ['accepted', 'stale'])
        self.assertEqual(self.totals(), (1, 1, 1))

    def test_late_event_failure_rolls_back_head_and_event(self):
        self.propose()
        original = self.service._authority
        calls = []
        def deny_late(*args):
            result = original(*args); calls.append(True)
            if len(calls) == 2: raise PolicyAccessDenied()
            return result
        with mock.patch.object(self.service, '_authority', side_effect=deny_late), self.assertRaises(PolicyAccessDenied):
            self.decide('approve', 1)
        self.assertEqual(self.totals(), (1, 0, 1))
        self.decide('approve', 1)

    def test_read_context_is_consistent_during_concurrent_deactivation(self):
        self.active(); read, release = threading.Event(), threading.Event()
        original = self.service._active
        def pause(session, head):
            read.set()
            if not release.wait(10): raise AssertionError('Missing release')
            return original(session, head)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with mock.patch.object(self.service, '_active', side_effect=pause):
                reader = pool.submit(self.read); self.assertTrue(read.wait(10))
                # A separate service instance avoids pausing the writer.
                writer = CostPolicyService(self.database, university_timezone='Europe/Istanbul')
                try:
                    with self.authenticated(2): writer.deactivate(3, 1, parse(policy_document()).content_digest, 'Explicit test release')
                finally: release.set()
                self.assertEqual(reader.result(timeout=10).state, 'active')
        self.assertEqual(self.read().state, 'deactivated')

    def test_raw_revocation_committed_before_publication_is_observed(self):
        held, attempted, release = threading.Event(), threading.Event(), threading.Event()
        other = Database(self.database.url); self.addCleanup(other.dispose)
        def revoke():
            with other.transaction() as session:
                row = authority_row(1, revision=2); row.decision = 'Revoked'; session.add(row)
                session.flush(); held.set()
                if not release.wait(10): raise AssertionError('Missing release')
        def capture(_, __, statement, *args):
            if statement.startswith('LOCK TABLE scheduling_cost_policy_authority_revision'): attempted.set()
        event.listen(self.database.engine, 'before_cursor_execute', capture)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                revoker = pool.submit(revoke); self.assertTrue(held.wait(10))
                writer = pool.submit(self.propose); self.assertTrue(attempted.wait(10))
                try: self.assertFalse(writer.done())
                finally: release.set()
                revoker.result(timeout=10)
                with self.assertRaises(PolicyAccessDenied): writer.result(timeout=10)
        finally: event.remove(self.database.engine, 'before_cursor_execute', capture)
        self.assertEqual(self.totals(), (0, 0, 0))

    def test_inflight_publication_blocks_raw_revocation_and_later_transaction_is_denied(self):
        held, attempted, release = threading.Event(), threading.Event(), threading.Event()
        other = Database(self.database.url); self.addCleanup(other.dispose)
        original = self.service._authority
        first = []
        def pause(*args):
            result = original(*args)
            if not first:
                first.append(True); held.set()
                if not release.wait(10): raise AssertionError('Missing release')
            return result
        def capture(_, __, statement, *args):
            if statement.startswith('INSERT INTO scheduling_cost_policy_authority_revision'): attempted.set()
        def revoke():
            with other.transaction() as session:
                row = authority_row(1, revision=2); row.decision = 'Revoked'; session.add(row)
        event.listen(other.engine, 'before_cursor_execute', capture)
        try:
            with mock.patch.object(self.service, '_authority', side_effect=pause), ThreadPoolExecutor(max_workers=2) as pool:
                writer = pool.submit(self.propose); self.assertTrue(held.wait(10))
                revoker = pool.submit(revoke); self.assertTrue(attempted.wait(10))
                try: self.assertFalse(revoker.done())
                finally: release.set()
                self.assertEqual(writer.result(timeout=10).status, 'Proposed'); revoker.result(timeout=10)
        finally: event.remove(other.engine, 'before_cursor_execute', capture)
        with self.assertRaises(PolicyAccessDenied): self.propose(1, 2)
        self.assertEqual(self.totals(), (1, 0, 1))

    def test_head_and_account_lock_timeouts_save_no_partial_state(self):
        short = Database(self.database.url, lock_timeout=.1); self.addCleanup(short.dispose)
        service = CostPolicyService(short, university_timezone='Europe/Istanbul')
        with self.database.transaction() as session: session.add(Head(id=1, version=0))
        for model in (Head, LoginAccount):
            with self.subTest(model=model.__name__), self.database.transaction() as blocker, self.authenticated():
                blocker.get(model, 1, with_for_update=True)
                with self.assertRaises(PolicyStorageError) as raised: service.propose(0, policy_document())
                self.assertNotIn('login_account', str(raised.exception))
                self.assertIsNone(raised.exception.__cause__)
        self.assertEqual(self.totals(), (0, 0, 1))

    def test_real_deadlock_rolls_back_the_whole_operation(self):
        with self.database.transaction() as session: session.add(Head(id=1, version=0))
        locked, attempted = threading.Event(), threading.Event()
        other = Database(self.database.url); self.addCleanup(other.dispose)
        transaction = self.database.transaction
        @contextmanager
        def short_deadlock(**kwargs):
            with transaction(**kwargs) as session:
                session.execute(text("SET LOCAL deadlock_timeout='100ms'")); yield session
        def capture(_, __, statement, *args):
            if 'login_account' in statement and 'FOR UPDATE' in statement: attempted.set()
        def blocker():
            with other.transaction() as session:
                session.execute(text("SET LOCAL deadlock_timeout='5s'"))
                session.get(LoginAccount, 1, with_for_update=True); locked.set()
                if not attempted.wait(10): raise AssertionError('Missing account lock attempt')
                session.get(Head, 1, with_for_update=True)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(blocker); self.assertTrue(locked.wait(10))
            event.listen(self.database.engine, 'before_cursor_execute', capture)
            try:
                with mock.patch.object(self.database, 'transaction', short_deadlock), self.assertRaises(PolicyStorageError):
                    self.propose()
            finally: event.remove(self.database.engine, 'before_cursor_execute', capture)
            pending.result(timeout=10)
        self.assertEqual(self.totals(), (0, 0, 1))

    def test_duplicate_approvals_from_two_transactions_commit_once(self):
        proposed = self.propose(); barrier = threading.Barrier(2)
        def attempt(_):
            with self.authenticated(2):
                barrier.wait(timeout=10)
                try: self.service.approve(1, 1, proposed.digest, 'Fictional duplicate'); return 'accepted'
                except PolicyConflict: return 'stale'
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(attempt, range(2))), ['accepted', 'stale'])
        self.assertEqual(self.totals(), (1, 1, 1))

    def test_competing_activation_and_deactivation_cannot_implicitly_replace(self):
        self.active(); second = self.propose(3, 2); self.decide('approve', 4, 2)
        barrier = threading.Barrier(2)
        def attempt(kind):
            with self.authenticated(2):
                barrier.wait(timeout=10)
                try:
                    if kind == 'activate': self.service.activate(5, 2, second.digest, 'Fictional replace attempt')
                    else: self.service.deactivate(5, 1, parse(policy_document()).content_digest, 'Explicit release')
                    return kind + '-accepted'
                except PolicyConflict: return kind + '-blocked'
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(attempt, ('activate', 'deactivate'))), ['activate-blocked', 'deactivate-accepted'])
        self.assertEqual(self.read().state, 'deactivated')
        self.decide('activate', 6, 2); self.assertEqual(self.read().policy.revision, 2)

    def test_expiring_activation_during_transaction_rolls_back_event_and_pointer(self):
        value = policy_document(effective={'from': NOW.isoformat(), 'until': (NOW+timedelta(seconds=1)).isoformat()})
        with self.authenticated(): proposed = self.service.propose(0, value)
        self.decide('approve', 1, digest=proposed.digest)
        with mock.patch.object(self.service, '_now', side_effect=[NOW, NOW+timedelta(seconds=1)]), \
                self.assertRaises(PolicyConflict): self.decide('activate', 2, digest=proposed.digest)
        self.assertEqual((self.read().state, self.totals()), ('missing', (1, 1, 1)))

    def test_policy_revision_overflow_does_not_create_a_new_revision(self):
        with self.database.transaction() as session:
            session.add(Head(id=1, version=0)); session.add(policy_row(policy_document(revision=MAX_REVISION)))
        with self.assertRaises(PolicyConflict): self.propose(0, MAX_REVISION)
        self.assertEqual(self.totals(), (1, 0, 1))

    def test_blank_authority_provenance_is_not_trusted(self):
        with self.database.transaction() as session:
            row = authority_row(1, revision=2); row.authorization_ref = '\n'; session.add(row)
        with self.assertRaises(PolicyAccessDenied): self.propose()
        self.assertEqual(self.totals(), (0, 0, 0))

    def test_temporary_authority_table_cannot_grant_a_capability(self):
        with self.database.engine.begin() as connection:
            connection.execute(text('CREATE TEMP TABLE scheduling_cost_policy_authority_revision '
                '(LIKE "'+self.schema+'".scheduling_cost_policy_authority_revision INCLUDING ALL)'))
            connection.execute(text('INSERT INTO pg_temp.scheduling_cost_policy_authority_revision '
                '(user_id,capability,revision,decision,actor_id,effective_from,effective_until,reason,authorization_ref) '
                'SELECT 6,capability,revision,decision,actor_id,effective_from,effective_until,reason,authorization_ref '
                'FROM "'+self.schema+'".scheduling_cost_policy_authority_revision WHERE user_id=1'))
        with self.authenticated(6), self.assertRaises(PolicyAccessDenied): self.service.propose(0, policy_document())

    def test_governance_never_reads_private_preferences_or_calendar_tables(self):
        statements = []
        def capture(_, __, statement, *args): statements.append(statement.lower())
        event.listen(self.database.engine, 'before_cursor_execute', capture)
        try: self.active(); self.read()
        finally: event.remove(self.database.engine, 'before_cursor_execute', capture)
        for name in ('scheduling_preference_revision', 'appointment', 'calendar_block', 'notification', 'room_reservation'):
            self.assertFalse(any(name in sql for sql in statements), name)

    def test_same_database_new_pool_is_allowed_but_identical_foreign_schema_is_not(self):
        same = Database(self.database.url); self.addCleanup(same.dispose)
        with self.authenticated(3):
            self.assertEqual(CostPolicyService(same, university_timezone='Europe/Istanbul').current().state, 'missing')
        other = CostPolicyGovernanceTests('test_missing_head_read_does_not_initialize_and_roles_grant_nothing')
        try:
            other.setUp(); other.active()
            with self.authenticated(3):
                with self.assertRaises(PolicyAccessDenied): other.service.current()
                with self.assertRaises(PolicyAccessDenied): other.service.history()
        finally: other.doCleanups()

    def test_unsupported_current_policy_is_not_returned_or_replaced_by_older_values(self):
        self.active()
        with mock.patch.object(self.service, '_policy', side_effect=PreferenceUnavailable('UNSUPPORTED_VERSION')):
            self.assertEqual((self.read().state, self.read().policy), ('unsupported', None))

    def test_readonly_database_rejects_injected_core_writes(self):
        self.active()
        def mutate(session, head):
            session.execute(update(Head).values(version=Head.version + 1))
            raise AssertionError('Read-only database should reject DML')
        with self.authenticated(3), mock.patch.object(self.service, '_active', side_effect=mutate), \
                self.assertRaises(PolicyStorageError): self.service.current()
        self.assertEqual((self.read().head_version, self.read().state), (3, 'active'))

    def test_contradictory_manual_event_history_cannot_authorize_a_transition(self):
        self.propose(); self.decide('approve', 1)
        with self.database.transaction() as session:
            session.add(Event(policy_id='university', policy_revision=1, event_type='Rejected', actor_id=2,
                actor_capability='approve', authority_revision=1, head_version=3, reason='Isolated structural corruption'))
            session.get(Head, 1).version = 3
        with self.assertRaises(PolicyStorageError): self.decide('activate', 3)
        with self.authenticated(3), self.assertRaises(PolicyStorageError): self.service.history()

    def test_privileged_methods_have_no_caller_supplied_actor_override(self):
        with self.authenticated():
            with self.assertRaises(TypeError): self.service.propose(0, policy_document(), actor_id=2)
        with self.authenticated(3):
            with self.assertRaises(TypeError): self.service.current(actor_id=2)
            with self.assertRaises(TypeError): self.service.history(owner_id=1)
        self.assertEqual(self.totals(), (0, 0, 0))
