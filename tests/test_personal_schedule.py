"""The timetable is a private projection, not a second booking database."""

from datetime import date, datetime, timedelta, timezone
from unittest import TestCase

from sqlalchemy import select

from auth_fixtures import authorized_client
from runtime_file_guard import forbid_runtime_files
from test_appointments import AppointmentFixture, START
from web import app as web_app
from web.account_service import AccountService
from web.calendar_service import CalendarError, legacy_intervals, local_instant
from web.personal_schedule_service import PersonalScheduleService, select_calendar
from web.persistence.models import BusySlot, Role, User
from web.presentation import person_name


class CalendarSelectionTests(TestCase):
    def test_default_month_and_week_follow_university_timezone(self):
        selected = select_calendar(now=datetime(2030, 1, 31, 22, tzinfo=timezone.utc))
        self.assertEqual(selected['month'], '2030-02')
        self.assertEqual(selected['weekStart'], date(2030, 1, 28))

    def test_month_navigation_has_every_week_and_leap_day(self):
        selected = select_calendar(month='2032-02', now=START)
        self.assertEqual(selected['monthEnd'], date(2032, 2, 29))
        self.assertEqual(selected['weekStart'], selected['weeks'][0])
        self.assertEqual(len(select_calendar('2030-12', now=START)['weeks']), 6)

    def test_legacy_week_links_and_invalid_months_are_handled_explicitly(self):
        self.assertEqual(select_calendar(week='2030-01-14', now=START)['month'], '2030-01')
        for month, week in [('wrong', None), ('2030-13', None), ('9999-01', None), ('2030-01', '2030-03-07'), ('2030-01', 'invalid')]:
            with self.subTest(month=month, week=week), self.assertRaises(CalendarError):
                select_calendar(month, week, START)

    def test_only_known_demo_suffixes_are_hidden_without_changing_real_names(self):
        self.assertEqual(person_name('Demo Mira Vale 0001'), 'Demo Mira Vale')
        self.assertEqual(person_name('Demo Elio Reed 12000'), 'Demo Elio Reed')
        for name in ('Professor 42', 'Mira Vale 0001', 'Demo Other Person 0001', '<script>0001</script>'):
            self.assertEqual(person_name(name), name)

    def test_boundary_month_padding_does_not_weaken_booking_date_validation(self):
        self.assertEqual(select_calendar('1970-01', now=START)['weekStart'], date(1969, 12, 29))
        self.assertEqual(select_calendar('2099-12', week='2099-12-28', now=START)['end'].year, 2100)
        with self.assertRaises(CalendarError):
            local_instant('1969-12-29T10:00')


class PersonalScheduleTests(AppointmentFixture):
    def setUp(self):
        super().setUp()
        self.schedule = PersonalScheduleService(self.database)

    def load(self, actor=1, week='2030-01-07'):
        return self.schedule.load(actor, week=week, now=START)

    def confirm(self, actor=1, professor=2, start=START, duration=60, invitees=()):
        pid = self.service.submit(actor, [professor], list(invitees), 'Known appointment', duration, start, self.faculty)
        self.service.decide(pid, professor, 1, True)
        return pid

    def test_confirmed_meetings_fill_exact_hour_cells_for_students_and_professors(self):
        pid = self.confirm(start=START + timedelta(minutes=15), duration=75)
        for actor in (1, 2):
            with forbid_runtime_files():
                schedule = self.load(actor)
            self.assertEqual(len(schedule['days']), 5)
            occupied = [row for row in schedule['rows'] if row['cells'][0]['entries']]
            self.assertEqual([row['label'] for row in occupied], ['10:00', '11:00'])
            self.assertFalse(occupied[0]['cells'][0]['entries'][0]['continues'])
            self.assertTrue(occupied[1]['cells'][0]['entries'][0]['continues'])
            self.assertEqual(occupied[0]['cells'][0]['entries'][0]['appointmentId'], pid)
            self.assertEqual(occupied[0]['cells'][0]['entries'][0]['start'].minute, 15)
        self.assertFalse(any(day['entries'] for day in self.load(week='2030-01-14')['days']))

    def test_all_user_roles_have_own_timetables_without_peer_schedule_access(self):
        self.confirm()
        with self.database.transaction() as session:
            roles = {row.name: row.id for row in session.scalars(select(Role))}
            session.get(User, 4).primary_role_id = roles['Staff']
            session.get(User, 5).primary_role_id = roles['TeachingAssistant']
            session.get(User, 6).primary_role_id = roles['Administrator']
        for actor in (3, 4, 5, 6):
            self.service.block(actor, START, START + timedelta(hours=1), f'Own block {actor}')
            entries = [item for day in self.load(actor)['days'] for item in day['entries']]
            self.assertEqual([item['title'] for item in entries], [f'Own block {actor}'])

    def test_unresolved_and_bound_university_entries_do_not_change_engine_projection(self):
        with self.database.transaction() as session:
            row = BusySlot(user_id=1, source_order=1, day=1, start_minutes=600, end_minutes=660, reason='Algorithms course')
            session.add(row)
            session.flush()
            busy_id = row.id
        self.assertTrue(self.load()['unresolved'])
        self.service.bind_legacy('Fictional term', date(2030, 1, 1), date(2030, 1, 31), busy_id=busy_id)
        self.assertEqual(self.load()['days'][0]['entries'][0]['title'], 'Algorithms course')
        selected = select_calendar(week='2030-01-07', now=START)
        with self.database.transaction(read_only=True) as session:
            values, unresolved = legacy_intervals(session, [1], selected['start'], selected['end'])
        self.assertEqual(set(values[0]), {'userId', 'start', 'end'})
        self.assertFalse(unresolved)

    def test_optional_overlaps_are_visible_without_false_reservations_and_declines_hide_them(self):
        self.confirm()
        optional = self.confirm(actor=4, professor=3, invitees=(1,))
        self.assertEqual(len(self.load()['days'][0]['entries']), 2)
        self.assertEqual({row['kind'] for row in self.load()['days'][0]['entries']}, {'Appointment', 'Optional invitation'})
        self.service.decline_invitation(optional, 1)
        self.assertEqual(len(self.load()['days'][0]['entries']), 1)

    def test_weekends_early_hours_and_midnight_are_not_silently_lost(self):
        self.service.block(1, START - timedelta(hours=4), START - timedelta(hours=3), 'Early study')
        self.service.block(1, START + timedelta(hours=13, minutes=30), START + timedelta(hours=14, minutes=30), 'Night study')
        self.service.block(1, START + timedelta(days=5), START + timedelta(days=5, hours=1), 'Saturday study')
        schedule = self.load()
        self.assertEqual(schedule['rows'][0]['label'], '00:00')
        self.assertEqual(schedule['rows'][-1]['label'], '23:00')
        self.assertEqual([row['title'] for row in schedule['weekend']], ['Saturday study'])
        self.assertIn('Night study', [row['title'] for row in schedule['days'][1]['entries']])

    def test_pending_cancelled_and_declined_requests_never_occupy_the_table(self):
        self.submit()
        cancelled = self.confirm(start=START + timedelta(hours=1))
        self.service.cancel(cancelled, 1, 1)
        declined = self.submit(start=START + timedelta(hours=2))
        self.service.decide(declined, 2, 1, False)
        self.assertFalse(any(day['entries'] for day in self.load()['days']))


class AppointmentSelectionWebTests(AppointmentFixture):
    def setUp(self):
        super().setUp()
        self.client = self.configure_web()
        AccountService(self.database).provision(2, 'fixture-professor', 'Isolated-test-password-42')

    def times(self, **changes):
        values = {'facultyId': self.faculty, 'professorIds': [2], 'duration': 30, 'appointmentDate': '2030-01-07'}
        values.update(changes)
        return self.client.post('/appointments/times', data=values)

    def test_form_has_separate_compact_lists_and_only_one_date_control(self):
        with self.database.transaction() as session:
            session.get(User, 2).name = 'Demo Mira Vale 0081'
        page = self.client.get('/appointments/new')
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.data.count(b'type="date"'), 1)
        self.assertNotIn(b'type="datetime-local"', page.data)
        self.assertNotIn(b'0081', page.data)
        self.assertIn(b'value="2"', page.data)
        self.assertIn(b'Search professors', page.data)
        self.assertIn(b'Search students', page.data)
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.get(User, 2).name, 'Demo Mira Vale 0081')

    def test_single_date_returns_feasible_slots_on_that_date_including_late_slots(self):
        result = self.times()
        self.assertEqual(result.status_code, 200)
        self.assertGreater(len(result.json['items']), 20)
        self.assertTrue(all(item['localStart'].startswith('2030-01-07T') for item in result.json['items']))
        self.assertIn('2030-01-07T16:30', [item['localStart'] for item in result.json['items']])
        self.assertEqual(self.times(appointmentDate='invalid').status_code, 409)

    def test_changed_calendar_rejects_a_previously_shown_slot_and_different_date(self):
        slot = self.times().json['items'][0]['localStart']
        self.service.block(2, START - timedelta(hours=1), START, 'Now unavailable')
        form = {'facultyId': self.faculty, 'professorIds': [2], 'duration': 30, 'purpose': 'Web proposal',
                'appointmentDate': '2030-01-07', 'start': slot}
        self.assertEqual(self.client.post('/appointments/new', data=form).status_code, 409)
        form['appointmentDate'] = '2030-01-14'
        self.assertEqual(self.client.post('/appointments/new', data=form).status_code, 409)

    def test_month_views_are_private_and_work_for_professor_and_student(self):
        self.service.block(2, START, START + timedelta(hours=1), 'PRIVATE professor block')
        for client in (self.client, authorized_client(web_app.app, 2)):
            with forbid_runtime_files():
                page = client.get('/appointments/calendar?month=2030-01&week=2030-01-07&actor=2')
            self.assertEqual(page.status_code, 200)
            for day in ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'):
                self.assertIn(day.encode(), page.data)
            self.assertIn(b'10:00', page.data)
        self.assertNotIn(b'PRIVATE professor block', self.client.get('/appointments/calendar?from=2030-01-07').data)
        self.assertEqual(self.client.get('/appointments/calendar?month=bad').status_code, 409)
        self.assertEqual(self.client.get('/student/?month=bad').status_code, 400)
