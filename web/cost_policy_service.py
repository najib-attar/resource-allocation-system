"""Internal policy governance only: no routes, authority assignment or optimizer."""

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
import re

from flask import g, has_request_context, session as login_session
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError

from .account_service import AccountService, Principal
from .cost_policy_values import (COEFFICIENT_FIELDS, OBJECTIVE, OPERATION, RATE_MODEL,
    InstitutionalCostPolicy, parse_institutional_policy)
from .persistence.database import DatabaseBusy
from .persistence.models import (LoginAccount, User,
    SchedulingCostPolicyAuthorityRevision as Authority, SchedulingCostPolicyRevision as Revision,
    SchedulingCostPolicyEvent as Event, SchedulingCostPolicyHead as Head)
from .preference_values import PreferenceError, PreferenceUnavailable, check, label, number, zone


MAX_REVISION = 2**63 - 1


class PolicyAccessDenied(PermissionError):
    def __init__(self):
        super().__init__('Authenticated institutional policy authority is unavailable.')


class PolicyConflict(RuntimeError):
    def __init__(self):
        super().__init__('Policy revision or transition changed or cannot advance. Refresh before retrying.')


class PolicyStorageError(RuntimeError):
    def __init__(self):
        super().__init__('Institutional policy state could not be read or updated safely.')


@dataclass(frozen=True, repr=False)
class PolicyDecision:
    head_version: int
    revision: int
    digest: str
    status: str
    event_id: int | None = None

    def __repr__(self):
        return 'PolicyDecision(institutional_only=True; contents withheld)'


@dataclass(frozen=True, repr=False)
class PolicyCurrent:
    head_version: int
    state: str
    policy: InstitutionalCostPolicy | None = field(default=None, repr=False)

    def __repr__(self):
        return 'PolicyCurrent(institutional_only=True; contents withheld)'


@dataclass(frozen=True, repr=False)
class PolicyHistoryEntry:
    policy: InstitutionalCostPolicy
    status: str
    proposer_id: int
    proposer_authority_revision: int
    created_at: datetime
    events: tuple

    def __repr__(self):
        return 'PolicyHistoryEntry(institutional_only=True; contents withheld)'


@dataclass(frozen=True, repr=False)
class PolicyHistory:
    head_version: int
    entries: tuple
    next_before_revision: int | None

    def __repr__(self):
        return 'PolicyHistory(institutional_only=True; contents withheld)'


def _reason(value):
    try:
        check(type(value) is str and 0 < len(value) <= 2000 and bool(value.strip()) and '\0' not in value,
              'INVALID_REASON')
        value.encode('utf-8')
    except UnicodeError:
        raise PreferenceError('INVALID_REASON') from None
    return value


class CostPolicyService:
    def __init__(self, database, *, university_timezone):
        self.database = database
        self.timezone = zone(university_timezone)

    @staticmethod
    def _now(session):
        return session.scalar(select(func.clock_timestamp()))

    @staticmethod
    def _authority(session, uid, capability, now):
        # Future revisions are not effective early; never fall back after selecting
        # the latest begun revision, even if it is revoked or has expired.
        row = session.scalar(select(Authority).where(Authority.user_id == uid,
            Authority.capability == capability, Authority.effective_from <= now).order_by(
            Authority.revision.desc()).limit(1))
        if row is None or row.decision != 'Granted' or not row.effective_from <= now < row.effective_until:
            raise PolicyAccessDenied()
        try:
            label(row.authorization_ref)
            if not row.authorization_ref.strip() or not row.reason.strip():
                raise PolicyAccessDenied()
        except (PreferenceError, AttributeError, TypeError):
            raise PolicyAccessDenied() from None
        return row

    @contextmanager
    def _session(self, capability, *, write=False):
        principal = getattr(g, 'principal', None) if has_request_context() else None
        authenticated = getattr(g, 'authenticated_database_url', None) if has_request_context() else None
        if (type(principal) is not Principal or not isinstance(authenticated, URL)
                or type(principal.user_id) is not int or type(principal.session_version) is not int
                or type(principal.administrator) is not bool or type(principal.name) is not str
                or type(principal.role) is not str):
            raise PolicyAccessDenied()
        uid, version = login_session.get('user_id'), login_session.get('session_version')
        if (authenticated != self.database.engine.url or type(uid) is not int or type(version) is not int
                or uid != principal.user_id or version != principal.session_version):
            raise PolicyAccessDenied()
        try:
            with self.database.transaction(read_only=not write) as session, session.no_autoflush:
                bind = session.get_bind()
                if (getattr(bind, 'url', None) != authenticated or not session.is_active
                        or session.new or session.dirty or session.deleted):
                    raise PolicyAccessDenied()
                # After waiting for a revocation lock, writers must see its newly
                # committed row rather than a transaction's earlier snapshot.
                if write and session.scalar(text('SHOW transaction_isolation')) != 'read committed':
                    raise PolicyStorageError()
                schema = session.scalar(text('SELECT pg_catalog.current_schema()'))
                if schema is None:
                    raise PolicyAccessDenied()
                path = 'pg_catalog, ' + bind.dialect.identifier_preparer.quote(schema) + ', pg_temp'
                session.execute(text("SELECT pg_catalog.set_config('search_path', :path, true)"), {'path': path})
                if write:
                    session.execute(insert(Head).values(id=1, version=0).on_conflict_do_nothing(index_elements=['id']))
                    head = session.get(Head, 1, with_for_update=True, populate_existing=True)
                    # SHARE also blocks an authority INSERT that does not cooperate
                    # with the future head-first authority-management protocol.
                    session.execute(text('LOCK TABLE scheduling_cost_policy_authority_revision IN SHARE MODE'))
                    if session.get(LoginAccount, uid, with_for_update=True, populate_existing=True) is None:
                        raise PolicyAccessDenied()
                    if session.get(User, uid, with_for_update={'read': True}, populate_existing=True) is None:
                        raise PolicyAccessDenied()
                else:
                    head = session.get(Head, 1)
                current = AccountService(self.database).identity(uid, version, session=session)
                if current is None or current != principal:
                    raise PolicyAccessDenied()
                now = self._now(session)
                authority = self._authority(session, uid, capability, now)
                before = head.active_event_id if head else None
                yield session, current, head, authority, now
                if write:
                    session.flush()
                    final_now = self._now(session)
                    final_authority = self._authority(session, uid, capability, final_now)
                    if final_authority.revision != authority.revision:
                        raise PolicyAccessDenied()
                    if head.active_event_id is not None and head.active_event_id != before:
                        policy, _ = self._active(session, head)
                        if not policy.effective_from <= final_now < policy.effective_until:
                            raise PolicyConflict()
                elif session.new or session.dirty or session.deleted:
                    raise PolicyStorageError()
        except (SQLAlchemyError, DatabaseBusy):
            raise PolicyStorageError() from None

    def _policy(self, row):
        if row is None:
            raise PolicyConflict()
        return parse_institutional_policy({'policy_contract_version': row.contract_version,
            'origin': row.provenance_type, 'policy_id': row.policy_id, 'revision': row.revision,
            'objective_version': row.objective_version, 'engine_operation': row.engine_operation,
            'objective_model': row.objective_model, 'rate_model': row.rate_model, 'timezone': row.timezone,
            'effective': {'from': row.effective_from.isoformat(), 'until': row.effective_until.isoformat()},
            'cost_unit': row.cost_unit, 'calibration_ref': row.calibration_ref,
            'provenance': {'type': row.provenance_type, 'source_ref': row.provenance_ref},
            'coefficients': {key: getattr(row, key) for key in COEFFICIENT_FIELDS}},
            university_timezone=self.timezone, expected_digest=row.content_digest)

    @staticmethod
    def _events(session, revision, head_version):
        rows = list(session.scalars(select(Event).where(Event.policy_id == 'university',
            Event.policy_revision == revision).order_by(Event.head_version).limit(4)))
        state, previous = 'Proposed', None
        for event in rows:
            allowed = {'Proposed': ('Approved', 'Rejected'), 'Approved': ('Activated',),
                       'Activated': ('Deactivated',)}.get(state, ())
            if (event.event_type not in allowed or event.head_version > head_version
                    or event.preceding_event_id != (previous.id if state in ('Approved', 'Activated') else None)):
                raise PolicyStorageError()
            state, previous = event.event_type, event
        return state, rows

    def _active(self, session, head):
        last = session.scalar(select(Event).where(Event.event_type.in_(('Activated', 'Deactivated')))
            .order_by(Event.head_version.desc()).limit(1))
        highest = session.scalar(select(func.max(Event.head_version)))
        if highest is not None and (head is None or highest > head.version):
            raise PolicyStorageError()
        if head is None or head.active_event_id is None:
            if last is not None and last.event_type != 'Deactivated':
                raise PolicyStorageError()
            return None, 'deactivated' if last else 'missing'
        if last is None or last.id != head.active_event_id or last.event_type != 'Activated':
            raise PolicyStorageError()
        row = session.get(Revision, ('university', last.policy_revision))
        policy = self._policy(row)
        state, _ = self._events(session, row.revision, head.version)
        if state != 'Activated':
            raise PolicyStorageError()
        return policy, 'active'

    @staticmethod
    def _advance(head, expected):
        if head is None or head.version != expected or head.version == MAX_REVISION:
            raise PolicyConflict()
        return head.version + 1

    def propose(self, expected_head_version, document):
        number(expected_head_version, MAX_REVISION)
        policy = parse_institutional_policy(document, university_timezone=self.timezone)
        with self._session('propose', write=True) as (session, actor, head, grant, now):
            self._active(session, head)
            latest = session.scalar(select(func.max(Revision.revision))) or 0
            if latest == MAX_REVISION or policy.revision != latest + 1:
                raise PolicyConflict()
            head.version = self._advance(head, expected_head_version)
            row = Revision(policy_id='university', revision=policy.revision, contract_version=1, objective_version=1,
                engine_operation=OPERATION, objective_model=OBJECTIVE,
                rate_model=RATE_MODEL, timezone=policy.timezone,
                effective_from=policy.effective_from, effective_until=policy.effective_until,
                cost_unit=policy.cost_unit, calibration_ref=policy.calibration_ref,
                provenance_type='institutional_policy', provenance_ref=policy.provenance_ref,
                content_digest=policy.content_digest, proposer_id=actor.user_id,
                proposer_capability='propose', proposer_authority_revision=grant.revision,
                **policy.coefficients.document())
            session.add(row)
            return PolicyDecision(head.version, policy.revision, policy.content_digest, 'Proposed')

    def _decide(self, kind, expected_head_version, revision, digest, reason):
        number(expected_head_version, MAX_REVISION)
        number(revision, MAX_REVISION, 1)
        check(type(digest) is str and re.fullmatch('[0-9a-f]{64}', digest), 'INVALID_DIGEST')
        reason = _reason(reason)
        with self._session('approve', write=True) as (session, actor, head, grant, now):
            self._active(session, head)
            row = session.get(Revision, ('university', revision))
            policy = self._policy(row)
            if policy.content_digest != digest:
                raise PolicyConflict()
            state, events = self._events(session, revision, head.version)
            expected_state = {'Approved': 'Proposed', 'Rejected': 'Proposed',
                              'Activated': 'Approved', 'Deactivated': 'Activated'}[kind]
            if state != expected_state or (kind == 'Approved' and actor.user_id == row.proposer_id):
                raise PolicyConflict()
            if kind == 'Activated' and (head.active_event_id is not None
                    or not policy.effective_from <= now < policy.effective_until):
                raise PolicyConflict()
            if kind == 'Deactivated' and head.active_event_id != events[-1].id:
                raise PolicyConflict()
            next_version = self._advance(head, expected_head_version)
            event = Event(policy_id='university', policy_revision=revision, event_type=kind,
                actor_id=actor.user_id, actor_capability='approve', authority_revision=grant.revision,
                head_version=next_version, preceding_event_id=events[-1].id if events else None, reason=reason)
            session.add(event)
            session.flush()
            head.version = next_version
            if kind == 'Activated':
                head.active_event_id = event.id
            elif kind == 'Deactivated':
                head.active_event_id = None
            return PolicyDecision(head.version, revision, digest, kind, event.id)

    def approve(self, expected_head_version, revision, digest, reason):
        return self._decide('Approved', expected_head_version, revision, digest, reason)

    def reject(self, expected_head_version, revision, digest, reason):
        return self._decide('Rejected', expected_head_version, revision, digest, reason)

    def activate(self, expected_head_version, revision, digest, reason):
        return self._decide('Activated', expected_head_version, revision, digest, reason)

    def deactivate(self, expected_head_version, revision, digest, reason):
        return self._decide('Deactivated', expected_head_version, revision, digest, reason)

    def current(self):
        with self._session('audit') as (session, actor, head, grant, now):
            try:
                policy, state = self._active(session, head)
            except PreferenceUnavailable:
                return PolicyCurrent(head.version if head else 0, 'unsupported')
            except (PreferenceError, PolicyStorageError, PolicyConflict):
                return PolicyCurrent(head.version if head else 0, 'unknown')
            if policy is not None:
                if now < policy.effective_from:
                    return PolicyCurrent(head.version, 'not_effective')
                if now >= policy.effective_until:
                    return PolicyCurrent(head.version, 'expired')
            return PolicyCurrent(head.version if head else 0, state, policy)

    def history(self, *, limit=20, before_revision=None):
        number(limit, 100, 1)
        if before_revision is not None:
            number(before_revision, MAX_REVISION, 1)
        with self._session('audit') as (session, actor, head, grant, now):
            version = head.version if head else 0
            self._active(session, head)
            query = select(Revision).order_by(Revision.revision.desc())
            if before_revision is not None:
                query = query.where(Revision.revision < before_revision)
            rows = list(session.scalars(query.limit(limit + 1)))
            entries = []
            for row in rows[:limit]:
                policy = self._policy(row)
                state, events = self._events(session, row.revision, version)
                audit = tuple((e.id, e.event_type, e.actor_id, e.authority_revision,
                    e.head_version, e.created_at, e.reason, e.preceding_event_id) for e in events)
                entries.append(PolicyHistoryEntry(policy, state, row.proposer_id,
                    row.proposer_authority_revision, row.created_at, audit))
            return PolicyHistory(version, tuple(entries), rows[limit - 1].revision if len(rows) > limit else None)
