"""Trusted application reads only. Nothing registers routes or invokes an engine."""

from contextlib import contextmanager

from flask import g, has_request_context, session as login_session
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError

from web.account_service import AccountService, Principal
from web.appointment_service import AppointmentError, AppointmentService
from web.calendar_service import aware, calendar_snapshot, local_instant, university_zone
from web.persistence.database import DatabaseBusy
from web.persistence.repository import PersistenceError

from .projection import ProjectionError, UnsupportedProjection, project_facts


class CalendarProjectionService:
    def __init__(self, database):
        self.database = database

    @contextmanager
    def _read(self):
        if not has_request_context() or not isinstance(getattr(g, "principal", None), Principal):
            raise PermissionError("An authenticated server-side request context is required.")
        authenticated = getattr(g, "authenticated_database_url", None)
        if not isinstance(authenticated, URL) or self.database.engine.url != authenticated:
            raise PermissionError("The projection must use the authenticated database context.")
        try:
            with self.database.transaction(read_only=True) as session, session.no_autoflush:
                if getattr(session.get_bind(), "url", None) != authenticated:
                    raise PermissionError("The projection session has an inconsistent database binding.")
                principal = AccountService(self.database).identity(login_session.get("user_id"),
                    login_session.get("session_version"), session=session)
                if principal is None or principal != g.principal:
                    raise PermissionError("The authenticated identity is missing, revoked or inconsistent.")
                yield session, principal
                if session.new or session.dirty or session.deleted:
                    raise ProjectionError("WRITE_ATTEMPT", "The read-only projection attempted an ORM mutation.")
        except (SQLAlchemyError, DatabaseBusy):
            raise ProjectionError("DATABASE_READ_FAILED", "The read-only calendar transaction could not complete.") from None
        except PersistenceError:
            raise ProjectionError("CALENDAR_CONFIGURATION", "Calendar configuration or participant data cannot be projected safely.") from None

    def for_selection(self, professor_ids, invited_ids, duration, start, end, faculty_id,
                      *, preferred=None, proposed=None, required_resources=()):
        with self._read() as (session, principal):
            if principal.role != "Student":
                raise UnsupportedProjection("UNSUPPORTED_INITIATION", "No appointment initiation permission is established for this workflow.")
            if required_resources:
                raise UnsupportedProjection("UNSUPPORTED_RESOURCES", "Exclusive resource semantics are not part of this appointment projection.")
            if type(faculty_id) is not int or faculty_id <= 0:
                raise ProjectionError("INVALID_SELECTION", "Select an existing faculty and valid participants.")
            if not isinstance(professor_ids, (tuple, list)) or not isinstance(invited_ids, (tuple, list)):
                raise ProjectionError("INVALID_SELECTION", "Participant selections must be bounded lists.")
            professors, invitees = list(professor_ids), list(invited_ids)
            AppointmentService(self.database, None)._participants(session, principal.user_id, professors, invitees, faculty_id)
            return self._project(session, principal.user_id, professors, invitees, duration, start, end,
                                 preferred=preferred, proposed=proposed)

    def for_appointment(self, appointment_id):
        with self._read() as (session, principal):
            if type(appointment_id) is not int or appointment_id <= 0:
                raise ProjectionError("INVALID_CONTEXT", "Select an existing appointment context.")
            service = AppointmentService(self.database, None)
            try:
                record, professors, invitations = service._visible(session, appointment_id, principal.user_id)
            except (AppointmentError, PermissionError):
                raise PermissionError("The appointment context is unavailable to this identity.") from None
            if principal.user_id not in {record.organizer_id, *(row.user_id for row in professors)}:
                raise PermissionError("Viewing an invitation does not grant calendar projection access.")
            if record.status not in {"Pending Approval", "Confirmed"}:
                raise UnsupportedProjection("INACTIVE_APPOINTMENT", "Historical appointment visibility does not grant a scheduling context.")
            if principal.user_id != record.organizer_id and record.status != "Pending Approval":
                raise UnsupportedProjection("NO_PENDING_REVIEW", "Appointment detail access does not grant a new calendar evaluation.")
            required, optional = [row.user_id for row in professors], [row.user_id for row in invitations]
            service._participants(session, record.organizer_id, required, optional)
            return self._project(session, record.organizer_id, required, optional, record.duration_minutes,
                                 record.start_at, record.end_at, exclude=record.id,
                                 proposed=(record.start_at, record.end_at), stored_instants=True)

    def _project(self, session, organizer, professors, invitees, duration, start, end, *,
                 preferred=None, proposed=None, exclude=None, stored_instants=False):
        def canonical(value):
            instant = aware(value)
            # Stored timestamptz values already identify an instant, including folds.
            # New local requests must pass the existing gap/fold validator first.
            return instant if stored_instants else local_instant(value.replace(tzinfo=None), value.tzinfo)

        start, end = canonical(start), canonical(end)
        preferred = canonical(preferred) if preferred is not None else None
        if proposed is not None:
            if not isinstance(proposed, (tuple, list)) or len(proposed) != 2:
                raise ProjectionError("INVALID_PROPOSAL", "A manual proposal requires an exact start/end interval.")
            proposed = (canonical(proposed[0]), canonical(proposed[1]))
        facts, revision = calendar_snapshot(session, organizer, professors, invitees, duration, start, end,
            action="validate" if proposed is not None else "recommend", proposed=proposed,
            preferred=preferred, exclude_appointment=exclude)
        return project_facts(facts, revision, university_zone().key)
