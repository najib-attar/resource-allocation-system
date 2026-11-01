"""Private self-scoped preference revisions, with no scheduling execution path."""

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime

from flask import g, has_request_context, session as login_session
from sqlalchemy import select
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError

from .account_service import AccountService, Principal
from .persistence.database import DatabaseBusy
from .persistence.models import LoginAccount, SchedulingPreferenceRevision, User
from .preference_values import (PreferenceError, PreferenceUnavailable, PreferenceValues,
                                VALUE_FIELDS, check, load_document, number, parse_values, record)


MAX_REVISION = 2**63 - 1


class PreferenceAccessDenied(PermissionError):
    def __init__(self):
        super().__init__('Authenticated self-preference access is unavailable.')


class PreferenceConflict(RuntimeError):
    def __init__(self):
        super().__init__('Preference revision changed or cannot advance. Refresh before retrying.')


class PreferenceStorageError(RuntimeError):
    state = 'unknown'

    def __init__(self):
        super().__init__('Private preference storage could not be read or updated safely.')


@dataclass(frozen=True, repr=False)
class PreferenceView:
    revision: int
    state: str
    stored_status: str | None = None
    preference_version: int | None = None
    created_at: datetime | None = field(default=None, repr=False)
    values: PreferenceValues | None = field(default=None, repr=False)

    def __repr__(self):
        return 'PreferenceView(private=True; contents withheld)'

    def document(self):
        """Explicit private return to the owner, never a research snapshot."""
        return {'origin': 'personal_preference', 'revision': self.revision, 'state': self.state,
                'status': self.stored_status, 'preference_version': self.preference_version,
                'created_at': self.created_at.isoformat() if self.created_at else None,
                'values': self.values.document() if self.values else None}


@dataclass(frozen=True, repr=False)
class PreferenceHistory:
    entries: tuple
    next_before_revision: int | None

    def __repr__(self):
        return 'PreferenceHistory(private=True; contents withheld)'


def replacement_values(document):
    if type(document) is bytes:
        document = load_document(document)
    record(document, ('preference_version', *VALUE_FIELDS))
    number(document['preference_version'], 2**31 - 1, 1)
    if document['preference_version'] != 1:
        raise PreferenceUnavailable('UNSUPPORTED_VERSION')
    return parse_values({key: document[key] for key in VALUE_FIELDS})


class SchedulingPreferenceService:
    def __init__(self, database):
        self.database = database

    @contextmanager
    def _session(self, *, write=False):
        principal = getattr(g, 'principal', None) if has_request_context() else None
        if type(principal) is not Principal:
            raise PreferenceAccessDenied()
        authenticated = getattr(g, 'authenticated_database_url', None)
        if not isinstance(authenticated, URL) or authenticated != self.database.engine.url:
            raise PreferenceAccessDenied()
        uid, version = login_session.get('user_id'), login_session.get('session_version')
        if (type(uid) is not int or type(version) is not int
                or uid != principal.user_id or version != principal.session_version):
            raise PreferenceAccessDenied()
        try:
            with self.database.transaction(read_only=not write) as session, session.no_autoflush:
                if (getattr(session.get_bind(), 'url', None) != authenticated or not session.is_active
                        or session.new or session.dirty or session.deleted):
                    raise PreferenceAccessDenied()
                if write:
                    # Account revocation/deletion and concurrent self-writes serialize here.
                    if session.get(LoginAccount, uid, with_for_update=True, populate_existing=True) is None:
                        raise PreferenceAccessDenied()
                    # Keep active university identity stable until the preference commit.
                    if session.get(User, uid, with_for_update={'read': True}, populate_existing=True) is None:
                        raise PreferenceAccessDenied()
                current = AccountService(self.database).identity(uid, version, session=session)
                if current is None or current != principal:
                    raise PreferenceAccessDenied()
                yield session, current.user_id
                if not write and (session.new or session.dirty or session.deleted):
                    raise PreferenceStorageError()
        except (SQLAlchemyError, DatabaseBusy):
            # Neither database exception text nor its bound parameters may escape.
            raise PreferenceStorageError() from None

    @staticmethod
    def _latest(session, owner):
        return session.scalar(select(SchedulingPreferenceRevision).where(
            SchedulingPreferenceRevision.owner_id == owner).order_by(
            SchedulingPreferenceRevision.revision.desc()).limit(1))

    @staticmethod
    def _view(row):
        if row is None:
            return PreferenceView(0, 'missing')
        if row.contract_version != 1:
            return PreferenceView(row.revision, 'unsupported', row.status, row.contract_version, row.created_at)
        if row.status == 'deactivated':
            return PreferenceView(row.revision, 'missing', row.status, row.contract_version, row.created_at)
        try:
            values = parse_values({'timezone': row.timezone,
                'effective': {'from': row.effective_from.isoformat(), 'until': row.effective_until.isoformat()},
                'preferred_weekdays': row.preferred_weekdays, 'preferred_windows': row.preferred_windows,
                'desired_gap_minutes': 'indifferent' if row.gap_indifferent else row.desired_gap_minutes})
        except PreferenceError as error:
            state = 'unsupported' if error.code == 'INVALID_TIMEZONE' else 'unknown'
            return PreferenceView(row.revision, state, row.status, row.contract_version, row.created_at)
        except (AttributeError, TypeError, ValueError):
            return PreferenceView(row.revision, 'unknown', row.status, row.contract_version, row.created_at)
        return PreferenceView(row.revision, 'configured', row.status, row.contract_version, row.created_at, values)

    def current(self):
        with self._session() as (session, owner):
            return self._view(self._latest(session, owner))

    def history(self, *, limit=20, before_revision=None):
        number(limit, 100, 1)
        if before_revision is not None:
            number(before_revision, MAX_REVISION, 1)
        with self._session() as (session, owner):
            query = select(SchedulingPreferenceRevision).where(SchedulingPreferenceRevision.owner_id == owner)
            if before_revision is not None:
                query = query.where(SchedulingPreferenceRevision.revision < before_revision)
            rows = list(session.scalars(query.order_by(SchedulingPreferenceRevision.revision.desc()).limit(limit + 1)))
            entries = tuple(self._view(row) for row in rows[:limit])
            return PreferenceHistory(entries, entries[-1].revision if len(rows) > limit else None)

    def replace(self, expected_revision, document):
        number(expected_revision, MAX_REVISION)
        values = replacement_values(document)
        return self._append(expected_revision, values)

    def deactivate(self, expected_revision):
        number(expected_revision, MAX_REVISION)
        return self._append(expected_revision, None)

    def _append(self, expected_revision, values):
        with self._session(write=True) as (session, owner):
            latest = self._latest(session, owner)
            current = latest.revision if latest is not None else 0
            if current != expected_revision or current == MAX_REVISION:
                raise PreferenceConflict()
            row = SchedulingPreferenceRevision(owner_id=owner, revision=current + 1,
                contract_version=1, status='configured' if values is not None else 'deactivated')
            if values is not None:
                document = values.document()
                row.timezone, row.effective_from, row.effective_until = values.timezone, values.first, values.last
                row.preferred_weekdays, row.preferred_windows = document['preferred_weekdays'], document['preferred_windows']
                row.gap_indifferent = values.desired_gap == 'indifferent'
                row.desired_gap_minutes = None if row.gap_indifferent else values.desired_gap
            session.add(row)
            session.flush()
            return self._view(row)
