"""Schema-only policy fixtures in owned PostgreSQL schemas; no governance API."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
import threading
from unittest import mock

from alembic import command
from alembic.config import Config
from alembic.operations import Operations
from sqlalchemy import delete, func, inspect, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError, IntegrityError

from postgres_fixtures import PostgresTestCase, ROOT
from test_cost_policy_values import parse, policy_document
from web.persistence.models import (Role, User, SchedulingCostPolicyAuthorityRevision as Authority,
    SchedulingCostPolicyRevision as Revision, SchedulingCostPolicyEvent as Event,
    SchedulingCostPolicyHead as Head)


TABLES = (Authority.__tablename__, Revision.__tablename__, Event.__tablename__, Head.__tablename__)


def authority_row(uid=1, capability='propose', revision=1, **changes):
    return Authority(user_id=uid, capability=capability, revision=revision, decision='Granted', actor_id=1,
        effective_from=datetime(2030, 1, 1, tzinfo=timezone.utc), effective_until=datetime(2031, 1, 1, tzinfo=timezone.utc),
        reason='Explicit isolated fixture only', authorization_ref='fictional-institution-decision', **changes)


def policy_row(document=None, proposer=1):
    value = parse(document or policy_document())
    return Revision(policy_id='university', revision=value.revision, contract_version=1, objective_version=1,
        engine_operation='cdmcs_schedule_v1', objective_model='V15_restricted_one_blocking_move',
        rate_model='weekday_window_tiers_v1', timezone=value.timezone, effective_from=value.effective_from,
        effective_until=value.effective_until, cost_unit=value.cost_unit, calibration_ref=value.calibration_ref,
        provenance_type='institutional_policy', provenance_ref=value.provenance_ref, content_digest=value.content_digest,
        proposer_id=proposer, proposer_capability='propose', proposer_authority_revision=1,
        **value.coefficients.document())


class PolicyDatabaseTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        with self.database.transaction() as session:
            session.add(Role(id=1, name='Administrator')); session.flush()
            for uid in (1, 2):
                session.add(User(id=uid, source_order=uid, name=f'Fictional policy actor {uid}', primary_role_id=1))

    def fixture(self):
        with self.database.transaction() as session:
            session.add_all([authority_row(), authority_row(2, 'approve')]); session.flush()
            session.add(policy_row())

    def decision(self, kind='Approved', version=1, previous=None, actor=2, policy_revision=1):
        row = Event(policy_id='university', policy_revision=policy_revision, event_type=kind,
            actor_id=actor, actor_capability='approve', authority_revision=1, head_version=version,
            preceding_event_id=previous, reason='Isolated schema association witness')
        with self.database.transaction() as session:
            session.add(row); session.flush(); return row.id

    def totals(self):
        with self.database.transaction(read_only=True) as session:
            return tuple(session.scalar(text('SELECT count(*) FROM ' + name)) for name in TABLES)

    def test_empty_foundation_seeds_no_policy_authority_head_or_permissions(self):
        self.assertEqual(self.totals(), (0, 0, 0, 0))
        from web import app as web_app
        self.assertFalse(any('cost-policy' in str(rule) or 'cost_policy' in str(rule) for rule in web_app.app.url_map.iter_rules()))

    def test_exact_roundtrip_digest_and_server_timestamp(self):
        self.fixture()
        with self.database.transaction(read_only=True) as session:
            row = session.get(Revision, ('university', 1))
            self.assertEqual(row.content_digest, parse(policy_document()).content_digest)
            self.assertEqual(row.effective_from, parse(policy_document()).effective_from)
            self.assertIsNotNone(row.created_at.tzinfo)
            self.assertNotEqual(row.created_at.year, 2030)
        self.assertEqual(self.totals(), (2, 1, 0, 0))

    def test_every_coefficient_bound_is_enforced_by_postgresql(self):
        self.fixture()
        maximum = dict(zip(parse(policy_document()).coefficients.document(),
            (10**8, 10**8, 10**8, 100000, 10080, 10**7, 10**7, 10**7, 10**7)))
        with self.database.transaction() as session:
            session.add(policy_row(policy_document(revision=2, coefficients=maximum)))
        for index, (key, upper) in enumerate(maximum.items(), 3):
            for bad in (-1, upper + 1, None, 2**63):
                document = policy_document(revision=index, coefficients=maximum)
                row = policy_row(document); setattr(row, key, bad)
                # Give deliberately invalid SQL input its matching digest, so this
                # witnesses the numeric constraint, not just digest rejection.
                items = json.loads(parse(document).canonical_bytes())
                items[15 + list(maximum).index(key)] = bad
                row.content_digest = hashlib.sha256(json.dumps(items, ensure_ascii=False,
                    separators=(', ', ': ')).encode('utf-8')).hexdigest()
                with self.subTest(key=key, value=bad), self.assertRaises(DBAPIError) as raised:
                    with self.database.transaction() as session: session.add(row)
                if bad is not None and bad != 2**63:
                    expected = 'rates' if key in list(maximum)[:3] else 'gap' if key in list(maximum)[3:5] else 'fees'
                    self.assertEqual(raised.exception.orig.diag.constraint_name, 'ck_cost_policy_' + expected)
        self.assertEqual(self.totals(), (2, 2, 0, 0))

    def test_bad_provenance_model_interval_timezone_digest_and_missing_grant_fail(self):
        self.fixture()
        changes = {'contract_version': 2, 'objective_version': 2, 'policy_id': 'faculty', 'revision': 0,
            'provenance_type': 'synthetic', 'timezone': 'Mars/Invalid', 'engine_operation': 'unsupported',
            'objective_model': 'minimax', 'rate_model': 'additive', 'cost_unit': ' ', 'calibration_ref': '',
            'provenance_ref': 'secret\nvalue', 'content_digest': '0' * 64,
            'effective_until': datetime(2029, 1, 1, tzinfo=timezone.utc), 'proposer_authority_revision': 999}
        for key, bad in changes.items():
            row = policy_row(policy_document(revision=2)); setattr(row, key, bad)
            with self.subTest(key=key), self.assertRaises(DBAPIError), self.database.transaction() as session:
                session.add(row)

    def test_canonical_digest_matches_postgresql_unicode_offsets_microseconds_and_max_revision(self):
        self.fixture()
        values = [policy_document(revision=2, cost_unit='Fictional \u00fcniversity "points" \\ \U0001f4da'),
            policy_document(revision=3, effective={'from': '2030-01-01T03:00:00.123456+03:00', 'until': '2031-01-01T03:00:00.654321+03:00'}),
            policy_document(revision=2**63 - 1)]
        for value in values:
            with self.database.transaction() as session: session.add(policy_row(value))
        self.assertEqual(self.totals(), (2, 4, 0, 0))

    def test_history_updates_deletes_and_truncation_are_blocked(self):
        self.fixture(); self.decision()
        for model in (Authority, Revision, Event):
            for statement in (delete(model), update(model).values(created_at=datetime(2030, 1, 1, tzinfo=timezone.utc)),
                              text('TRUNCATE ' + model.__tablename__ + ' CASCADE')):
                with self.subTest(table=model.__tablename__), self.assertRaises(IntegrityError), self.database.transaction() as session:
                    session.execute(statement)
        self.assertEqual(self.totals(), (2, 1, 1, 0))

    def test_digest_text_domain_matches_python_without_unicode_normalization(self):
        self.fixture()
        for revision, unit in enumerate(('Fictional \u0085 unit', 'Fictional \u009f unit',
                'Fictional \u00e9', 'Fictional e\u0301', 'Fictional \u2028 unit'), 2):
            with self.subTest(revision=revision), self.database.transaction() as session:
                session.add(policy_row(policy_document(revision=revision, cost_unit=unit)))
        for char in ('\x01', '\x1f', '\x7f'):
            row = policy_row(policy_document(revision=7)); row.cost_unit = 'Fictional ' + char
            items = json.loads(parse(policy_document(revision=7)).canonical_bytes()); items[11] = row.cost_unit
            row.content_digest = hashlib.sha256(json.dumps(items, ensure_ascii=False,
                separators=(', ', ': ')).encode('utf-8')).hexdigest()
            with self.subTest(control=ord(char)), self.assertRaises(IntegrityError), self.database.transaction() as session:
                session.add(row)

    def test_proposal_and_approval_do_not_publish_or_change_any_other_service(self):
        self.fixture(); self.decision()
        with self.database.transaction(read_only=True) as session:
            self.assertIsNone(session.get(Head, 1))
            for name in ('scheduling_preference_revision', 'appointment', 'room_reservation', 'notification'):
                self.assertEqual(session.scalar(text('SELECT count(*) FROM ' + name)), 0)
            self.assertEqual(session.scalar(text('SELECT calendar_revision FROM application_state')), 0)

    def test_separate_approver_and_valid_grant_reference_are_required(self):
        self.fixture()
        with self.database.transaction() as session: session.add(authority_row(1, 'approve'))
        with self.assertRaises(IntegrityError): self.decision(actor=1)
        with self.database.transaction() as session:
            revoked = authority_row(2, 'audit'); revoked.decision = 'Revoked'; session.add(revoked)
        row = policy_row(policy_document(revision=2)); row.proposer_id = 999
        with self.assertRaises(DBAPIError), self.database.transaction() as session: session.add(row)
        with self.assertRaises(DBAPIError): self.decision(policy_revision=999)

    def test_explicit_activation_event_associations_and_single_head(self):
        self.fixture(); approved = self.decision()
        with self.assertRaises(IntegrityError), self.database.transaction() as session:
            session.add(Head(id=1, version=1, active_event_id=approved))
        activated = self.decision('Activated', 2, approved)
        with self.database.transaction() as session: session.add(Head(id=1, version=2, active_event_id=activated))
        with self.assertRaises(IntegrityError), self.database.transaction() as session: session.add(Head(id=2, version=2))
        with self.assertRaises(IntegrityError), self.database.transaction() as session:
            session.execute(update(Head).values(version=2))
        self.decision('Deactivated', 3, activated)
        with self.database.transaction() as session:
            session.execute(update(Head).values(version=3, active_event_id=None))
        with self.database.transaction(read_only=True) as session:
            self.assertIsNone(session.get(Head, 1).active_event_id)
            self.assertEqual(session.scalar(select(func.count()).select_from(Event)), 3)

    def test_wrong_predecessor_target_and_revocation_reference_fail(self):
        self.fixture(); approved = self.decision()
        with self.assertRaises(IntegrityError): self.decision('Deactivated', 2, approved)
        with self.database.transaction() as session: session.add(policy_row(policy_document(revision=2)))
        with self.assertRaises(IntegrityError): self.decision('Activated', 2, approved, policy_revision=2)
        with self.assertRaises(IntegrityError): self.decision('Activated', 2, None)
        with self.database.transaction() as session:
            row = authority_row(2, 'approve', revision=2); row.decision = 'Revoked'; session.add(row)
        event = Event(policy_id='university', policy_revision=1, event_type='Rejected', actor_id=2,
            actor_capability='approve', authority_revision=2, head_version=2, reason='fixture')
        with self.assertRaises(IntegrityError), self.database.transaction() as session: session.add(event)

    def test_rollback_is_atomic_and_explicit_zero_head_is_inactive(self):
        with self.assertRaises(RuntimeError), self.database.transaction() as session:
            session.add(authority_row()); session.flush(); session.add(policy_row()); session.flush()
            raise RuntimeError('fictional rollback')
        self.assertEqual(self.totals(), (0, 0, 0, 0))
        with self.database.transaction() as session: session.add(Head(id=1, version=0))
        with self.database.transaction(read_only=True) as session: self.assertIsNone(session.get(Head, 1).active_event_id)

    def test_simultaneous_expected_head_updates_have_one_winner(self):
        with self.database.transaction() as session: session.add(Head(id=1, version=0))
        barrier = threading.Barrier(2)
        def attempt():
            barrier.wait(timeout=10)
            with self.database.transaction() as session:
                return session.execute(update(Head).where(Head.version == 0).values(version=1)).rowcount
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(lambda _: attempt(), range(2))), [0, 1])

    def test_first_head_initialization_can_serialize_competing_expected_versions(self):
        barrier = threading.Barrier(2)
        def attempt():
            barrier.wait(timeout=10)
            with self.database.transaction() as session:
                session.execute(insert(Head).values(id=1, version=0).on_conflict_do_nothing(index_elements=['id']))
                head = session.scalar(select(Head).where(Head.id == 1).with_for_update())
                if head.version != 0: return 'stale'
                head.version = 1
                return 'accepted'
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(lambda _: attempt(), range(2))), ['accepted', 'stale'])
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.get(Head, 1).version, 1)
            self.assertIsNone(session.get(Head, 1).active_event_id)

    def test_competing_same_revision_proposals_cannot_overwrite_history(self):
        with self.database.transaction() as session: session.add(authority_row())
        barrier = threading.Barrier(2)
        def attempt():
            barrier.wait(timeout=10)
            try:
                with self.database.transaction() as session: session.add(policy_row())
                return 'inserted'
            except IntegrityError as error:
                self.assertEqual(error.orig.sqlstate, '23505')
                return 'duplicate'
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(lambda _: attempt(), range(2))), ['duplicate', 'inserted'])
        self.assertEqual(self.totals(), (1, 1, 0, 0))

    def test_competing_decisions_have_one_head_version_and_atomic_audit(self):
        self.fixture()
        with self.database.transaction() as session: session.add(Head(id=1, version=0))
        barrier = threading.Barrier(2)
        def attempt(kind):
            barrier.wait(timeout=10)
            with self.database.transaction() as session:
                head = session.scalar(select(Head).where(Head.id == 1).with_for_update())
                if head.version != 0: return 'stale'
                session.add(Event(policy_id='university', policy_revision=1, event_type=kind,
                    actor_id=2, actor_capability='approve', authority_revision=1, head_version=1,
                    reason='Isolated lock protocol witness'))
                head.version = 1
                return 'accepted'
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(attempt, ('Approved', 'Rejected'))), ['accepted', 'stale'])
        self.assertEqual(self.totals(), (2, 1, 1, 1))

    def test_head_lock_can_order_revocation_before_decision_and_rollback_partial_event(self):
        self.fixture()
        with self.database.transaction() as session: session.add(Head(id=1, version=0))
        held, attempted, release = threading.Event(), threading.Event(), threading.Event()
        def revoke():
            with self.database.transaction() as session:
                session.scalar(select(Head).where(Head.id == 1).with_for_update())
                row = authority_row(2, 'approve', revision=2); row.decision = 'Revoked'; session.add(row)
                session.flush(); held.set()
                if not release.wait(10): raise AssertionError('Missing release')
        def decide():
            attempted.set()
            with self.database.transaction() as session:
                session.scalar(select(Head).where(Head.id == 1).with_for_update())
                latest = session.scalar(select(Authority).where(Authority.user_id == 2,
                    Authority.capability == 'approve').order_by(Authority.revision.desc()).limit(1))
                return latest.decision
        with ThreadPoolExecutor(max_workers=2) as pool:
            revoker = pool.submit(revoke); self.assertTrue(held.wait(10))
            decision = pool.submit(decide); self.assertTrue(attempted.wait(10))
            try: self.assertFalse(decision.done())
            finally: release.set()
            revoker.result(timeout=10); self.assertEqual(decision.result(timeout=10), 'Revoked')
        with self.assertRaises(RuntimeError), self.database.transaction() as session:
            head = session.scalar(select(Head).where(Head.id == 1).with_for_update())
            session.add(Event(policy_id='university', policy_revision=1, event_type='Approved',
                actor_id=2, actor_capability='approve', authority_revision=1, head_version=1,
                reason='Structural historic grant only, not a B2 authorization'))
            head.version = 1; session.flush(); raise RuntimeError('Isolated rollback')
        self.assertEqual(self.totals(), (3, 1, 0, 1))
        with self.database.transaction(read_only=True) as session: self.assertEqual(session.get(Head, 1).version, 0)

    def test_immutable_digest_does_not_claim_current_authority_or_lifecycle_authorization(self):
        self.fixture()
        with self.database.transaction() as session:
            revoked = authority_row(1, revision=2); revoked.decision = 'Revoked'; session.add(revoked)
        # Historic grant FKs preserve evidence; B2 must separately reject stale grants.
        with self.database.transaction() as session: session.add(policy_row(policy_document(revision=2)))
        approved = self.decision(); activated = self.decision('Activated', 2, approved)
        self.decision('Deactivated', 3, activated)
        with self.database.transaction() as session: session.add(Head(id=1, version=3, active_event_id=activated))
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.get(Head, 1).active_event_id, activated)
        # This witnesses the documented service boundary, not a usable governance command.

    def test_head_cannot_reset_its_version_by_deletion_truncation_or_overflow(self):
        with self.database.transaction() as session: session.add(Head(id=1, version=2**63 - 1))
        for statement in (delete(Head), text('TRUNCATE scheduling_cost_policy_head'), update(Head).values(version=0)):
            with self.assertRaises(IntegrityError), self.database.transaction() as session: session.execute(statement)
        with self.database.transaction(read_only=True) as session: self.assertEqual(session.get(Head, 1).version, 2**63 - 1)

    def test_authority_constraints_and_revision_boundaries(self):
        for key, value in (('capability', 'administrator'), ('decision', 'Automatic'), ('revision', 0),
                           ('revision', 2**63), ('authorization_ref', ''), ('reason', ' '), ('user_id', 999)):
            row = authority_row(); setattr(row, key, value)
            with self.subTest(key=key), self.assertRaises(DBAPIError), self.database.transaction() as session: session.add(row)
        with self.database.transaction() as session: session.add(authority_row(revision=2**63 - 1))
        self.assertEqual(self.totals(), (1, 0, 0, 0))

    def test_integrity_functions_use_their_own_schema_not_caller_shadow_tables(self):
        self.fixture()
        with self.database.transaction(read_only=True) as session:
            settings = session.execute(text("SELECT proconfig FROM pg_proc WHERE pronamespace=current_schema()::regnamespace "
                "AND proname LIKE 'ras_cost_%'")).scalars().all()
            self.assertEqual(len(settings), 5)
            self.assertTrue(all(any(self.schema in setting for setting in row) for row in settings))
            self.assertTrue(all(any(setting.startswith('search_path=pg_catalog,') and setting.endswith(', pg_temp')
                for setting in row) for row in settings))
        with self.database.transaction() as session:
            session.execute(text('CREATE SCHEMA "' + self.schema + '_shadow"'))
        self.addCleanup(self.drop_shadow)
        with self.assertRaises(IntegrityError), self.database.transaction() as session:
            session.execute(text('SET LOCAL search_path TO "' + self.schema + '_shadow", "' + self.schema + '"'))
            session.execute(text('CREATE TABLE scheduling_cost_policy_authority_revision '
                '(user_id int,capability text,revision bigint,decision text)'))
            session.execute(text("INSERT INTO scheduling_cost_policy_authority_revision VALUES (1,'propose',999,'Granted')"))
            row = policy_row(policy_document(revision=2)); row.proposer_authority_revision = 999
            session.add(row)

    def drop_shadow(self):
        with self.database.transaction() as session:
            session.execute(text('DROP SCHEMA "' + self.schema + '_shadow" CASCADE'))

    def test_temporary_shadow_event_cannot_make_approval_an_active_policy(self):
        self.fixture(); approved = self.decision()
        with self.assertRaises(IntegrityError), self.database.transaction() as session:
            session.execute(text('CREATE TEMP TABLE scheduling_cost_policy_event '
                '(id bigint, event_type text, head_version bigint) ON COMMIT DROP'))
            session.execute(text("INSERT INTO pg_temp.scheduling_cost_policy_event VALUES (:id,'Activated',1)"),
                {'id': approved})
            session.add(Head(id=1, version=1, active_event_id=approved))
        with self.database.transaction(read_only=True) as session: self.assertIsNone(session.get(Head, 1))


class PolicyMigrationTests(PostgresTestCase):
    migration_target = '0050a'

    def migrate(self, direction, target):
        with mock.patch.dict(os.environ, {'DATABASE_URL': self.url}):
            config = Config(str(ROOT / 'alembic.ini'))
            if direction == 'check': command.check(config)
            else: getattr(command, direction)(config, target)

    def actor(self):
        with self.database.transaction() as session:
            session.add(Role(id=1, name='Student')); session.flush()
            session.add(User(id=1, source_order=1, name='Fictional retained identity', primary_role_id=1))

    def test_additive_empty_upgrade_and_schema_drift(self):
        before = set(inspect(self.database.engine).get_table_names()); self.actor()
        self.migrate('upgrade', 'head')
        self.assertEqual(set(inspect(self.database.engine).get_table_names()) - before, set(TABLES))
        with self.database.transaction(read_only=True) as session:
            self.assertTrue(all(session.scalar(text('SELECT count(*) FROM ' + table)) == 0 for table in TABLES))
            self.assertEqual(session.scalar(text('SELECT version_num FROM alembic_version')), '0050b')
        self.migrate('check', None)

    def test_empty_downgrade_and_reupgrade_preserve_existing_identity(self):
        self.actor(); self.migrate('upgrade', 'head'); self.migrate('downgrade', '0050a')
        self.assertFalse(set(TABLES).intersection(inspect(self.database.engine).get_table_names()))
        self.migrate('upgrade', 'head')
        with self.database.transaction(read_only=True) as session: self.assertIsNotNone(session.get(User, 1))

    def test_populated_authority_or_head_blocks_downgrade(self):
        self.actor(); self.migrate('upgrade', 'head')
        with self.database.transaction() as session: session.add(authority_row())
        with self.assertRaisesRegex(RuntimeError, 'history'): self.migrate('downgrade', '0050a')
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Authority)), 1)
            self.assertEqual(session.scalar(text('SELECT version_num FROM alembic_version')), '0050b')

    def test_downgrade_waits_for_committed_append_then_refuses_history_loss(self):
        self.actor(); self.migrate('upgrade', 'head')
        held, release = threading.Event(), threading.Event()
        def append():
            with self.database.transaction() as session:
                session.add(authority_row()); session.flush(); held.set()
                if not release.wait(10): raise AssertionError('Missing release')
        with ThreadPoolExecutor(max_workers=2) as pool:
            writer = pool.submit(append); self.assertTrue(held.wait(10))
            downgrade = pool.submit(self.migrate, 'downgrade', '0050a')
            try: self.assertFalse(downgrade.done())
            finally: release.set()
            writer.result(timeout=10)
            with self.assertRaisesRegex(RuntimeError, 'history'): downgrade.result(timeout=10)

    def test_downgrade_locks_all_tables_before_emptiness_and_drop(self):
        self.actor(); self.migrate('upgrade', 'head')
        checked, release, committed = threading.Event(), threading.Event(), threading.Event()
        original = Operations.drop_table
        def pause(operations, name, *args, **kwargs):
            if name == Head.__tablename__:
                checked.set()
                if not release.wait(10): raise AssertionError('Missing release')
            return original(operations, name, *args, **kwargs)
        def append():
            try:
                with self.database.transaction() as session: session.add(authority_row())
                committed.set(); return 'committed'
            except DBAPIError as error:
                self.assertEqual(error.orig.sqlstate, '42P01'); return 'table_removed'
        with ThreadPoolExecutor(max_workers=2) as pool, mock.patch.object(Operations, 'drop_table', pause):
            downgrade = pool.submit(self.migrate, 'downgrade', '0050a'); self.assertTrue(checked.wait(10))
            with self.database.transaction(read_only=True) as session:
                locked = session.execute(text("SELECT c.relname FROM pg_locks l JOIN pg_class c ON c.oid=l.relation "
                    "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=:schema "
                    "AND l.mode='AccessExclusiveLock' AND l.granted"), {'schema': self.schema}).scalars().all()
                self.assertEqual(set(locked), set(TABLES))
            writer = pool.submit(append)
            try: self.assertFalse(committed.wait(.3))
            finally: release.set()
            downgrade.result(timeout=10); self.assertEqual(writer.result(timeout=10), 'table_removed')
        self.migrate('upgrade', 'head')

    def test_future_privileged_erasure_is_possible_but_not_an_application_command(self):
        self.actor(); self.migrate('upgrade', 'head')
        with self.database.transaction() as session: session.add(authority_row())
        with self.assertRaises(RuntimeError), self.database.transaction() as session:
            session.execute(text('ALTER TABLE scheduling_cost_policy_authority_revision DISABLE TRIGGER cost_authority_immutable'))
            session.execute(delete(Authority)); raise RuntimeError('transactional rollback')
        with self.assertRaises(IntegrityError), self.database.transaction() as session: session.execute(delete(Authority))
        with self.database.transaction() as session:
            session.execute(text('ALTER TABLE scheduling_cost_policy_authority_revision DISABLE TRIGGER cost_authority_immutable'))
            session.execute(delete(Authority))
            session.execute(text('ALTER TABLE scheduling_cost_policy_authority_revision ENABLE TRIGGER cost_authority_immutable'))
        self.migrate('downgrade', '0050a')

    def test_failed_upgrade_rolls_back_tables_functions_and_version(self):
        original = Operations.create_index
        def fail(operations, name, *args, **kwargs):
            if name == 'ix_cost_event_policy': raise RuntimeError('Isolated migration failure')
            return original(operations, name, *args, **kwargs)
        with mock.patch.object(Operations, 'create_index', fail), self.assertRaisesRegex(RuntimeError, 'Isolated'):
            self.migrate('upgrade', 'head')
        self.assertFalse(set(TABLES).intersection(inspect(self.database.engine).get_table_names()))
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(text('SELECT version_num FROM alembic_version')), '0050a')
        self.migrate('upgrade', 'head'); self.migrate('check', None)

    def test_initialized_head_alone_also_blocks_downgrade_without_data_loss(self):
        self.migrate('upgrade', 'head')
        with self.database.transaction() as session: session.add(Head(id=1, version=0))
        with self.assertRaisesRegex(RuntimeError, 'history'): self.migrate('downgrade', '0050a')
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.get(Head, 1).version, 0)
            self.assertEqual(session.scalar(text('SELECT version_num FROM alembic_version')), '0050b')

    def test_downgrade_lock_order_with_concurrent_decision_append_has_no_lost_history(self):
        self.actor(); self.migrate('upgrade', 'head')
        with self.database.transaction() as session:
            session.add(User(id=2, source_order=2, name='Fictional approver', primary_role_id=1)); session.flush()
            session.add_all([authority_row(), authority_row(2, 'approve')]); session.flush()
            session.add(policy_row())
        held, release = threading.Event(), threading.Event()
        def append():
            with self.database.transaction() as session:
                session.add(Event(policy_id='university', policy_revision=1, event_type='Approved',
                    actor_id=2, actor_capability='approve', authority_revision=1,
                    head_version=1, reason='Isolated concurrent history'))
                session.flush(); held.set()
                if not release.wait(10): raise AssertionError('Missing release')
        with ThreadPoolExecutor(max_workers=2) as pool:
            writer = pool.submit(append); self.assertTrue(held.wait(10))
            downgrade = pool.submit(self.migrate, 'downgrade', '0050a')
            try: self.assertFalse(downgrade.done())
            finally: release.set()
            writer.result(timeout=10)
            with self.assertRaisesRegex(RuntimeError, 'history'): downgrade.result(timeout=10)
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Event)), 1)
            self.assertEqual(session.scalar(text('SELECT version_num FROM alembic_version')), '0050b')
