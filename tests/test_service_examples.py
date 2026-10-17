"""Three-service demo decisions, persisted assignments and delivery evidence."""

from datetime import date
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase
from sqlalchemy import func, select

from auth_fixtures import authorized_client
from scripts.seed_service_examples import seed_service_examples
from test_room_requests import RoomFixture
from web import app as web_app
from web.engine_gateway import EngineGateway
from web.equipment_service import EquipmentService
from web.notification_service import NotificationService
from web.persistence.models import (Appointment, AppointmentCommitment, BorrowRequest,
    AppointmentEvent, EquipmentEvent, EquipmentReservation, LoginAccount, Notification, RoomEvent, RoomOrganizerCommitment,
    RoomReservation, StudentRoomRequest, User)
from web.student_dashboard_service import StudentDashboardService
from postgres_fixtures import ROOT


class ServiceExampleSafetyTests(TestCase):
    def test_unowned_profile_is_refused_without_creating_or_overwriting_files(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)/'settings.json'
            for content in (None, '{"kind":"not-a-demo"}'):
                if content is not None:
                    path.write_text(content)
                result = subprocess.run([sys.executable, '-B', str(ROOT/'scripts/seed_service_examples.py'),
                                         '--state-dir', directory], capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(path.read_text() if path.exists() else None, content)


class ServiceExampleTests(RoomFixture):
    def setUp(self):
        super().setUp()
        self.equipment = EquipmentService(self.database, EngineGateway(ROOT))
        self.equipment.assign_custodian(6, self.faculty, 6)
        kind = self.equipment.create_type(6, self.faculty, 'Boards', 'Fictional teaching board', '', {}, 7, 'Faculty desk')
        for number in range(4):
            self.equipment.add_unit(6, kind, 'FICT-EXAMPLE-'+str(number))

    def examples(self):
        return seed_service_examples(self.database, EngineGateway(ROOT), 1, 2, 4,
                                     date(2030, 1, 7), date(2030, 1, 31))

    def test_all_nine_examples_have_real_assignments_and_auditable_notifications(self):
        cases = self.examples()
        self.assertEqual(len(cases), 9)
        expected = {'Appointment': ('Confirmed', 'Declined', 'Pending Approval'),
                    'Room': ('Confirmed', 'Rejected', 'Pending Faculty Approval'),
                    'Equipment': ('Approved', 'Rejected', 'Pending Approval')}
        for kind, statuses in expected.items():
            rows = [row for row in cases if row['service'] == kind]
            self.assertEqual(tuple(row['status'] for row in rows), statuses)
            self.assertEqual([row['assignedRecords'] for row in rows], [2 if kind != 'Room' else 1, 0, 0])
        with self.database.transaction(read_only=True) as session:
            for model in (Appointment, StudentRoomRequest, BorrowRequest):
                self.assertEqual(session.scalar(select(func.count()).select_from(model)), 3)
            for model, count in ((AppointmentCommitment, 2), (RoomReservation, 1),
                                 (RoomOrganizerCommitment, 1), (EquipmentReservation, 2)):
                self.assertEqual(session.scalar(select(func.count()).select_from(model)), count)
        notifications = NotificationService(self.database)
        for actor in (1, 2, 4, 6, 7):
            for item in notifications.inbox(actor, 100)['items']:
                self.assertEqual(item['recipient_id'], actor)
                self.assertNotEqual(item['actor_id'], actor)
                self.assertTrue(item['sender_name'] and item['recipient_name'])
                self.assertIsNotNone(item['created_at'].tzinfo)
                self.assertIn(item['current_status'], {s for states in expected.values() for s in states})

    def test_rerun_never_resets_manual_decisions_or_duplicates_examples(self):
        first = self.examples()
        pending = next(row for row in first if row['service'] == 'Appointment' and row['example'] == 'Pending')
        self.service.decide(pending['id'], 2, 1, True)
        second = self.examples()
        self.assertEqual([row['id'] for row in first], [row['id'] for row in second])
        self.assertTrue(all(not row['created'] for row in second))
        self.assertEqual(next(row['status'] for row in second if row['url'] == pending['url']), 'Confirmed')

    def test_authenticated_pending_decisions_clear_actions_counts_and_update_old_alerts(self):
        cases = self.examples()
        self.configure_web()
        student = authorized_client(web_app.app, 1)
        pending = [row for row in cases if row['example'] == 'Pending']
        self.assertEqual(StudentDashboardService(self.database).load(1)['counts']['pending'], 1)
        for row in pending:
            with self.database.transaction(read_only=True) as session:
                actor = session.scalar(select(LoginAccount.user_id).where(LoginAccount.username == row['decisionAccount']))
            decider = authorized_client(web_app.app, actor)
            if row['service'] == 'Appointment':
                response = decider.post(row['url']+'/decision', data={'revision': 1, 'decision': 'approve'})
                forbidden_button = b'Approve this revision'
                status = 'Confirmed'
            elif row['service'] == 'Room':
                response = decider.post(row['url']+'/decision', data={'revision': 1, 'decision': 'reject', 'reason': 'Demo rejection'})
                forbidden_button = b'Recheck and approve'
                status = 'Rejected'
            else:
                response = decider.post(row['url']+'/approve')
                forbidden_button = b'Approve and reserve'
                status = 'Approved'
            self.assertEqual(response.status_code, 302)
            page = decider.get(row['url'])
            self.assertEqual(page.status_code, 200)
            self.assertNotIn(forbidden_button, page.data)
            if row['service'] == 'Appointment':
                self.assertIn(b'My activity', page.data)
                self.assertNotIn(b'Notified:', page.data)
            else:
                self.assertIn(b'Operational audit log', page.data)
                self.assertIn(b'Notified:', page.data)
            self.assertIn(b'datetime=', page.data)
            self.assertIn(status.encode(), student.get(row['url']).data)
            receipts = [item for item in NotificationService(self.database).inbox(actor, 100)['items']
                        if item['subject_id'] == row['id'] and item['kind'] == row['service'].lower()]
            self.assertTrue(receipts)
            self.assertTrue(all(item['current_status'] == status for item in receipts))
        self.assertEqual(StudentDashboardService(self.database).load(1)['counts']['pending'], 0)
        home = student.get('/student/').get_data(as_text=True)
        self.assertNotIn('[Demo] Appointment - Pending', home.split('id="my-pending"')[-1].split('</section>')[0])

    def test_staff_audit_and_personal_activity_are_separated_in_backend_and_pages(self):
        cases = self.examples()
        self.configure_web()
        student = authorized_client(web_app.app, 1)
        for row in cases:
            if row['service'] == 'Appointment':
                detail = self.service.detail(row['id'], 1)
            elif row['service'] == 'Room':
                detail = self.rooms.detail(row['id'], 1)
            else:
                detail = self.equipment.detail(1, row['id'])
            self.assertFalse(detail['canAudit'])
            self.assertTrue(detail['history'])
            for event in detail['history']:
                self.assertNotIn('actorId', event)
                self.assertNotIn('recipients', event)
                self.assertIsNotNone(event['at'].tzinfo)
            page = student.get(row['url'])
            self.assertEqual(page.status_code, 200)
            self.assertIn(b'My activity', page.data)
            self.assertNotIn(b'Notified:', page.data)
            if row['service'] == 'Appointment':
                professor = self.service.detail(row['id'], 2)
                self.assertFalse(professor['canAudit'])
                self.assertTrue(professor['history'])
                self.assertTrue(all('recipients' not in event for event in professor['history']))
                if row['example'] != 'Pending':
                    self.assertTrue(any(event['ownAction'] for event in professor['history']))
            else:
                staff = self.rooms.detail(row['id'], 6) if row['service'] == 'Room' else self.equipment.detail(6, row['id'])
                self.assertTrue(staff['canAudit'])
                self.assertEqual(staff['history'][0]['actorId'], 1)
                self.assertTrue(staff['history'][0]['recipients'])
                self.assertIn(b'Operational audit log', authorized_client(web_app.app, 6).get(row['url']).data)
        with self.database.transaction(read_only=True) as session:
            for model, source in ((AppointmentEvent, Notification.appointment_event_id),
                                  (RoomEvent, Notification.room_event_id), (EquipmentEvent, Notification.equipment_event_id)):
                self.assertTrue(session.scalar(select(model.actor_id).order_by(model.id)))
                self.assertGreater(session.scalar(select(func.count()).select_from(Notification).where(source.is_not(None))), 0)
        outsider = authorized_client(web_app.app, 3)
        self.assertFalse(NotificationService(self.database).inbox(3)['items'])
        for row in cases:
            self.assertEqual(outsider.get(row['url']).status_code, 403)
        page = student.get('/notifications/').get_data(as_text=True)
        self.assertIn('Current status:', page)
        self.assertIn('From:', page)
        self.assertIn('To:', page)
        with self.database.transaction() as session:
            session.get(User, 2).name = '<script>Fictional professor</script>'
        page = student.get('/notifications/').get_data(as_text=True)
        self.assertIn('&lt;script&gt;Fictional professor&lt;/script&gt;', page)
        self.assertNotIn('<script>Fictional professor</script>', page)
