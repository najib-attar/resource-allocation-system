"""Participant-scoped appointment workflows and short transactional publication."""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError

from .calendar_service import (CalendarError, assert_commitments_compatible, aware, calendar_snapshot,
                               epoch, expand_weekly, university_zone)
from .persistence.models import (AcademicPeriod, Appointment, AppointmentCommitment, AppointmentEvent,
                                AppointmentInvitation, AppointmentProfessor, BusySlot, CalendarBlock,
                                LegacyCalendarBinding, OrganizationUnit, ProfessorAvailability,
                                ResourceRequest, Role, User)
from .persistence.repository import state_row, validate_unit_hierarchy


class AppointmentError(CalendarError):
    pass


REASONS = {
    "UNRESOLVED_CALENDAR": "A required participant has undated university commitments. An administrator must explicitly bind them to an academic period before availability can be determined.",
    "OUTSIDE_PUBLISHED_AVAILABILITY": "The time is outside one or more professors' published appointment hours.",
    "REQUIRED_PARTICIPANT_BUSY": "A required professor is unavailable at this time.",
    "ORGANIZER_BUSY": "The organizing student is unavailable at this time.",
    "NO_FEASIBLE_TIME": "No feasible appointment time was found in this period.",
    "INVALID_INTERVAL": "The proposed interval does not match the duration or search period.",
}


class AppointmentService:
    def __init__(self, database, gateway):
        self.database, self.gateway = database, gateway

    def directory(self):
        with self.database.transaction(read_only=True) as session:
            units = list(session.scalars(select(OrganizationUnit).order_by(OrganizationUnit.name)))
            parents = {item.id: item.parent_id for item in units}
            validate_unit_hierarchy(parents)
            faculties = [item for item in units if item.unit_type == "Faculty"]
            roles = {item.id: item.name for item in session.scalars(select(Role))}
            professors, students = [], []
            for user in session.scalars(select(User).where(func.lower(User.status) == "active").order_by(User.name, User.id)):
                role = roles[user.primary_role_id]
                if role == "Student":
                    students.append({"id": user.id, "name": user.name})
                if role != "Instructor":
                    continue
                ancestor = user.primary_unit_id
                while ancestor is not None and ancestor not in {item.id for item in faculties}:
                    ancestor = parents.get(ancestor)
                if ancestor is not None:
                    professors.append({"id": user.id, "name": user.name, "facultyId": ancestor})
            return {"faculties": [{"id": item.id, "name": item.name} for item in faculties],
                    "professors": professors, "students": students}

    def _participants(self, session, organizer, professors, invitees, faculty=None):
        if not professors or len(professors) > 100 or len(invitees) > 100:
            raise AppointmentError("Select 1-100 professors and at most 100 invited students.")
        ids = [organizer, *professors, *invitees]
        if any(type(item) is not int or item <= 0 for item in ids) or len(set(ids)) != len(ids):
            raise AppointmentError("Participants must be distinct existing university users.")
        roles = {item.id: item.name for item in session.scalars(select(Role))}
        users = {item.id: item for item in session.scalars(select(User).where(User.id.in_(ids)))}
        for pid in ids:
            expected = "Instructor" if pid in professors else "Student"
            if pid not in users or users[pid].status.casefold() != "active" or roles[users[pid].primary_role_id] != expected:
                raise AppointmentError("Select active students and professors with the appropriate university roles.")
        if faculty is not None:
            unit = session.get(OrganizationUnit, faculty)
            if unit is None or unit.unit_type != "Faculty":
                raise AppointmentError("Select a configured faculty.")
            parents = {item.id: item.parent_id for item in session.scalars(select(OrganizationUnit))}
            validate_unit_hierarchy(parents)
            for pid in professors:
                ancestor = users[pid].primary_unit_id
                while ancestor is not None and ancestor != faculty:
                    ancestor = parents[ancestor]
                if ancestor is None:
                    raise AppointmentError("Every selected professor must belong to the selected faculty.")

    def evaluate(self, organizer, professors, invitees, duration, start, end, proposed=None, preferred=None, exclude=None, faculty=None):
        with self.database.transaction(read_only=True) as session:
            self._participants(session, organizer, professors, invitees, faculty)
            snapshot, revision = calendar_snapshot(session, organizer, professors, invitees, duration, start, end,
                                                   "validate" if proposed else "recommend", proposed, preferred, exclude)
        result, _ = self.gateway.execute_appointment(snapshot)
        return result, revision

    def _feasible(self, result):
        if not result["feasible"]:
            raise AppointmentError(REASONS.get(result["reasonCode"], "The proposed time is unavailable."))

    def _current(self, state, revision):
        if state.calendar_revision != revision:
            raise AppointmentError("Calendar availability changed during evaluation. Please retry with current times.")

    def submit(self, organizer, professors, invitees, purpose, duration, start, faculty=None):
        start = aware(start)
        if type(duration) is not int or not 1 <= duration <= 1440:
            raise AppointmentError("Appointment duration must be 1-1440 minutes.")
        if not isinstance(purpose, str) or not purpose.strip() or len(purpose) > 2000:
            raise AppointmentError("Enter an appointment purpose of 1-2000 characters.")
        if start <= datetime.now(timezone.utc):
            raise AppointmentError("Select a future appointment time.")
        end = start + timedelta(minutes=duration)
        result, revision = self.evaluate(organizer, professors, invitees, duration, start, end, (start, end), faculty=faculty)
        self._feasible(result)
        with self.database.transaction() as session:
            self._current(state_row(session, True), revision)
            self._participants(session, organizer, professors, invitees, faculty)
            record = Appointment(organizer_id=organizer, purpose=purpose.strip(), duration_minutes=duration, start_at=start, end_at=end)
            session.add(record)
            session.flush()
            session.add_all(AppointmentProfessor(appointment_id=record.id, user_id=pid, revision=1) for pid in professors)
            session.add_all(AppointmentInvitation(appointment_id=record.id, user_id=pid) for pid in invitees)
            session.add(AppointmentEvent(appointment_id=record.id, actor_id=organizer, revision=1, message="Submitted for unanimous professor approval; no time reserved."))
            return record.id

    def _visible(self, session, appointment_id, actor):
        record = session.get(Appointment, appointment_id)
        if record is None:
            raise AppointmentError("Appointment not found.")
        professors = list(session.scalars(select(AppointmentProfessor).where(AppointmentProfessor.appointment_id == appointment_id).order_by(AppointmentProfessor.user_id)))
        invitations = list(session.scalars(select(AppointmentInvitation).where(AppointmentInvitation.appointment_id == appointment_id).order_by(AppointmentInvitation.user_id)))
        if actor not in {record.organizer_id, *(item.user_id for item in professors), *(item.user_id for item in invitations)}:
            raise PermissionError("This appointment is private to its participants.")
        return record, professors, invitations

    def detail(self, appointment_id, actor):
        with self.database.transaction(read_only=True) as session:
            record, professors, invitations = self._visible(session, appointment_id, actor)
            people = {record.organizer_id, *(item.user_id for item in professors), *(item.user_id for item in invitations)}
            names = {row.id: row.name for row in session.scalars(select(User).where(User.id.in_(people)))}
            return {"id": record.id, "organizerId": record.organizer_id, "organizerName": names[record.organizer_id],
                    "purpose": record.purpose, "start": record.start_at, "end": record.end_at,
                    "duration": record.duration_minutes, "revision": record.revision, "status": record.status,
                    "professors": [{"id": row.user_id, "name": names[row.user_id], "decision": row.decision} for row in professors],
                    "invitations": [{"id": row.user_id, "name": names[row.user_id], "status": row.status} for row in invitations],
                    "history": [row.message for row in session.scalars(select(AppointmentEvent).where(AppointmentEvent.appointment_id == record.id).order_by(AppointmentEvent.id))]}

    def list_for(self, actor):
        with self.database.transaction(read_only=True) as session:
            ids = list(session.scalars(select(Appointment.id).where(or_(Appointment.organizer_id == actor,
                        Appointment.id.in_(select(AppointmentProfessor.appointment_id).where(AppointmentProfessor.user_id == actor)),
                        Appointment.id.in_(select(AppointmentInvitation.appointment_id).where(AppointmentInvitation.user_id == actor))))
                                      .order_by(Appointment.start_at, Appointment.id)))
        return [self.detail(pid, actor) for pid in ids]

    def decide(self, appointment_id, actor, revision, approve):
        current = self.detail(appointment_id, actor)
        professors = [item["id"] for item in current["professors"]]
        if actor not in professors:
            raise PermissionError("Only a required professor may approve or reject.")
        calendar_revision = None
        if approve:
            result, calendar_revision = self.evaluate(current["organizerId"], professors,
                [item["id"] for item in current["invitations"]], current["duration"], current["start"], current["end"],
                (current["start"], current["end"]), exclude=appointment_id)
            self._feasible(result)
        try:
            with self.database.transaction() as session:
                state = state_row(session, True)
                if approve:
                    self._current(state, calendar_revision)
                record = session.get(Appointment, appointment_id, with_for_update=True)
                if record.revision != revision or record.status != "Pending Approval" or (approve and record.start_at <= datetime.now(timezone.utc)):
                    raise AppointmentError("The appointment revision/state changed or its time has passed. Refresh before deciding.")
                rows = list(session.scalars(select(AppointmentProfessor).where(AppointmentProfessor.appointment_id == appointment_id)))
                decision = next(row for row in rows if row.user_id == actor)
                decision.decision = "Approved" if approve else "Declined"
                if not approve:
                    record.status = "Declined"
                elif all(row.decision == "Approved" and row.revision == revision for row in rows):
                    record.status = "Confirmed"
                    session.add_all(AppointmentCommitment(appointment_id=record.id, user_id=pid,
                                                         start_at=record.start_at, end_at=record.end_at)
                                    for pid in [record.organizer_id, *professors])
                    state.calendar_revision += 1
                session.add(AppointmentEvent(appointment_id=record.id, actor_id=actor, revision=revision,
                                             message=f"Professor {'approved' if approve else 'declined'} revision {revision}; status: {record.status}."))
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23P01":
                raise AppointmentError("A required participant was just booked. Please select another time.") from error
            raise

    def reschedule(self, appointment_id, actor, revision, start):
        current = self.detail(appointment_id, actor)
        if current["organizerId"] != actor:
            raise PermissionError("Only the organizer may change the proposed time.")
        start = aware(start)
        if start <= datetime.now(timezone.utc):
            raise AppointmentError("Select a future time.")
        end = start + timedelta(minutes=current["duration"])
        result, calendar_revision = self.evaluate(actor, [item["id"] for item in current["professors"]],
                        [item["id"] for item in current["invitations"]], current["duration"], start, end, (start, end), exclude=appointment_id)
        self._feasible(result)
        with self.database.transaction() as session:
            state = state_row(session, True)
            self._current(state, calendar_revision)
            record = session.get(Appointment, appointment_id, with_for_update=True)
            if record.revision != revision or record.status not in {"Pending Approval", "Confirmed"}:
                raise AppointmentError("This revision cannot be rescheduled. Refresh its current status.")
            session.execute(delete(AppointmentCommitment).where(AppointmentCommitment.appointment_id == appointment_id))
            record.start_at, record.end_at = start, end
            record.revision += 1
            record.status = "Pending Approval"
            for professor in session.scalars(select(AppointmentProfessor).where(AppointmentProfessor.appointment_id == appointment_id)):
                professor.revision, professor.decision = record.revision, "Pending"
            state.calendar_revision += 1
            session.add(AppointmentEvent(appointment_id=record.id, actor_id=actor, revision=record.revision,
                                         message="Time changed; all professor approvals cleared and prior reservations released."))

    def cancel(self, appointment_id, actor, revision):
        with self.database.transaction() as session:
            state = state_row(session, True)
            record, professors, _ = self._visible(session, appointment_id, actor)
            if actor != record.organizer_id and actor not in {row.user_id for row in professors}:
                raise PermissionError("Only the organizer or a required professor may cancel.")
            if record.revision != revision or record.status == "Cancelled":
                raise AppointmentError("The appointment changed or was already cancelled.")
            record.status = "Cancelled"
            session.execute(delete(AppointmentCommitment).where(AppointmentCommitment.appointment_id == appointment_id))
            state.calendar_revision += 1
            session.add(AppointmentEvent(appointment_id=record.id, actor_id=actor, revision=record.revision, message="Cancelled; reserved mandatory-participant time released."))

    def decline_invitation(self, appointment_id, actor):
        with self.database.transaction() as session:
            state_row(session, True)
            record, _, _ = self._visible(session, appointment_id, actor)
            invitation = session.get(AppointmentInvitation, (appointment_id, actor))
            if actor == record.organizer_id or invitation is None:
                raise PermissionError("Only an invited student can decline participation; the organizer may cancel instead.")
            invitation.status = "Declined"
            session.add(AppointmentEvent(appointment_id=record.id, actor_id=actor, revision=record.revision, message="Invited student declined; professor confirmation requirements unchanged."))

    def publish_hours(self, actor, day, start_minutes, end_minutes, valid_from, valid_until, exclusions=()):
        if not date(1970, 1, 1) <= valid_from <= valid_until < date(2100, 1, 1):
            raise AppointmentError("Published appointment dates must be between 1970 and 2099.")
        if valid_until - valid_from > timedelta(days=730):
            raise AppointmentError("Publish at most two years of explicitly dated availability per pattern.")
        zone = university_zone()
        start = datetime.combine(valid_from, datetime.min.time(), zone)
        end = datetime.combine(valid_until + timedelta(days=1), datetime.min.time(), zone)
        expand_weekly(day, start_minutes, end_minutes, valid_from, valid_until, zone.key, start, end, exclusions)
        with self.database.transaction() as session:
            self._professor(session, actor)
            state = state_row(session, True)
            row = ProfessorAvailability(user_id=actor, day=day, start_minutes=start_minutes, end_minutes=end_minutes,
                                        valid_from=valid_from, valid_until=valid_until, timezone=zone.key, excluded_dates=list(exclusions))
            session.add(row)
            state.calendar_revision += 1

    def _professor(self, session, actor):
        user = session.get(User, actor)
        if user is None or session.get(Role, user.primary_role_id).name != "Instructor" or user.status.casefold() != "active":
            raise PermissionError("Only an active professor can manage appointment hours.")

    def remove_hours(self, actor, pattern_id):
        with self.database.transaction() as session:
            state = state_row(session, True)
            row = session.get(ProfessorAvailability, pattern_id)
            if row is None or row.user_id != actor:
                raise PermissionError("Only the publishing professor may remove these hours.")
            if session.scalar(select(AppointmentCommitment.appointment_id).where(AppointmentCommitment.user_id == actor,
                    AppointmentCommitment.end_at > datetime.now(timezone.utc)).limit(1)) is not None:
                raise AppointmentError("Cancel or reschedule future confirmed appointments before removing published hours.")
            session.delete(row)
            state.calendar_revision += 1

    def block(self, actor, start, end, reason=""):
        start, end = aware(start), aware(end)
        if start >= end or not isinstance(reason, str) or len(reason) > 2000:
            raise AppointmentError("Enter a valid blocked interval and a reason of at most 2000 characters.")
        with self.database.transaction() as session:
            state = state_row(session, True)
            assert_commitments_compatible(session, [{"userId": actor, "start": epoch(start), "end": epoch(end)}])
            session.add(CalendarBlock(user_id=actor, start_at=start, end_at=end, reason=reason))
            state.calendar_revision += 1

    def unblock(self, actor, block_id):
        with self.database.transaction() as session:
            state = state_row(session, True)
            row = session.get(CalendarBlock, block_id)
            if row is None or row.user_id != actor:
                raise PermissionError("Only the owner may remove a blocked interval.")
            session.delete(row)
            state.calendar_revision += 1

    def availability_for(self, actor):
        with self.database.transaction(read_only=True) as session:
            return {"hours": [{key: getattr(row, key) for key in ("id", "day", "start_minutes", "end_minutes", "valid_from", "valid_until", "excluded_dates")}
                              for row in session.scalars(select(ProfessorAvailability).where(ProfessorAvailability.user_id == actor).order_by(ProfessorAvailability.id))],
                    "blocks": [{"id": row.id, "start": row.start_at, "end": row.end_at, "reason": row.reason}
                               for row in session.scalars(select(CalendarBlock).where(CalendarBlock.user_id == actor).order_by(CalendarBlock.start_at))]}

    def bind_legacy(self, period_name, start_date, end_date, busy_id=None, request_id=None, week_start=None, exclusions=()):
        if not isinstance(period_name, str) or not period_name.strip() or len(period_name) > 200 or start_date > end_date or (busy_id is None) == (request_id is None):
            raise AppointmentError("Enter a named explicit academic period and exactly one legacy record.")
        try:
            for value in exclusions:
                date.fromisoformat(value)
        except (ValueError, TypeError) as error:
            raise AppointmentError("Use explicit YYYY-MM-DD exception dates.") from error
        if week_start is not None and (week_start.isoweekday() != 1 or week_start > end_date or (start_date - week_start).days > 6):
            raise AppointmentError("Planning week must start on a Monday and overlap the academic period.")
        with self.database.transaction() as session:
            state = state_row(session, True)
            if session.get(BusySlot if busy_id is not None else ResourceRequest, busy_id or request_id) is None:
                raise AppointmentError("The legacy record does not exist.")
            period = session.scalar(select(AcademicPeriod).where(AcademicPeriod.name == period_name))
            if period is None:
                period = AcademicPeriod(name=period_name, start_date=start_date, end_date=end_date, timezone=university_zone().key)
                session.add(period)
                session.flush()
            elif (period.start_date, period.end_date, period.timezone) != (start_date, end_date, university_zone().key):
                raise AppointmentError("The named period already has different dates/timezone; use its exact configuration.")
            session.add(LegacyCalendarBinding(period_id=period.id, busy_slot_id=busy_id, request_id=request_id,
                                              week_start=week_start, excluded_dates=list(exclusions)))
            session.flush()
            from .calendar_service import legacy_intervals
            commits = list(session.scalars(select(AppointmentCommitment)))
            if commits:
                values, _ = legacy_intervals(session, {row.user_id for row in commits}, min(row.start_at for row in commits),
                                             max(row.end_at for row in commits), state.active_run_id)
                assert_commitments_compatible(session, values)
            state.calendar_revision += 1
