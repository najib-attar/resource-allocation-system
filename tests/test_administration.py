"""Administration composition over real PostgreSQL and existing scoped services."""
from datetime import datetime, timedelta, timezone
import uuid
from unittest import mock

from sqlalchemy import select

from test_room_requests import RoomFixture
from test_appointments import START
from web.account_service import AccountService
from web.admin_dashboard_service import AdminDashboardService
from web.engine_gateway import EngineGateway
from web.persistence.models import LoginAccount, Role, User
from web.persistence.repository import Repository


class AdministrationReadModelTests(RoomFixture):
    def setUp(self):
        super().setUp()
        self.dashboard = AdminDashboardService(self.database)

    def academic_request(self):
        return Repository(self.database).save_request(dict(type='OneTime', requesterId=2,
            spaceId=301, participantCount=5, title='Declared activity', purpose='Teaching',
            slots=[dict(day=1, startMinutes=600, endMinutes=660)]))

    def test_empty_dashboard_is_read_only_and_does_not_run_engine(self):
        with mock.patch.object(EngineGateway, '_execute', side_effect=AssertionError('GET executed engine')):
            result = self.dashboard.load(6)
        self.assertTrue(all(q['count'] == 0 and q['items'] == [] for q in result['queues'].values()))
        self.assertIsNone(result['activeRun'])
        self.assertEqual(result['resources'], 3)
        self.assertEqual(result['runs'], [])

    def test_all_five_roles_need_explicit_administrative_capability(self):
        with self.database.transaction() as session:
            role = session.scalar(select(Role).where(Role.name == 'TeachingAssistant'))
            session.get(User, 4).primary_role_id = role.id
        for actor in (1, 2, 4, 7):
            for method in (self.dashboard.load, self.dashboard.report):
                with self.subTest(actor=actor, method=method.__name__), self.assertRaises(PermissionError):
                    method(actor)
        self.dashboard.load(6)
        AccountService(self.database).provision(7, 'designated-admin', 'Synthetic-test-password', administrator=True, reset=True)
        self.dashboard.load(7)
        with self.database.transaction() as session:
            session.get(LoginAccount, 7).enabled = False
        with self.assertRaises(PermissionError): self.dashboard.load(7)

    def test_pending_room_queue_does_not_grant_blanket_admin_faculty_access(self):
        mine = self.request_room(room=301)
        foreign = self.request_room(room=302)
        queue = self.dashboard.load(6)['queues']['rooms']
        self.assertEqual(queue['count'], 1)
        self.assertEqual([r['id'] for r in queue['items']], [mine])
        self.assertNotIn(foreign, [r['id'] for r in queue['items']])
        self.rooms.configure_approver(6, self.faculty, 7)
        self.assertEqual(self.dashboard.load(6)['queues']['rooms']['count'], 0)

    def test_large_academic_queue_is_bounded_and_filter_does_not_change_counts(self):
        for _ in range(8): self.academic_request()
        result = self.dashboard.load(6)
        self.assertEqual(result['queues']['academic']['count'], 8)
        self.assertEqual(len(result['queues']['academic']['items']), 5)
        selected = self.dashboard.load(6, 'rooms')
        self.assertEqual(selected['queues']['academic']['count'], 8)
        self.assertEqual(selected['queues']['academic']['items'], [])
        with self.assertRaises(ValueError): self.dashboard.load(6, 'private')

    def test_count_and_rows_share_one_snapshot_during_committed_submission(self):
        self.academic_request()
        original = self.dashboard._count
        inserted = []
        def interleave(session, query):
            value = original(session, query)
            if not inserted: inserted.append(self.academic_request())
            return value
        with mock.patch.object(self.dashboard, '_count', side_effect=interleave):
            result = self.dashboard.load(6)
        self.assertEqual(result['queues']['academic']['count'], 1)
        self.assertEqual(len(result['queues']['academic']['items']), 1)
        self.assertEqual(self.dashboard.load(6)['queues']['academic']['count'], 2)

    def test_report_dates_denominator_and_current_faculty_scope(self):
        self.request_room(room=301)
        self.request_room(room=302)
        report = self.dashboard.report(6, 'rooms', '2030-01-07', '2030-01-07')
        self.assertEqual(report['states'], {'Pending Faculty Approval': 1})
        self.assertEqual(report['total'], 1)
        self.assertEqual(self.dashboard.report(6, 'rooms', '2030-01-08', '2030-01-08')['total'], 0)
        for values in [('private', None, None), ('rooms', 'bad', None),
                       ('rooms', '2030-02-01', '2030-01-01'), ('rooms', '2029-01-01', '2030-01-02'),
                       ('rooms', '9999-12-31', '9999-12-31')]:
            with self.subTest(values=values), self.assertRaises(ValueError): self.dashboard.report(6, *values)
        default = self.dashboard.report(6, now=datetime(2030, 1, 30, tzinfo=timezone.utc))
        self.assertEqual((default['start'], default['end']), ('2030-01-01', '2030-01-30'))

    def test_dashboard_never_reads_private_appointment_content_or_credentials(self):
        key = self.submit()
        data = str(self.dashboard.load(6))
        self.assertNotIn('Fictional project review', data)
        self.assertNotIn('password', data)
        self.assertNotIn('session_version', data)
        self.assertTrue(key)

    def test_run_history_rejects_unknown_ids_and_invalid_pages(self):
        with self.assertRaises(LookupError): self.dashboard.run_detail(6, 999)
        with self.assertRaises(PermissionError): self.dashboard.run_detail(1, 999)
        for key, page in [(True, 1), (0, 1), (2**63, 1), (1, 0), (1, 10001)]:
            with self.assertRaises(ValueError): self.dashboard.run_detail(key=key, actor=6, page=page)
        with self.assertRaises(ValueError): self.dashboard.run_detail(6, 1, allocation_page=True)

    def test_run_history_matches_persisted_engine_decisions(self):
        from web.academic_eligibility import EligibilityService
        from web.allocation_workflow import execute_allocation
        key = self.academic_request()
        EligibilityService(self.database).decide(6, key, 1, 0, True, 'Synthetic eligibility review')
        execute_allocation(Repository(self.database), self.rooms.gateway)
        home = self.dashboard.load(6)
        run = self.dashboard.run_detail(6, home['activeRun']['id'])
        self.assertEqual(run['decisions'], [dict(id=key, status='Approved', reason='')])
        self.assertEqual(run['allocations'][0]['requestId'], key)
        self.assertTrue(run['active'])
        self.assertEqual(run['allocationTotal'], 1)
        self.assertEqual(self.dashboard.run_detail(6, run['id'], allocation_page=2)['allocations'], [])
        self.assertEqual(home['allocationStates'], {'Approved': 1})

    def test_equipment_queues_and_inventory_follow_current_custody(self):
        from web.equipment_service import EquipmentService
        equipment = EquipmentService(self.database, self.rooms.gateway)
        for actor, faculty in ((6, self.faculty), (7, self.other_faculty)):
            equipment.assign_custodian(6, faculty, actor)
            kind = equipment.create_type(actor, faculty, 'Kits', 'Synthetic kit', 'Teaching', {}, 7, 'Faculty desk')
            equipment.add_unit(actor, kind, 'SYNTHETIC-'+str(faculty))
            equipment.submit(1, faculty, [dict(typeId=kind, quantity=1)], START, START+timedelta(days=1),
                'Equipment activity', '', uuid.uuid4().hex)
        home = self.dashboard.load(6)
        self.assertEqual(home['queues']['equipment']['count'], 1)
        self.assertEqual(home['equipmentUnits'], 1)
        self.assertEqual([row['id'] for row in home['inventories']], [self.faculty])
        equipment.assign_custodian(6, self.faculty, 7)
        home = self.dashboard.load(6)
        self.assertEqual(home['queues']['equipment']['count'], 0)
        self.assertEqual(home['equipmentUnits'], 0)

    def test_feedback_queue_and_inbox_use_existing_private_visibility(self):
        from web.feedback_service import FeedbackService
        service = FeedbackService(self.database, clock=lambda: START+timedelta(minutes=30))
        mine = self.request_room(room=301)
        foreign = self.request_room(room=302, start=START+timedelta(hours=2))
        self.rooms.decide(mine, 6, 1, True)
        self.rooms.decide(foreign, 7, 1, True)
        own_report = service.submit(1, 'room', mine, 301, 'problem', 'Synthetic issue', False, uuid.uuid4().hex)
        service.clock = lambda: START+timedelta(hours=2, minutes=30)
        service.submit(1, 'room', foreign, 302, 'problem', 'Private other faculty issue', False, uuid.uuid4().hex)
        home = self.dashboard.load(6)
        self.assertEqual([r['id'] for r in home['queues']['issues']['items']], [own_report])
        from web.notification_service import NotificationService
        self.assertEqual(home['unread'], NotificationService(self.database).inbox(6)['unreadCount'])
