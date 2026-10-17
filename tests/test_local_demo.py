"""Fictional launcher inputs must be usable without changing existing datasets."""

from datetime import date, datetime, timedelta
from pathlib import Path
import tempfile
import json
from unittest import TestCase
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from postgres_fixtures import PostgresTestCase, ROOT
from scripts.setup_local_demo import demo_inputs, prepare_settings, seed_local_demo
from web.account_service import AccountService
from web.appointment_service import AppointmentService
from web.engine_gateway import EngineGateway
from web.persistence.importer import ImportValidationError
from web.persistence.models import (AcademicPeriod, Allocation, AppointmentCommitment, FacultyRoomApprover,
                                    LoginAccount, ProfessorAvailability, RoomPolicy)


class LocalDemoConfigurationTests(TestCase):
    def test_configuration_is_private_stable_and_never_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            settings = prepare_settings(path)
            self.assertEqual(settings['databaseName'], 'resource_allocation')
            self.assertEqual(settings, prepare_settings(path))
            self.assertGreaterEqual(len(settings['sessionSecret']), 32)
            self.assertNotEqual(settings['postgresPassword'], settings['demoPassword'])
            with self.assertRaisesRegex(ValueError, 'never reset'):
                prepare_settings(path, seed=999)
            self.assertEqual(settings, prepare_settings(path))
            path.write_text(json.dumps([]), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'not an owned'):
                prepare_settings(path)

    def test_existing_database_name_is_preserved_and_unexpected_names_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            settings = prepare_settings(path)
            settings['databaseName'] = 'ras_university_demo'
            path.write_text(json.dumps(settings), encoding='utf-8')
            self.assertEqual(prepare_settings(path)['databaseName'], 'ras_university_demo')
            settings['databaseName'] = "unexpected'; DROP DATABASE postgres;--"
            path.write_text(json.dumps(settings), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Invalid saved'):
                prepare_settings(path)

    def test_inputs_are_seeded_fictional_and_professor_pair_shares_faculty(self):
        first, _ = demo_inputs(42)
        self.assertEqual(first, demo_inputs(42)[0])
        self.assertNotEqual(first, demo_inputs(43)[0])
        professors = [row for row in first['users'] if row['role'] == 'Instructor']
        self.assertEqual([row['primaryUnit'] for row in professors[:2]], ['Computing Department'] * 2)
        self.assertTrue(all(row['email'].endswith('@example.invalid') for row in first['users']))


class LocalDemoDatabaseTests(PostgresTestCase):
    def test_demo_has_accounts_published_calendars_and_real_allocations(self):
        password = 'Isolated-demo-password-42'
        summary = seed_local_demo(self.database, password, date(2030, 1, 7), date(2030, 1, 31))
        self.assertEqual(summary['counts'], {'users': 106, 'spaces': 20, 'requests': 120, 'busySlots': 12})
        self.assertEqual(len(summary['accounts']), 94)
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(LoginAccount)), 94)
            self.assertEqual(session.scalar(select(func.count()).select_from(ProfessorAvailability)), 60)
            self.assertEqual(session.scalar(select(func.count()).select_from(AcademicPeriod)), 1)
            self.assertGreater(session.scalar(select(func.count()).select_from(Allocation)), 0)
            self.assertEqual(session.scalar(select(func.count()).select_from(RoomPolicy)), 20)
            self.assertEqual(session.scalar(select(func.count()).select_from(FacultyRoomApprover)), 2)
        self.assertEqual(summary['configuredStudentRooms'], 20)
        accounts = AccountService(self.database)
        self.assertEqual(accounts.authenticate('student1', password).role, 'Student')
        self.assertEqual(accounts.authenticate('professor1', password).role, 'Instructor')
        self.assertTrue(accounts.authenticate('admin', password).administrator)
        client = self.configure_web()
        self.assertEqual(client.get('/appointments/').status_code, 200)
        self.assertEqual(client.get('/appointments/new').status_code, 200)
        self.assertNotIn(b'unresolved calendar', client.get('/appointments/calendar?from=2030-01-14').data)
        with self.assertRaisesRegex(ImportValidationError, 'already contains'):
            seed_local_demo(self.database, password, date(2030, 1, 7), date(2030, 1, 31))
        service = AppointmentService(self.database, EngineGateway(ROOT))
        start = datetime(2030, 1, 14, 9, tzinfo=ZoneInfo('Europe/Istanbul'))
        result, _ = service.evaluate(1, [81, 82], [2], 30, start, start + timedelta(days=4))
        self.assertTrue(result['feasible'])
        slot = datetime.fromtimestamp(result['recommendations'][0]['start'], ZoneInfo('Europe/Istanbul'))
        pid = service.submit(1, [81, 82], [2], 'Fictional multi-professor demonstration', 30, slot)
        for professor in (81, 82):
            service.decide(pid, professor, 1, True)
        self.assertEqual(service.detail(pid, 1)['status'], 'Confirmed')
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(AppointmentCommitment)), 3)

    def test_invalid_period_cannot_partially_seed_database(self):
        with self.assertRaises(ValueError):
            seed_local_demo(self.database, 'Isolated-demo-password-42', date(2030, 1, 31), date(2030, 1, 7))
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(LoginAccount)), 0)
