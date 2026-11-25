"""Verify the additive task migration and its downgrade guard on owned schemas."""

import os
from unittest import mock
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text

from postgres_fixtures import ROOT
from test_room_requests import RoomFixture
from web.account_service import AccountService
from web.persistence.models import LoginAccount, Role, User
from web.research_assistant_service import ResearchAssistantService


class ResearchTaskMigrationTests(RoomFixture):
    def test_upgrade_keeps_credentials_and_confirmed_meeting_and_protects_tasks(self):
        config = Config(str(ROOT / "alembic.ini"))
        with mock.patch.dict(os.environ, {"DATABASE_URL": self.url}):
            command.downgrade(config, "0051c")
        meeting = self.submit(professors=(2,))
        self.service.decide(meeting, 2, 1, True)
        with self.database.transaction() as session:
            assistant_role = session.scalar(select(Role.id).where(Role.name == "TeachingAssistant"))
            session.get(User, 4).primary_role_id = assistant_role
            session.get(User, 4).assistant_type = "Research Assistant"
            hashes = {actor: session.get(LoginAccount, actor).password_hash for actor in (1, 2, 4)}
            self.assertFalse(inspect(session.connection()).has_table("research_task"))

        with mock.patch.dict(os.environ, {"DATABASE_URL": self.url}):
            command.upgrade(config, "head")
            self.assertEqual(ResearchAssistantService(self.database).tasks(4)["items"], [])
            command.downgrade(config, "0051c")
            with self.database.transaction(read_only=True) as session:
                self.assertFalse(inspect(session.connection()).has_table("research_task"))
            command.upgrade(config, "head")
            service = ResearchAssistantService(self.database)
            service.create(4, uuid4(), "Saved research task")
            with self.assertRaisesRegex(RuntimeError, "preserve personal planning data"):
                command.downgrade(config, "0051c")

        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(text("SELECT version_num FROM alembic_version")), self.head_revision)
            self.assertEqual({actor: session.get(LoginAccount, actor).password_hash for actor in hashes}, hashes)
        self.assertTrue(AccountService(self.database).identity(4, 1).research_assistant)
        self.assertEqual(self.service.detail(meeting, 1)["status"], "Confirmed")
        self.assertEqual(service.tasks(4)["items"][0]["title"], "Saved research task")
