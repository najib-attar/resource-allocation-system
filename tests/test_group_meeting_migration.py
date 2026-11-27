"""Exercise the group meeting schema boundary on a disposable PostgreSQL schema."""

import os
from datetime import date
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import DBAPIError

from postgres_fixtures import ROOT
from test_appointments import AppointmentFixture
from web.account_service import AccountService
from web.persistence.models import AppointmentCommitment, GroupMeetingAvailability, LoginAccount, Notification


class GroupMeetingMigrationTests(AppointmentFixture):
    def test_upgrade_preserves_existing_appointments_credentials_and_inbox(self):
        AccountService(self.database).provision(1, "fictional-migration-student", "fictional-migration-only")
        appointment_id = self.submit()
        self.service.decide(appointment_id, 2, 1, True)
        with self.database.transaction(read_only=True) as session:
            password_hash = session.get(LoginAccount, 1).password_hash
            inbox = list(session.execute(select(Notification.id, Notification.recipient_id).order_by(Notification.id)))
        self.assertTrue(inbox)
        config = Config(str(ROOT / "alembic.ini"))
        with patch.dict(os.environ, {"DATABASE_URL": self.url}):
            command.downgrade(config, "0051e")
            with self.database.transaction(read_only=True) as session:
                self.assertFalse(inspect(session.connection()).has_table("group_meeting"))
                self.assertEqual(session.scalar(text("SELECT version_num FROM alembic_version")), "0051e")
                self.assertEqual(list(session.execute(text("SELECT id, recipient_id FROM notification ORDER BY id"))), inbox)
            command.upgrade(config, "head")
            command.check(config)
        self.assertEqual(self.service.detail(appointment_id, 1)["status"], "Confirmed")
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.get(LoginAccount, 1).password_hash, password_hash)
            self.assertEqual(list(session.scalars(select(AppointmentCommitment.user_id)
                .where(AppointmentCommitment.appointment_id == appointment_id)
                .order_by(AppointmentCommitment.user_id))), [1, 2])
            self.assertEqual(list(session.execute(select(Notification.id, Notification.recipient_id)
                .order_by(Notification.id))), inbox)

    def test_populated_pilot_refuses_destructive_downgrade(self):
        with self.database.transaction() as session:
            session.add(GroupMeetingAvailability(owner_id=1, revision=1, valid_from=date(2030, 1, 1),
                valid_until=date(2030, 1, 31), windows=[], allow_relocation=False))
        with patch.dict(os.environ, {"DATABASE_URL": self.url}):
            with self.assertRaisesRegex(DBAPIError, "explicitly resolve group meeting records"):
                command.downgrade(Config(str(ROOT / "alembic.ini")), "0051e")
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(text("SELECT version_num FROM alembic_version")), self.head_revision)
            self.assertEqual(session.get(GroupMeetingAvailability, 1).revision, 1)
