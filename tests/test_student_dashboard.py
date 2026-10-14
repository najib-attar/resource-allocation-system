"""Student home uses real PostgreSQL state, never scheduling guesses or private peers' data."""

from datetime import date, datetime, timedelta, timezone
import re
import secrets
from unittest import mock

from sqlalchemy import event, select

from auth_fixtures import authorized_client
from runtime_file_guard import forbid_runtime_files
from test_appointments import AppointmentFixture, START
from web import app as web_app
from web.account_service import AccountService
from web.calendar_service import CalendarError
from web.persistence.models import Appointment, AppointmentProfessor, BusySlot, Role, User
from web.student_dashboard_service import StudentDashboardService


class StudentDashboardTests(AppointmentFixture):
    def setUp(self):
        super().setUp()
        self.dashboard = StudentDashboardService(self.database)

    def home(self, actor=1, now=None, week=None):
        return self.dashboard.load(actor, now=now or START - timedelta(hours=1), week=week)

    def request(self, title, start=START, actor=1, professor=2, invitees=()):
        return self.service.submit(actor, [professor], list(invitees), title, 60, start, self.faculty)

    def confirm(self, title, start=START, actor=1, professor=2, invitees=()):
        pid = self.request(title, start, actor, professor, invitees)
        self.service.decide(pid, professor, 1, True)
        return pid

    def test_empty_home_is_read_only_and_does_not_invoke_engine_or_runtime_files(self):
        with forbid_runtime_files(), mock.patch('web.engine_gateway.EngineGateway.execute_appointment',
                side_effect=AssertionError('Dashboard must not execute the engine')):
            home = self.home()
        self.assertEqual(home['profile']['name'], 'Student Mira')
        self.assertEqual(home['counts'], {'bookings': 0, 'pending': 0, 'invitations': 0})
        self.assertIsNone(home['nextMeeting'])
        self.assertEqual(len(home['days']), 5)
        self.assertFalse(home['calendarUnresolved'])
        self.assertTrue(all(not day['entries'] for day in home['days']))

    def test_summaries_exclude_past_cancelled_declined_and_other_students(self):
        future = START + timedelta(days=7)
        self.confirm('Past confirmed meeting')
        confirmed = self.confirm('My upcoming confirmed meeting', future)
        pending = self.request('My pending request', future + timedelta(hours=1))
        cancelled = self.request('Cancelled request', future + timedelta(hours=2))
        self.service.cancel(cancelled, 1, 1)
        rejected = self.request('Declined request', future + timedelta(hours=3))
        self.service.decide(rejected, 2, 1, False)
        self.confirm('PRIVATE unrelated meeting', future + timedelta(hours=4), actor=4, professor=3)
        home = self.home(now=future - timedelta(hours=1))
        self.assertEqual(home['counts'], {'bookings': 1, 'pending': 1, 'invitations': 0})
        self.assertEqual(home['nextMeeting']['id'], confirmed)
        self.assertEqual([row['id'] for row in home['pending']], [pending])
        self.assertEqual([row['id'] for row in home['bookings']], [confirmed])
        self.assertNotIn('PRIVATE', str(home))
        self.assertEqual([row['appointmentId'] for day in home['days'] for row in day['entries']], [confirmed])

    def test_optional_invitation_is_visible_but_never_counted_as_my_reservation(self):
        pid = self.request('Optional invitation', actor=4, professor=3, invitees=(1,))
        self.assertEqual(self.home()['counts']['invitations'], 1)
        self.assertIsNone(self.home()['nextMeeting'])
        self.service.decide(pid, 3, 1, True)
        home = self.home()
        self.assertEqual(home['counts'], {'bookings': 0, 'pending': 0, 'invitations': 1})
        self.assertFalse(home['nextMeeting']['organizedByMe'])
        self.assertEqual(home['days'][0]['entries'][0]['kind'], 'Optional invitation')
        self.service.decline_invitation(pid, 1)
        home = self.home()
        self.assertEqual(home['counts']['invitations'], 0)
        self.assertIsNone(home['nextMeeting'])
        self.assertFalse(home['days'][0]['entries'])
        self.assertEqual(self.service.detail(pid, 4)['status'], 'Confirmed')

    def test_cancelled_or_professor_declined_invitations_are_not_open_actions(self):
        cancelled = self.request('Cancelled invitation', actor=4, professor=3, invitees=(1,))
        self.service.cancel(cancelled, 4, 1)
        declined = self.request('Professor declined invitation', actor=4, professor=3, invitees=(1,))
        self.service.decide(declined, 3, 1, False)
        self.assertEqual(self.home()['counts']['invitations'], 0)
        self.assertFalse(self.home()['invitations'])

    def test_ongoing_meeting_and_exact_end_boundary_use_half_open_intervals(self):
        self.confirm('Boundary meeting')
        home = self.home(now=START + timedelta(minutes=30))
        self.assertTrue(home['nextMeeting']['inProgress'])
        home = self.home(now=START + timedelta(hours=1))
        self.assertIsNone(home['nextMeeting'])
        self.assertEqual(home['counts']['bookings'], 0)

    def test_expired_pending_request_remains_actionable_without_reserving_time(self):
        pid = self.request('Expired pending request')
        home = self.home(now=START + timedelta(days=7))
        self.assertEqual(home['counts']['pending'], 1)
        self.assertTrue(home['pending'][0]['expired'])
        self.assertEqual(home['pending'][0]['id'], pid)
        self.assertFalse(home['bookings'])
        self.assertTrue(all(not day['entries'] for day in home['days']))

    def test_calendar_uses_explicit_bindings_own_blocks_and_university_timezone(self):
        with self.database.transaction() as session:
            busy = BusySlot(user_id=1, source_order=1, day=1, start_minutes=600, end_minutes=660, reason='Private class title')
            session.add(busy)
            session.flush()
            busy_id = busy.id
        self.assertTrue(self.home()['calendarUnresolved'])
        self.service.bind_legacy('Explicit fictional term', date(2030, 1, 1), date(2030, 1, 31), busy_id=busy_id)
        self.service.block(1, START + timedelta(hours=3), START + timedelta(hours=4), 'My private block')
        self.service.block(4, START, START + timedelta(hours=1), 'PRIVATE other student block')
        home = self.home()
        self.assertFalse(home['calendarUnresolved'])
        entries = home['days'][0]['entries']
        self.assertEqual([row['kind'] for row in entries], ['University', 'Personal block'])
        self.assertEqual(entries[0]['start'].hour, 10)
        self.assertEqual(entries[0]['title'], 'Private class title')
        self.assertNotIn('PRIVATE other student', str(home))
        self.assertIn('My private block', str(home))
        self.assertEqual(self.home(now=datetime(2030, 1, 13, 22, tzinfo=timezone.utc))['weekStart'], date(2030, 1, 14))

    def test_all_sections_pin_one_snapshot_during_concurrent_cancellation(self):
        pid = self.confirm('Snapshot meeting')
        fired = []
        def cancel_after_read(connection, cursor, statement, parameters, context, executemany):
            if not fired and 'FROM appointment LEFT OUTER JOIN appointment_invitation' in ' '.join(statement.split()):
                fired.append(True)
                self.service.cancel(pid, 1, 1)
        event.listen(self.database.engine, 'after_cursor_execute', cancel_after_read)
        try:
            home = self.home()
        finally:
            event.remove(self.database.engine, 'after_cursor_execute', cancel_after_read)
        self.assertTrue(fired)
        self.assertEqual(home['counts']['bookings'], 1)
        self.assertEqual(home['nextMeeting']['id'], pid)
        self.assertEqual(home['bookings'][0]['id'], pid)
        self.assertEqual(home['days'][0]['entries'][0]['appointmentId'], pid)
        self.assertEqual(self.home()['counts']['bookings'], 0)

    def test_card_lists_are_bounded_without_losing_totals_or_n_plus_one_queries(self):
        with self.database.transaction() as session:
            rows = [Appointment(organizer_id=1, purpose=f'Pending fixture {index}', duration_minutes=60,
                                start_at=START, end_at=START + timedelta(hours=1)) for index in range(12)]
            session.add_all(rows)
            session.flush()
            session.add_all(AppointmentProfessor(appointment_id=row.id, user_id=2, revision=1) for row in rows)
        statements = []
        def record(connection, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        event.listen(self.database.engine, 'before_cursor_execute', record)
        try:
            home = self.home()
        finally:
            event.remove(self.database.engine, 'before_cursor_execute', record)
        self.assertEqual(home['counts']['pending'], 12)
        self.assertEqual(len(home['pending']), 4)
        self.assertLessEqual(len(statements), 24)
        self.assertEqual(self.database.engine.pool.checkedout(), 0)


class StudentDashboardWebTests(AppointmentFixture):
    def setUp(self):
        super().setUp()
        self.configure_web()
        self.password = secrets.token_urlsafe(24)
        accounts = AccountService(self.database)
        accounts.provision(1, 'student-one', self.password, reset=True, administrator=False)
        accounts.provision(2, 'professor-one', self.password)
        accounts.provision(4, 'student-four', self.password)
        with self.database.transaction() as session:
            session.get(User, 6).primary_role_id = session.scalar(select(Role.id).where(Role.name == 'Administrator'))
        accounts.provision(6, 'admin-one', self.password, administrator=True)
        self.client = authorized_client(web_app.app, 1, 2)

    def login(self, username, next_path=''):
        client = web_app.app.test_client()
        page = client.get('/login').get_data(as_text=True)
        token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
        response = client.post('/login' + next_path, data={'username': username, 'password': self.password, 'csrf_token': token})
        return client, response

    def test_login_and_root_choose_student_home_without_changing_other_roles(self):
        for username, location in (('student-one', '/student/'), ('professor-one', '/appointments/'), ('admin-one', '/')):
            client, response = self.login(username)
            self.assertEqual(response.location, location)
            self.assertEqual(client.get(location).status_code, 200)
        self.assertEqual(self.client.get('/').location, '/student/')
        client, response = self.login('student-one', '?next=//external.invalid')
        self.assertEqual(response.location, '/student/')
        client, response = self.login('student-one', '?next=/appointments/new')
        self.assertEqual(response.location, '/appointments/new')

    def test_student_scope_is_enforced_and_actor_query_parameters_cannot_override_identity(self):
        self.assertEqual(web_app.app.test_client().get('/student/').status_code, 302)
        for actor in (2, 6):
            self.assertEqual(authorized_client(web_app.app, actor).get('/student/').status_code, 403)
            with self.assertRaises(PermissionError):
                StudentDashboardService(self.database).load(actor)
        self.service.submit(4, [3], [], 'PRIVATE other student request', 60, START)
        with forbid_runtime_files():
            response = self.client.get('/student/?actor=4&week=2030-01-07')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b'PRIVATE other student', response.data)
        self.assertIn(b'Student Home', response.data)
        self.assertIn(b'Schedule an appointment', response.data)
        self.assertNotIn(b'/raw-data', response.data)

    def test_bad_week_and_escaped_content_fail_safely_without_fake_services(self):
        for value in ('invalid', '9999-12-31', '2030-02-30'):
            self.assertEqual(self.client.get('/student/', query_string={'week': value}).status_code, 400)
            with self.assertRaises(CalendarError):
                StudentDashboardService(self.database).load(1, week=value)
        self.service.submit(1, [2], [], '<script>alert("private")</script>', 60, START)
        response = self.client.get('/student/?week=2030-01-07')
        self.assertIn(b'&lt;script&gt;', response.data)
        self.assertNotIn(b'<script>alert', response.data)
        self.assertNotIn(b'href="/student-card', response.data)
        self.assertIn(b'Pending requests do not reserve time', response.data)

    def test_cancellation_and_rescheduling_update_home_counts_and_private_detail_links(self):
        pid = self.submit()
        path = f'/appointments/{pid}'
        home = self.client.get('/student/?week=2030-01-07')
        self.assertIn(path.encode(), home.data)
        self.assertEqual(self.client.get(path).status_code, 200)
        professor = authorized_client(web_app.app, 2)
        self.assertEqual(professor.post(path + '/decision', data={'revision': 1, 'decision': 'approve'}).status_code, 302)
        self.assertIn(b'Open meeting details', self.client.get('/student/').data)
        self.assertEqual(self.client.post(path + '/reschedule', data={'revision': 1, 'start': '2030-01-07T11:00'}).status_code, 302)
        home = StudentDashboardService(self.database).load(1, now=START - timedelta(hours=1))
        self.assertEqual(home['counts']['bookings'], 0)
        self.assertEqual(home['counts']['pending'], 1)
        self.assertEqual(self.client.post(path + '/cancel', data={'revision': 2}).status_code, 302)
        self.assertEqual(StudentDashboardService(self.database).load(1)['counts']['pending'], 0)
        self.assertEqual(authorized_client(web_app.app, 4).get(path).status_code, 403)

    def test_database_failure_has_no_file_fallback_or_sensitive_error_details(self):
        with mock.patch.dict(web_app.app.config, {'DATABASE_URL': 'postgresql+psycopg://wrong:private-password@127.0.0.1:1/missing'}), forbid_runtime_files():
            response = self.client.get('/student/')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(b'private-password', response.data)
        self.assertNotIn(b'wrong', response.data)
