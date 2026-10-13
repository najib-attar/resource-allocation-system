"""Live PostgreSQL identity and dated-reservation foundation regressions."""

from datetime import datetime, timedelta, timezone
import secrets

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from postgres_fixtures import PostgresTestCase
from postgres_web_fixtures import seed_web_database
from web.account_service import AccountService
from web.persistence.models import Appointment, AppointmentCommitment, LoginAccount, User
from web.persistence.repository import PersistenceError


class AppointmentFoundationTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        seed_web_database(self.database, with_request=False)
        self.accounts = AccountService(self.database)
        self.password = secrets.token_urlsafe(24)

    def test_password_is_hashed_and_identity_cannot_be_self_assigned(self):
        self.accounts.provision(2, "ada", self.password)
        with self.database.transaction(read_only=True) as session:
            account = session.get(LoginAccount, 2)
            self.assertNotEqual(account.password_hash, self.password)
            self.assertTrue(account.password_hash.startswith("scrypt:"))
            self.assertFalse(account.administrator)
        self.assertEqual(self.accounts.authenticate("ADA", self.password).user_id, 2)
        self.assertIsNone(self.accounts.authenticate("ada", "wrong"))

    def test_provision_refuses_unknown_user_and_unapproved_overwrite(self):
        with self.assertRaises(PersistenceError):
            self.accounts.provision(999, "missing", self.password)
        self.accounts.provision(2, "ada", self.password)
        with self.assertRaises(PersistenceError):
            self.accounts.provision(2, "ada", self.password)
        with self.assertRaises(PersistenceError):
            self.accounts.provision(2, "ada", "short", reset=True)

    def test_sessions_are_revocable_and_inactive_users_cannot_sign_in(self):
        self.accounts.provision(2, "ada", self.password)
        principal = self.accounts.authenticate("ada", self.password)
        self.assertIsNotNone(self.accounts.identity(2, principal.session_version))
        self.accounts.revoke(2)
        self.assertIsNone(self.accounts.identity(2, principal.session_version))
        with self.database.transaction() as session:
            session.get(User, 2).status = "inactive"
        self.assertIsNone(self.accounts.authenticate("ada", self.password))

    def test_failed_logins_are_throttled_across_service_instances(self):
        self.accounts.provision(2, "ada", self.password)
        for _ in range(5):
            self.assertIsNone(self.accounts.authenticate("ada", "wrong"))
        self.assertIsNone(AccountService(self.database).authenticate("ada", self.password))

    def _reservation(self, start):
        with self.database.transaction() as session:
            appointment = Appointment(organizer_id=2, purpose="Fixture reservation", duration_minutes=60,
                                      start_at=start, end_at=start + timedelta(hours=1))
            session.add(appointment)
            session.flush()
            session.add(AppointmentCommitment(appointment_id=appointment.id, user_id=2,
                                              start_at=start, end_at=start + timedelta(hours=1)))

    def test_half_open_reservations_allow_adjacency_and_reject_overlap(self):
        start = datetime(2027, 1, 4, 10, tzinfo=timezone.utc)
        self._reservation(start)
        self._reservation(start + timedelta(hours=1))
        with self.assertRaises(IntegrityError):
            self._reservation(start + timedelta(minutes=30))
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(len(list(session.scalars(select(AppointmentCommitment)))), 2)

    def test_duration_and_reservation_interval_checks_reject_invalid_rows(self):
        start = datetime(2027, 1, 4, 10, tzinfo=timezone.utc)
        with self.assertRaises(IntegrityError):
            with self.database.transaction() as session:
                session.add(Appointment(organizer_id=2, purpose="Invalid", duration_minutes=30,
                                        start_at=start, end_at=start + timedelta(hours=1)))
