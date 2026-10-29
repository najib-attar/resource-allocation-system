"""Real PostgreSQL, existing authenticated request middleware, synthetic records only."""

from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import secrets
import sys
import threading
import traceback
from unittest import mock
from zoneinfo import ZoneInfo

from flask import g, session as login_session
from sqlalchemy import delete, event, select, text
from sqlalchemy.exc import IntegrityError, OperationalError

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tests"))
from postgres_fixtures import PostgresTestCase
from test_appointments import seed_appointments, START
from web import app as web_app
from web.account_service import AccountService, Principal
from web.appointment_service import AppointmentService
from web.calendar_service import calendar_snapshot, epoch
from web.engine_gateway import EngineGateway
from web.persistence.database import Database, DatabaseBusy
from web.persistence.models import (Appointment, AppointmentCommitment, AppointmentInvitation, AppointmentProfessor,
    Base, BusySlot, CalendarBlock, LoginAccount, ProfessorAvailability, Role, User)
from web.persistence.repository import state_row
from research.cdmcs.i3b.service import CalendarProjectionService
from research.cdmcs.i3b.projection import ProjectionError, UnsupportedProjection
from research.cdmcs.i3a.adapter import normalize


class ReadonlyProjectionTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        self.faculty = seed_appointments(self.database)
        with self.database.transaction() as session:
            roles = {row.name: row.id for row in session.scalars(select(Role))}
            session.add_all([User(id=7, source_order=7, name="Fictional Administrator", primary_role_id=roles["Administrator"]),
                             User(id=8, source_order=8, name="Fictional Committee Staff", primary_role_id=roles["Staff"])])
        accounts = AccountService(self.database)
        for uid in range(1, 9):
            accounts.provision(uid, f"projection-fixture-{uid}", secrets.token_urlsafe(24), administrator=uid in (3, 7, 8))
        self.configure_web()
        self.projection = CalendarProjectionService(self.database)

    @contextmanager
    def context(self, actor=1, version=1):
        with web_app.app.test_request_context("/appointments/?organizerId=999"):
            if actor is not None:
                login_session["user_id"], login_session["session_version"] = actor, version
            web_app.app.preprocess_request()
            yield

    def selection(self, professors=(2,), invitees=(), start=START, end=None, **kwargs):
        return self.projection.for_selection(list(professors), list(invitees), 30, start,
            end or start + timedelta(hours=3), self.faculty, **kwargs)

    def block(self, actor, start=START, end=None, reason="Private test-only commitment"):
        with self.database.transaction() as session:
            row = CalendarBlock(user_id=actor, start_at=start, end_at=end or start + timedelta(hours=1), reason=reason)
            session.add(row)
            state_row(session, True).calendar_revision += 1

    def appointment(self, status="Pending Approval", organizer=4, professors=(2,), invitees=(), start=START):
        with self.database.transaction() as session:
            row = Appointment(organizer_id=organizer, purpose="Confidential fictional meeting purpose",
                              duration_minutes=60, start_at=start, end_at=start + timedelta(hours=1), status=status)
            session.add(row)
            session.flush()
            key = row.id
            session.add_all(AppointmentProfessor(appointment_id=key, user_id=uid, revision=1,
                decision="Approved" if status == "Confirmed" else "Declined" if status == "Declined" else "Pending") for uid in professors)
            session.add_all(AppointmentInvitation(appointment_id=key, user_id=uid) for uid in invitees)
            if status == "Confirmed":
                session.add_all(AppointmentCommitment(appointment_id=key, user_id=uid, start_at=row.start_at,
                    end_at=row.end_at) for uid in (organizer, *professors))
            return key

    def test_student_one_and_multiple_professors_use_the_shared_contract(self):
        with self.context():
            for professors in ((2,), (2, 3)):
                snapshot = self.selection(professors=professors, invitees=(4, 5)).internal_snapshot()
                self.assertEqual(sum(p.required for p in snapshot.participants), len(professors) + 1)
                self.assertEqual(sum(p.published_required for p in snapshot.participants), len(professors))
                self.assertFalse(snapshot.participants[0].published_required)

    def test_unavailable_and_declined_optional_students_never_become_required(self):
        self.block(5)
        key = self.appointment(organizer=1, invitees=(5,))
        with self.database.transaction() as session:
            session.get(AppointmentInvitation, (key, 5)).status = "Declined"
        with self.context():
            snapshot = self.projection.for_appointment(key).internal_snapshot()
            optional = snapshot.participants[-1]
            self.assertFalse(optional.required)
            self.assertEqual(snapshot.commitments[0].people, (optional.id,))

    def test_professor_and_admin_flag_can_review_only_an_existing_required_context(self):
        key = self.appointment(organizer=1, professors=(2, 3))
        for actor in (1, 2, 3):
            with self.context(actor):
                snapshot = self.projection.for_appointment(key).internal_snapshot()
                self.assertEqual(snapshot.candidate_mode, "explicit")
                self.assertEqual(snapshot.explicit_starts, (epoch(START),))

    def test_new_professor_admin_and_committee_initiation_are_not_invented(self):
        for actor in (2, 3, 7, 8):
            with self.context(actor), mock.patch("research.cdmcs.i3b.service.calendar_snapshot") as read:
                with self.assertRaises(UnsupportedProjection) as caught:
                    self.selection()
                self.assertEqual(caught.exception.code, "UNSUPPORTED_INITIATION")
                read.assert_not_called()

    def test_invitation_detail_visibility_does_not_grant_calendar_projection(self):
        key = self.appointment(organizer=1, invitees=(5,))
        self.assertEqual(AppointmentService(self.database, None).detail(key, 5)["id"], key)
        for actor in (5, 6, 7):
            with self.context(actor), mock.patch("research.cdmcs.i3b.service.calendar_snapshot") as read:
                with self.assertRaises(PermissionError):
                    self.projection.for_appointment(key)
                read.assert_not_called()

    def test_no_request_context_or_anonymous_context_cannot_read(self):
        with self.assertRaises(PermissionError):
            self.selection()
        with self.context(None), self.assertRaises(PermissionError):
            self.selection()

    def test_unrelated_and_missing_appointments_have_the_same_private_denial(self):
        key = self.appointment(organizer=4)
        errors = []
        for target in (key, key + 1000):
            with self.context(6), self.assertRaises(PermissionError) as caught:
                self.projection.for_appointment(target)
            errors.append(str(caught.exception))
        self.assertEqual(errors[0], errors[1])

    def test_wrapped_database_error_does_not_leak_its_sensitive_cause(self):
        marker = "Synthetic confidential SQL parameter"
        @contextmanager
        def busy(*args, **kwargs):
            try:
                raise OperationalError("SELECT private_calendar", {"private": marker}, RuntimeError(marker))
            except OperationalError as cause:
                raise DatabaseBusy("Busy") from cause
            yield
        with self.context(), mock.patch.object(self.database, "transaction", side_effect=busy):
            with self.assertRaises(ProjectionError) as caught:
                self.selection()
        self.assertNotIn(marker, "".join(traceback.format_exception(caught.exception)))

    def test_forged_principal_and_stale_session_are_rejected(self):
        with self.context(), mock.patch("research.cdmcs.i3b.service.calendar_snapshot") as read:
            g.principal = Principal(2, "Forged", "Instructor", True, 1)
            with self.assertRaises(PermissionError):
                self.selection()
            read.assert_not_called()
        with self.context():
            AccountService(self.database).revoke(1)
            with self.assertRaises(PermissionError):
                self.selection()

    def test_identical_identity_fields_in_another_schema_do_not_authorize_that_database(self):
        other = PostgresTestCase()
        other.setUp()
        self.addCleanup(other.doCleanups)
        faculty = seed_appointments(other.database)
        AccountService(other.database).provision(1, "foreign-realm-fixture", secrets.token_urlsafe(24))
        statements = []
        def capture(_, __, statement, *args):
            statements.append(statement)
        event.listen(other.database.engine, "before_cursor_execute", capture)
        try:
            with self.context(), self.assertRaises(PermissionError):
                CalendarProjectionService(other.database).for_selection([2], [], 30, START,
                    START + timedelta(hours=2), faculty)
            self.assertEqual(statements, [], "A foreign authentication realm must be denied before any reads")
        finally:
            event.remove(other.database.engine, "before_cursor_execute", capture)

    def test_disabled_identity_and_unknown_or_inactive_participants_fail_closed(self):
        with self.context():
            with self.database.transaction() as session:
                session.get(LoginAccount, 1).enabled = False
            with self.assertRaises(PermissionError):
                self.selection()
        with self.database.transaction() as session:
            session.get(LoginAccount, 1).enabled = True
            session.get(User, 2).status = "inactive"
        with self.context():
            for professors in ((2,), (999,)):
                with self.assertRaises(ProjectionError):
                    self.selection(professors=professors)

    def test_only_confirmed_materialized_appointments_block(self):
        for status in ("Pending Approval", "Declined", "Cancelled", "Confirmed"):
            self.appointment(status=status)
        with self.context():
            snapshot = self.selection().internal_snapshot()
            self.assertEqual(len(snapshot.commitments), 1)
            self.assertEqual(snapshot.commitments[0].interval.start, epoch(START))

    def test_cross_midnight_publication_windows_keep_the_actual_manual_interval(self):
        start = datetime(2030, 1, 7, 20, 30, tzinfo=timezone.utc)
        with self.database.transaction() as session:
            session.execute(delete(ProfessorAvailability).where(ProfessorAvailability.user_id == 2))
            for day, a, b in ((1, 1380, 1440), (2, 0, 60)):
                session.add(ProfessorAvailability(user_id=2, day=day, start_minutes=a, end_minutes=b,
                    valid_from=date(2030, 1, 7), valid_until=date(2030, 1, 8), timezone="Europe/Istanbul", excluded_dates=[]))
        key = self.appointment(organizer=1, start=start)
        with self.context(2):
            snapshot = self.projection.for_appointment(key).internal_snapshot()
        self.assertEqual(snapshot.duration, 60)
        self.assertEqual(snapshot.explicit_starts, (epoch(start),))
        self.assertEqual(len(snapshot.participants[1].published), 2)
        result, _ = AppointmentService(self.database, EngineGateway(ROOT)).evaluate(
            1, [2], [], 60, start, start + timedelta(hours=1), proposed=(start, start + timedelta(hours=1)))
        self.assertTrue(result["feasible"])

    def test_ambiguous_and_nonexistent_published_wall_times_fail_closed(self):
        for day in (date(2026, 3, 29), date(2026, 10, 25)):
            with self.database.transaction() as session:
                session.execute(delete(ProfessorAvailability).where(ProfessorAvailability.user_id == 2))
                session.add(ProfessorAvailability(user_id=2, day=7, start_minutes=150, end_minutes=210,
                    valid_from=day, valid_until=day, timezone="Europe/Berlin", excluded_dates=[]))
            start = datetime.combine(day, datetime.min.time(), timezone.utc)
            with self.context(), self.assertRaises(ProjectionError) as caught:
                self.selection(start=start)
            self.assertEqual(caught.exception.code, "CALENDAR_CONFIGURATION")

    def test_room_organizer_commitment_uses_existing_booking_and_cancellation(self):
        from web.room_request_service import RoomRequestService
        rooms = RoomRequestService(self.database, EngineGateway(ROOT))
        rooms.configure_approver(7, self.faculty, 7)
        rooms.configure_room(7, 301, self.faculty, True, ["study"])
        key = rooms.submit(1, dict(start=START, duration=60, count=3, category="study",
            purpose="Confidential fictional room use", features=[]), [], 301)
        rooms.decide(key, 7, 1, True)
        with self.context():
            snapshot = self.selection().internal_snapshot()
            self.assertEqual(snapshot.commitments[0].people, (snapshot.organizer,))
        rooms.cancel(key, 1, 1)
        with self.context():
            self.assertEqual(self.selection().internal_snapshot().commitments, ())

    def test_equipment_deadlines_do_not_become_participant_busy_time(self):
        from web.equipment_service import EquipmentService
        equipment = EquipmentService(self.database, EngineGateway(ROOT))
        equipment.assign_custodian(7, self.faculty, 7)
        kind = equipment.create_type(7, self.faculty, "Fictional boards", "Fictional diagnostic board", "", {}, 7, "Faculty desk")
        equipment.add_unit(7, kind, "I3B-SYNTHETIC-BOARD")
        key = equipment.submit(1, self.faculty, [{"typeId": kind, "quantity": 1}], START,
            START + timedelta(days=2), "Fictional project", "", secrets.token_hex(16))
        equipment.decide(7, key, True)
        with mock.patch("web.equipment_service.datetime") as clock:
            clock.now.return_value = START + timedelta(hours=1)
            equipment.handover(7, key, "usable")
        with self.context():
            self.assertEqual(self.selection().internal_snapshot().commitments, ())

    def test_existing_database_constraints_reject_inconsistent_commitments(self):
        key = self.appointment()
        with self.assertRaises(IntegrityError):
            with self.database.transaction() as session:
                session.add(AppointmentCommitment(appointment_id=key, user_id=2,
                    start_at=START, end_at=START + timedelta(hours=1)))
        with self.context():
            self.assertEqual(self.selection().internal_snapshot().commitments, ())

    def test_confirmed_review_excludes_only_its_own_commitment(self):
        key = self.appointment(status="Confirmed", organizer=1)
        self.block(2, START + timedelta(minutes=15), START + timedelta(minutes=45))
        with self.context(1):
            snapshot = self.projection.for_appointment(key).internal_snapshot()
            self.assertEqual(len(snapshot.commitments), 1)
            self.assertEqual(snapshot.commitments[0].interval.start, epoch(START + timedelta(minutes=15)))

    def test_confirmed_professor_detail_access_does_not_grant_projection(self):
        key = self.appointment(status="Confirmed", organizer=1)
        self.assertEqual(AppointmentService(self.database, None).detail(key, 2)["status"], "Confirmed")
        with self.context(2), mock.patch("research.cdmcs.i3b.service.calendar_snapshot") as read:
            with self.assertRaises(UnsupportedProjection) as caught:
                self.projection.for_appointment(key)
            self.assertEqual(caught.exception.code, "NO_PENDING_REVIEW")
            read.assert_not_called()

    def test_historical_appointment_access_cannot_be_used_to_query_calendars(self):
        for status in ("Declined", "Cancelled"):
            key = self.appointment(status=status, organizer=1)
            with self.context(), self.assertRaises(UnsupportedProjection):
                self.projection.for_appointment(key)

    def test_published_exclusions_blocks_and_missing_hours(self):
        with self.database.transaction() as session:
            row = session.scalar(select(ProfessorAvailability).where(ProfessorAvailability.user_id == 2))
            row.excluded_dates = ["2030-01-07"]
        with self.context():
            self.assertEqual(self.selection().internal_snapshot().participants[1].published, ())
        with self.database.transaction() as session:
            session.execute(delete(ProfessorAvailability).where(ProfessorAvailability.user_id == 2))
        with self.context():
            participant = self.selection().internal_snapshot().participants[1]
            self.assertEqual(participant.calendar_state, "known")
            self.assertEqual(participant.published, ())

    def test_touching_windows_and_overlaps_preserve_production_grid_anchor(self):
        with self.database.transaction() as session:
            session.execute(delete(ProfessorAvailability).where(ProfessorAvailability.user_id == 2))
            for a, b in ((607, 667), (667, 787)):
                session.add(ProfessorAvailability(user_id=2, day=1, start_minutes=a, end_minutes=b,
                    valid_from=date(2030, 1, 1), valid_until=date(2030, 1, 31), timezone="Europe/Istanbul", excluded_dates=[]))
        self.block(1, START + timedelta(minutes=22), START + timedelta(minutes=52))
        with self.context():
            snapshot = self.selection(start=START + timedelta(minutes=10)).internal_snapshot()
            self.assertEqual(snapshot.participants[1].published[0].start, epoch(START + timedelta(minutes=7)))
            self.assertEqual(len(snapshot.commitments), 1)
            self.assertEqual(normalize(snapshot).candidates[0], epoch(START + timedelta(minutes=22)))

    def test_dated_midnight_and_dst_instants_are_not_rounded_or_reinterpreted(self):
        for zone, start in (("Europe/Istanbul", datetime(2030, 1, 7, 20, 30, tzinfo=timezone.utc)),
                            ("Europe/Berlin", datetime(2026, 3, 29, 0, 30, tzinfo=timezone.utc)),
                            ("Europe/Berlin", datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc))):
            self.block(1, start, start + timedelta(hours=1))
            with mock.patch.dict("os.environ", {"RESOURCE_ALLOCATION_TIMEZONE": zone}), self.context():
                snapshot = self.selection(start=start).internal_snapshot()
                self.assertEqual(snapshot.zone, zone)
                self.assertEqual(snapshot.commitments[0].interval.end - snapshot.commitments[0].interval.start, 3600)
                self.assertEqual(snapshot.horizon.start, epoch(start))

    def test_naive_and_subminute_times_or_invalid_calendar_configuration_fail(self):
        with self.context():
            for start in (START.replace(tzinfo=None), START + timedelta(seconds=1)):
                with self.assertRaises(ProjectionError):
                    self.selection(start=start)
        with self.database.transaction() as session:
            row = session.scalar(select(ProfessorAvailability).where(ProfessorAvailability.user_id == 2))
            row.timezone = "Private/InvalidTimezone"
        with self.context(), self.assertRaises(ProjectionError) as caught:
            self.selection()
        self.assertNotIn("Private", str(caught.exception))

    def test_aware_local_request_gaps_and_folds_are_not_silently_converted(self):
        for value in (datetime(2026, 3, 29, 2, 30, tzinfo=ZoneInfo("Europe/Berlin")),
                      datetime(2026, 10, 25, 2, 30, tzinfo=ZoneInfo("Europe/Berlin"))):
            with self.context(), self.assertRaises(ProjectionError):
                self.selection(start=value)

    def test_explicit_unambiguous_zone_offsets_preserve_the_same_utc_interval(self):
        with self.context():
            for zone in ("UTC", "Europe/Istanbul", "Europe/Berlin"):
                snapshot = self.selection(start=START.astimezone(ZoneInfo(zone))).internal_snapshot()
                self.assertEqual(snapshot.horizon.start, epoch(START))

    def test_explicit_legacy_binding_and_unresolved_mandatory_optional_calendars(self):
        with self.database.transaction() as session:
            row = BusySlot(user_id=2, source_order=1, day=1, start_minutes=600, end_minutes=660, reason="Private class")
            session.add(row)
            session.flush()
            key = row.id
        with self.context():
            self.assertEqual(self.selection().internal_snapshot().participants[1].calendar_state, "unresolved")
        AppointmentService(self.database, None).bind_legacy("Explicit fictional January", date(2030, 1, 1), date(2030, 1, 31), busy_id=key)
        with self.context():
            snapshot = self.selection().internal_snapshot()
            self.assertEqual(snapshot.participants[1].calendar_state, "known")
            self.assertEqual(snapshot.commitments[0].interval.start, epoch(START))
            self.assertEqual(self.selection(start=START + timedelta(days=28)).internal_snapshot().commitments, ())
        with self.database.transaction() as session:
            session.add(BusySlot(user_id=5, source_order=2, day=1, start_minutes=600, end_minutes=660, reason="Unknown optional applicability"))
        with self.context():
            snapshot = self.selection(invitees=(5,)).internal_snapshot()
            self.assertEqual(snapshot.participants[-1].calendar_state, "unresolved")
            self.assertFalse(snapshot.participants[-1].required)

    def test_resource_constraints_are_explicitly_unsupported(self):
        with self.context(), self.assertRaises(UnsupportedProjection) as caught:
            self.selection(required_resources=("room",))
        self.assertEqual(caught.exception.code, "UNSUPPORTED_RESOURCES")

    def test_empty_manual_proposal_is_not_silently_converted_to_a_search(self):
        with self.context(), self.assertRaises(ProjectionError) as caught:
            self.selection(proposed=[])
        self.assertEqual(caught.exception.code, "INVALID_PROPOSAL")

    def test_snapshot_has_no_private_metadata_or_database_identifiers(self):
        self.appointment(status="Confirmed")
        self.block(5, reason="Private optional reason")
        with self.context():
            result = self.selection(invitees=(5,))
        encoded = json.dumps(asdict(result.internal_snapshot()))
        for value in ("Confidential", "Professor Ada", "Student Mira", "Private", self.url,
                      "organizerId", "appointment_id", "reason", "purpose", "email"):
            self.assertNotIn(value, encoded)
        self.assertNotIn("person-", repr(result))
        self.assertNotIn("person-", repr(result.internal_snapshot()))

    def fingerprint(self):
        digest = hashlib.sha256()
        with self.database.transaction(read_only=True) as session:
            for name in sorted(Base.metadata.tables):
                rows = list(session.scalars(text(f'SELECT to_jsonb(t)::text FROM "{name}" AS t ORDER BY to_jsonb(t)::text')))
                digest.update(json.dumps([name, rows]).encode())
            sequences = session.execute(text("SELECT sequencename,last_value FROM pg_sequences WHERE schemaname=:schema ORDER BY sequencename"), {"schema": self.schema})
            digest.update(repr(list(sequences)).encode())
        return digest.hexdigest()

    def test_all_tables_sequences_and_notifications_remain_unchanged_without_engine_calls(self):
        before = self.fingerprint()
        statements = []
        def capture(_, __, statement, *args):
            statements.append(statement.lstrip().split()[0].upper())
        event.listen(self.database.engine, "before_cursor_execute", capture)
        try:
            with self.context(), mock.patch("subprocess.Popen", side_effect=AssertionError("No engine execution")):
                self.selection()
        finally:
            event.remove(self.database.engine, "before_cursor_execute", capture)
        self.assertEqual(before, self.fingerprint())
        self.assertFalse(set(statements) & {"INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP"})

    def test_repeatable_read_readonly_and_autoflush_are_enforced(self):
        original = calendar_snapshot
        def inspect(session, *args, **kwargs):
            self.assertFalse(session.autoflush)
            self.assertEqual(session.scalar(text("SHOW transaction_isolation")), "repeatable read")
            self.assertEqual(session.scalar(text("SHOW transaction_read_only")), "on")
            return original(session, *args, **kwargs)
        with self.context(), mock.patch("research.cdmcs.i3b.service.calendar_snapshot", side_effect=inspect):
            self.selection()

    def test_postgresql_rejects_injected_dml_and_rolls_back(self):
        before = self.fingerprint()
        def mutate(session, *args, **kwargs):
            session.execute(text("UPDATE application_state SET calendar_revision=calendar_revision+1"))
        with self.context(), mock.patch("research.cdmcs.i3b.service.calendar_snapshot", side_effect=mutate):
            with self.assertRaises(ProjectionError) as caught:
                self.selection()
        self.assertEqual(caught.exception.code, "DATABASE_READ_FAILED")
        self.assertEqual(before, self.fingerprint())

    def test_database_connection_failure_does_not_fall_back_or_echo_credentials(self):
        def unavailable(*args):
            raise OperationalError("CONNECT", {}, RuntimeError("Fictional private connection password"))
        with self.context():
            self.database.engine.dispose()
            event.listen(self.database.engine, "do_connect", unavailable)
            try:
                with self.assertRaises(ProjectionError) as caught:
                    self.selection()
                self.assertEqual(caught.exception.code, "DATABASE_READ_FAILED")
                self.assertNotIn("password", "".join(traceback.format_exception(caught.exception)))
            finally:
                event.remove(self.database.engine, "do_connect", unavailable)

    def test_same_database_in_another_pool_is_allowed_but_misbound_session_is_denied(self):
        equivalent = Database(self.database.url)
        self.addCleanup(equivalent.dispose)
        with self.context():
            self.assertEqual(CalendarProjectionService(equivalent).for_selection([2], [], 30, START,
                START + timedelta(hours=2), self.faculty).internal_snapshot().duration, 30)
        other = Database(self.database.url.set(database="not-connected-fictional-realm"))
        self.addCleanup(other.dispose)
        with self.context():
            # Database.transaction issues SET TRANSACTION before yielding, so reject
            # the foreign bind without connecting in this injected-session case.
            @contextmanager
            def misbound(*args, **kwargs):
                with other.sessions() as session:
                    yield session
            with mock.patch.object(self.database, "transaction", side_effect=misbound), self.assertRaises(PermissionError):
                self.selection()

    def test_dirty_orm_objects_are_detected_without_autoflush(self):
        before = self.fingerprint()
        original = calendar_snapshot
        def mutate(session, *args, **kwargs):
            session.get(User, 1).name = "Accidental private mutation"
            return original(session, *args, **kwargs)
        with self.context(), mock.patch("research.cdmcs.i3b.service.calendar_snapshot", side_effect=mutate):
            with self.assertRaises(ProjectionError) as caught:
                self.selection()
        self.assertEqual(caught.exception.code, "WRITE_ATTEMPT")
        self.assertEqual(before, self.fingerprint())

    def test_concurrent_changes_do_not_mix_revision_and_busy_rows(self):
        reached, resume = threading.Event(), threading.Event()
        original = calendar_snapshot
        results, errors = [], []
        def paused(session, *args, **kwargs):
            reached.set()
            if not resume.wait(15):
                raise RuntimeError("Bounded concurrency test timed out")
            return original(session, *args, **kwargs)
        def reader():
            try:
                with self.context():
                    results.append(self.selection())
            except Exception as error:
                errors.append(error)
        with mock.patch("research.cdmcs.i3b.service.calendar_snapshot", side_effect=paused):
            worker = threading.Thread(target=reader)
            worker.start()
            try:
                self.assertTrue(reached.wait(15))
                self.block(2)
            finally:
                resume.set()
                worker.join(20)
            self.assertFalse(worker.is_alive())
        self.assertFalse(errors)
        self.assertEqual(results[0].internal_snapshot().commitments, ())
        with self.context():
            current = self.selection()
        self.assertEqual(current.calendar_revision, results[0].calendar_revision + 1)
        self.assertEqual(len(current.internal_snapshot().commitments), 1)

    def test_projected_constraints_agree_with_real_production_validation(self):
        self.block(2, START + timedelta(minutes=30), START + timedelta(minutes=60))
        self.block(5)
        with self.context():
            snapshot = self.selection(invitees=(5,)).internal_snapshot()
        required = {p.id for p in snapshot.participants if p.required}
        service = AppointmentService(self.database, EngineGateway(ROOT))
        for offset in (0, 1, 30, 60, 90, 150):
            start = START + timedelta(minutes=offset)
            a, b = epoch(start), epoch(start + timedelta(minutes=30))
            expected = not any(required.intersection(c.people) and a < c.interval.end and c.interval.start < b for c in snapshot.commitments)
            result, _ = service.evaluate(1, [2], [5], 30, START, START + timedelta(hours=3), proposed=(start, start + timedelta(minutes=30)))
            self.assertEqual(result["feasible"], expected)


if __name__ == "__main__":
    import unittest
    unittest.main()
