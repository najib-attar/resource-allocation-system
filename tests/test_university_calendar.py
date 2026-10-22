"""Real PostgreSQL/engine calendar projections and server-side privacy boundaries."""
from datetime import date, datetime, timedelta, timezone
from unittest import TestCase, mock

from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError

from auth_fixtures import authorized_client
from postgres_fixtures import ROOT
from runtime_file_guard import forbid_runtime_files
from test_appointments import START
from test_room_requests import RoomFixture
from web import app as web_app
from web.account_service import AccountService
from web.allocation_workflow import execute_allocation
from web.calendar_service import CalendarError
from web.engine_gateway import EngineGateway
from web.equipment_service import EquipmentService
from web.persistence.models import (Appointment, BusySlot, EquipmentReservation,
    LoginAccount, RequestHistory, Resource, ResourceRequest, RoomInvitation)
from web.persistence.repository import Repository
from web.university_calendar import UniversityCalendarService, selection


class UnifiedCalendarSelectionTests(TestCase):
    def test_timezone_month_week_day_and_navigation(self):
        now = datetime(2030, 1, 31, 22, tzinfo=timezone.utc)
        self.assertEqual(selection(now=now)['date'], date(2030, 2, 1))
        month = selection('month', '2032-02-29', now)
        self.assertIn(date(2032, 2, 29), month['dates'])
        self.assertEqual(month['previous'], date(2032, 1, 29))
        self.assertEqual(month['next'], date(2032, 3, 29))
        self.assertEqual(selection('month', '2030-01-31')['next'], date(2030, 2, 28))
        self.assertEqual(selection('week', '2030-01-09')['dates'][0], date(2030, 1, 7))
        self.assertEqual(len(selection('week', '2030-01-09')['dates']), 7)
        self.assertEqual(len(selection('day', '2030-01-09')['dates']), 1)

    def test_invalid_input_and_boundary_padding(self):
        for view, day in [('bad', '2030-01-07'), ('month', 'wrong'), ('day', '1969-12-31'), ('day', '2100-01-01')]:
            with self.subTest(view=view, day=day), self.assertRaises(CalendarError):
                selection(view, day)
        self.assertEqual(selection('month', '1970-01-01')['dates'][0], date(1969, 12, 29))
        self.assertIsNone(selection('day', '1970-01-01')['previous'])
        self.assertEqual(selection('month', '2099-12-01')['end'].year, 2100)


class UnifiedCalendarTests(RoomFixture):
    def setUp(self):
        super().setUp()
        AccountService(self.database).provision(5, 'calendar-other-student', 'Fictional-isolated-password')
        self.calendar = UniversityCalendarService(self.database)

    def load(self, actor=1, **kwargs):
        return self.calendar.load(actor, day='2030-01-07', now=START, **kwargs)

    def appointment(self, invited=(4,), confirmed=False):
        key = self.submit(invitees=invited)
        if confirmed:
            self.service.decide(key, 2, 1, True)
        return key

    def equipment(self):
        service = EquipmentService(self.database, EngineGateway(ROOT))
        service.assign_custodian(6, self.faculty, 6)
        kind = service.create_type(6, self.faculty, 'Boards', 'Fictional board', '', {}, 7, 'Faculty desk')
        for n in range(2):
            service.add_unit(6, kind, 'CAL-BOARD-'+str(n))
        key = service.submit(1, self.faculty, [{'typeId':kind,'quantity':2}], START, START+timedelta(days=2),
                             'Private equipment project', '', 'c'*32)
        return service, key

    def test_appointment_participants_have_access_but_admin_has_no_private_override(self):
        self.appointment()
        for actor in (1, 2, 4):
            events = self.load(actor)['events']
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]['state'], 'pending')
            self.assertIn('0/1 professors approved revision 1', events[0]['note'])
            self.assertFalse(events[0]['busy'])
        for actor in (3, 5, 6, 7):
            self.assertEqual(self.load(actor)['events'], [])

    def test_confirmation_optional_decline_reschedule_and_cancellation_follow_source(self):
        key = self.appointment(confirmed=True)
        self.assertTrue(self.load()['events'][0]['busy'])
        self.assertFalse(self.load(4)['events'][0]['busy'])
        self.service.decline_invitation(key, 4)
        self.assertEqual(self.load(4)['events'][0]['state'], 'rejected')
        self.assertEqual(self.load(4)['events'][0]['status'], 'Confirmed')
        self.service.cancel(key, 1, 1)
        event = self.load()['events'][0]
        self.assertEqual(event['state'], 'cancelled')
        self.assertFalse(event['busy'])
        self.assertFalse(self.load(states=['confirmed'])['events'])
        self.assertEqual(self.load(4, states=['cancelled'])['events'][0]['state'], 'cancelled')

    def test_pending_reschedule_moves_event_and_revises_approval_progress(self):
        key = self.appointment()
        self.service.reschedule(key, 1, 1, START+timedelta(hours=2))
        event = self.load()['events'][0]
        self.assertEqual(event['start'].hour, 12)
        self.assertIn('revision 2', event['note'])
        self.assertEqual(event['state'], 'pending')

    def test_room_organizer_invitee_and_current_faculty_reviewer_only(self):
        key = self.request_room(room=301, invitees=(2,))
        for actor in (1, 2, 6):
            self.assertEqual(self.load(actor)['events'][0]['state'], 'pending')
        for actor in (3, 4, 7):
            self.assertFalse(self.load(actor)['events'])
        self.assertFalse(self.load(6, scope='personal')['events'])
        self.rooms.decide(key, 6, 1, True)
        self.assertTrue(self.load()['events'][0]['busy'])
        self.assertFalse(self.load(2)['events'][0]['busy'])
        with self.database.transaction() as session:
            session.get(RoomInvitation, (key, 2)).status = 'Declined'
        self.assertEqual(self.load(2)['events'][0]['state'], 'rejected')
        self.rooms.cancel(key, 1, 1)
        self.assertEqual(self.load()['events'][0]['state'], 'cancelled')
        self.assertEqual(self.load(2, states=['cancelled'])['events'][0]['state'], 'cancelled')

    def test_replaced_or_disabled_reviewer_does_not_retain_calendar_scope(self):
        self.request_room(room=301)
        self.rooms.configure_approver(6, self.faculty, 7)
        self.assertFalse(self.load(6)['events'])
        self.assertFalse(self.load(7)['events'])  # Existing request is still assigned to the previous reviewer.
        self.request_room(room=301, start=START+timedelta(hours=2))
        self.assertTrue(self.load(7)['events'])
        with self.database.transaction() as session:
            session.get(LoginAccount, 7).enabled = False
        with self.assertRaises(PermissionError):
            self.load(7)

    def test_equipment_reminders_private_and_custodian_scoped_never_busy(self):
        equipment, key = self.equipment()
        for actor in (1, 6):
            events = self.load(actor)['events']
            self.assertEqual(len(events), 2)
            self.assertTrue(all(e['reminder'] and not e['busy'] and e['state'] == 'pending' for e in events))
        for actor in (2, 4, 7):
            self.assertFalse(self.load(actor)['events'])
        self.assertFalse(self.load(6, scope='personal')['events'])
        equipment.decide(6, key, True)
        self.assertTrue(all(e['state'] == 'confirmed' for e in self.load()['events']))
        with self.database.transaction() as session:
            session.get(LoginAccount, 6).enabled = False
        self.assertFalse(self.load()['events'][0]['busy'])

    def test_recorded_handover_partial_return_and_overdue_follow_physical_records(self):
        equipment, key = self.equipment()
        equipment.decide(6, key, True)
        with mock.patch('web.equipment_service.datetime') as clock:
            clock.now.return_value = START+timedelta(hours=1, seconds=17)
            equipment.handover(6, key, 'Inspected')
        with self.database.transaction(read_only=True) as session:
            unit = session.scalar(select(EquipmentReservation.unit_id))
        with mock.patch('web.equipment_service.datetime') as clock:
            clock.now.return_value = START+timedelta(hours=2, seconds=19)
            equipment.return_units(6, key, [unit], 'usable', 'Verified')
        data = self.calendar.load(1, day='2030-01-07', now=START+timedelta(days=3))
        self.assertEqual(len([e for e in data['events'] if e['id'].startswith('handover:')]), 2)
        self.assertEqual(len([e for e in data['events'] if e['id'].startswith('return:')]), 1)
        self.assertEqual(next(e for e in data['events'] if e['id'].startswith('due:'))['state'], 'overdue')
        self.assertTrue(all(not e['busy'] for e in data['events']))

    def test_unresolved_and_explicit_periods_exceptions_and_weeks(self):
        with self.database.transaction() as session:
            busy = BusySlot(user_id=1, source_order=1, day=1, start_minutes=600, end_minutes=660, reason='Algorithms laboratory')
            session.add(busy); session.flush(); key = busy.id
        self.assertTrue(self.load()['warnings'])
        self.assertFalse(self.load()['events'])
        self.service.bind_legacy('Explicit January', date(2030, 1, 7), date(2030, 1, 31), busy_id=key, exclusions=['2030-01-14'])
        data = self.load()
        self.assertEqual([e['start'].day for e in data['events']], [7, 21, 28])
        self.assertEqual(data['events'][0]['title'], 'Algorithms laboratory')
        self.assertFalse(self.calendar.load(1, view='week', day='2030-02-04')['events'])

    def test_opt_in_public_academic_details_do_not_expose_private_request_data(self):
        repo = self.academic()
        execute_allocation(repo, EngineGateway(ROOT))
        with self.database.transaction(read_only=True) as session:
            key = session.scalar(select(ResourceRequest.id))
            self.assertFalse(session.get(ResourceRequest, key).calendar_public)
        self.assertFalse(self.load(scope='published')['events'])
        with self.assertRaises(PermissionError):
            self.calendar.academic_detail(1, key, '2030-01-07')
        self.calendar.publish(6, key, True, 2)
        data = self.load(scope='published')
        self.assertEqual(len(data['events']), 1)
        self.assertIn('Professor Ada', data['events'][0]['note'])
        self.assertFalse(data['events'][0]['busy'])
        detail = self.calendar.academic_detail(1, key, '2030-01-07')
        self.assertEqual(detail['title'], 'Known university course')
        self.assertNotIn('requester', str(detail))
        self.calendar.publish(6, key, False)
        self.assertFalse(self.load(scope='published')['events'])

    def test_publication_requires_admin_and_valid_instructor_and_is_audited(self):
        self.academic()
        with self.database.transaction(read_only=True) as session:
            key = session.scalar(select(ResourceRequest.id))
        for actor in (1, 2, 7):
            with self.assertRaises(PermissionError):
                self.calendar.publish(actor, key, True)
            with self.assertRaises(PermissionError):
                self.calendar.publications(actor)
        with self.assertRaises(CalendarError):
            self.calendar.publish(6, key, True, 4)
        self.calendar.publish(6, key, True, 2)
        self.calendar.publish(6, key, True, 2)
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(RequestHistory).where(RequestHistory.kind=='calendar_publication')), 1)
        self.assertEqual(self.calendar.publications(6)['requests'][0]['instructorId'], 2)

    def test_half_open_boundaries_and_cross_midnight_local_dates(self):
        self.service.block(1, START-timedelta(hours=11), START-timedelta(hours=10), 'Previous day only')
        self.service.block(1, START+timedelta(hours=13), START+timedelta(hours=15), 'Cross midnight')
        data = self.load(view='week')
        first = data['days'][0]['entries']; second = data['days'][1]['entries']
        self.assertEqual([e['title'] for e in first], ['Cross midnight'])
        self.assertEqual([e['title'] for e in second], ['Cross midnight'])
        self.assertEqual(first[0]['start'].hour, 23)
        self.assertEqual(first[0]['end'].hour, 1)

    def test_categories_states_scopes_invalid_inputs_and_disabled_accounts(self):
        self.appointment()
        self.assertFalse(self.load(categories=[])['events'])
        self.assertFalse(self.load(states=[])['events'])
        self.assertFalse(self.load(scope='published')['events'])
        for args in ({'categories':['bad']}, {'states':['bad']}, {'categories':[{}]}, {'scope':'bad'}):
            with self.assertRaises(CalendarError): self.load(**args)
        for key in (-1, 2147483648):
            with self.assertRaises(CalendarError): self.calendar.publish(6, key, True)
            with self.assertRaises(CalendarError): self.calendar.academic_detail(1, key, '2030-01-07')
        with self.database.transaction() as session:
            session.get(LoginAccount, 1).enabled = False
        with self.assertRaises(PermissionError): self.load()

    def test_multi_room_academic_allocations_group_without_an_invented_enrollment(self):
        repo = Repository(self.database)
        with self.database.transaction() as session:
            session.add(Resource(id=304,source_order=4,type='Classroom',name='Exam Hall',capacity=32,building='Arts'))
        key = repo.save_request({'type':'Exam','requesterId':2,'spaceId':304,'participantCount':40,
            'title':'Public systems examination','purpose':'Private examination administration',
            'exam':{'courseName':'Systems','courseCode':'SYS101','examType':'Final','canSplitAcrossRooms':True},
            'slots':[{'day':1,'startMinutes':600,'endMinutes':660}]})
        repo.set_strategy('multi_room_exam_best_fit')
        execute_allocation(repo, EngineGateway(ROOT))
        self.service.bind_legacy('Exam week',date(2030,1,7),date(2030,1,13),request_id=key,week_start=date(2030,1,7))
        self.calendar.publish(6,key,True,2)
        events = self.load(scope='published')['events']
        self.assertEqual(len(events),1)
        self.assertGreaterEqual(len(events[0]['location'].split('; ')),2)
        self.assertFalse(self.load(1)['events'])
        self.assertEqual(len(self.load(2)['events']),1)
        self.assertFalse(self.calendar.load(1,view='week',day='2030-01-14',scope='published')['events'])

    def test_committee_cannot_be_published_even_by_direct_database_write(self):
        repo = Repository(self.database)
        key = repo.save_request({'type':'CommitteeMeeting','requesterId':2,'spaceId':301,'participantCount':1,
            'title':'Private committee','purpose':'Private business',
            'participants':[{'userId':2,'role':'Chair'}],
            'slots':[{'day':1,'startMinutes':600,'endMinutes':660}]})
        with self.assertRaises(CalendarError): self.calendar.publish(6,key,True)
        with self.assertRaises(IntegrityError), self.database.transaction() as session:
            session.get(ResourceRequest,key).calendar_public=True

    def test_calendar_retrieval_stays_on_one_snapshot_during_concurrent_cancellation(self):
        key = self.appointment(confirmed=True)
        original = self.calendar._read
        def concurrent_change(session,*args):
            session.scalar(select(Appointment.status).where(Appointment.id==key))
            self.service.cancel(key,1,1)
            return original(session,*args)
        with mock.patch.object(self.calendar,'_read',side_effect=concurrent_change):
            self.assertEqual(self.load()['events'][0]['state'],'confirmed')
        self.assertEqual(self.load()['events'][0]['state'],'cancelled')

    def test_hourly_grid_preserves_partial_hours_and_adjacent_half_open_cells(self):
        self.service.block(1,START+timedelta(minutes=15),START+timedelta(hours=1),'Partial hour')
        values=self.load(view='day')
        cells=[row['label'] for row in values['rows'] if row['cells'][0]]
        self.assertEqual(cells,['10:00'])
        self.assertEqual(len(values['days']),1)

    def test_one_repeatable_read_snapshot_without_csv_or_result_file_dependencies(self):
        self.appointment()
        original = self.calendar._read
        def inspect_snapshot(session, *args):
            self.assertEqual(session.scalar(text('SHOW transaction_isolation')), 'repeatable read')
            self.assertEqual(session.scalar(text('SHOW transaction_read_only')), 'on')
            return original(session, *args)
        with forbid_runtime_files(), mock.patch.object(self.calendar, '_read', side_effect=inspect_snapshot):
            self.assertEqual(len(self.load()['events']), 1)

    def test_flask_all_roles_navigation_filters_privacy_csrf_and_escaping(self):
        key = self.appointment()
        with self.database.transaction() as session:
            session.get(Appointment, key).purpose = '<script>private purpose</script>'
        self.configure_web()
        for actor in (1, 2, 4, 6, 7):
            client = authorized_client(web_app.app, actor)
            for view in ('month','week','day'):
                with forbid_runtime_files():
                    response = client.get('/calendar/?view='+view+'&date=2030-01-07')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers['Cache-Control'], 'private, no-store')
                self.assertNotIn(b'<script>private purpose</script>', response.data)
                self.assertEqual(b'private purpose' in response.data, actor in (1, 2, 4))
            self.assertEqual(client.get('/calendar/?view=bad').status_code, 400)
            self.assertEqual(client.get('/calendar/?filtered=1&category=bad').status_code, 400)
            self.assertEqual(client.get('/calendar/?filtered=1').status_code, 200)
            self.assertEqual(client.get('/calendar/publications').status_code, 200 if actor==6 else 403)
        student = authorized_client(web_app.app, 1)
        self.assertEqual(student.get('/calendar/?userId=2&date=2030-01-07').status_code, 200)
        self.assertEqual(student.post('/calendar/publications',data={'id':'1','visibility':'published'}).status_code, 403)
        self.assertEqual(web_app.app.test_client().get('/calendar/').status_code, 302)
        with student.session_transaction() as session:
            session.pop('csrf',None)
        self.assertEqual(student.post('/calendar/publications').status_code, 400)

    def test_migration_columns_have_safe_defaults_and_no_duplicate_calendar_tables(self):
        self.academic()
        with self.database.transaction(read_only=True) as session:
            columns = {c['name'] for c in inspect(session.connection()).get_columns('resource_request')}
            self.assertTrue({'calendar_public','academic_instructor_id'} <= columns)
            row = session.scalar(select(ResourceRequest))
            self.assertFalse(row.calendar_public)
            self.assertIsNone(row.academic_instructor_id)
            self.assertEqual(session.scalar(text('SELECT version_num FROM alembic_version')), '0049b')
        with self.assertRaises(IntegrityError), self.database.transaction() as session:
            session.scalar(select(ResourceRequest)).academic_instructor_id = 999999
