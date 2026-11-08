"""Student UI contracts using authorized read-model shapes, without a database.

Database scoping and workflow authorization remain covered by the student
dashboard, appointments, room, equipment, feedback and notification suites.
"""

from datetime import datetime, timedelta
from html.parser import HTMLParser
from types import SimpleNamespace
from unittest import TestCase, mock
from zoneinfo import ZoneInfo

from flask import g, render_template

from web import app as web_app


class Element:
    def __init__(self, tag, attrs=(), parent=None):
        self.tag, self.attrs, self.parent = tag, dict(attrs), parent
        self.children = []
        self.parts = []

    @property
    def text(self):
        return ' '.join(' '.join(self.parts).split())

    def find(self, tag=None, **attrs):
        found = []
        for child in self.children:
            if (tag is None or child.tag == tag) and all(child.attrs.get(k) == v for k, v in attrs.items()):
                found.append(child)
            found.extend(child.find(tag, **attrs))
        return found


class Document(HTMLParser):
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}

    def __init__(self, source):
        super().__init__()
        self.root = Element('document')
        self.current = self.root
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        node = Element(tag, attrs, self.current)
        self.current.children.append(node)
        if tag not in self.VOID:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        node = self.current
        while node.parent is not None:
            if node.tag == tag:
                self.current = node.parent
                return
            node = node.parent

    def handle_data(self, data):
        node = self.current
        while node is not None:
            node.parts.append(data)
            node = node.parent


class StudentPortalTemplateTests(TestCase):
    def setUp(self):
        self.now = datetime(2030, 1, 7, 9, tzinfo=ZoneInfo('Europe/Istanbul'))
        days = [{'date': (self.now + timedelta(days=n)).date(), 'entries': [], 'outsideMonth': False} for n in range(5)]
        self.home = {
            'profile': {'name': 'Fictional Student'}, 'now': self.now, 'zone': 'Europe/Istanbul',
            'weekStart': days[0]['date'], 'weekEnd': days[0]['date'] + timedelta(days=6),
            'pending': [], 'bookings': [], 'invitations': [], 'roomCards': [], 'nextMeeting': None,
            'calendarUnresolved': False,
            'schedule': {'days': days, 'today': days[0]['date'], 'weekend': [], 'month': '2030-01'},
        }
        self.settings = mock.patch.dict(web_app.app.config, {'SECRET_KEY': 'isolated-template-test-key-not-for-production'})
        self.settings.start()
        self.addCleanup(self.settings.stop)

    def render(self, role='Student', administrator=False, template='student_home.html'):
        with web_app.app.test_request_context('/student/' if template == 'student_home.html' else '/appointments/'):
            g.principal = SimpleNamespace(name='Fictional Student', role=role, administrator=administrator, user_id=1)
            source = render_template(template, home=self.home, items=[], zone='Europe/Istanbul')
        return source, Document(source).root

    def appointment(self, key, purpose, status, hour=10):
        start = self.now.replace(hour=hour)
        return {'id': key, 'purpose': purpose, 'status': status, 'start': start, 'end': start + timedelta(hours=1),
                'expired': False, 'organizedByMe': True, 'inProgress': False, 'professors': ['Fictional Professor'],
                'organizerName': 'Fictional Student'}

    def test_primary_navigation_has_four_cross_service_destinations(self):
        _, page = self.render()
        links = page.find('nav', **{'aria-label': 'Main navigation'})[0].find('a')
        self.assertEqual([a.attrs['href'] for a in links], ['/student/', '/student/#my-activity', '/calendar/', '/notifications/'])
        self.assertEqual([a.attrs.get('aria-label', a.text) for a in links], ['Home', 'My Activity', 'University Calendar', 'Inbox'])
        self.assertEqual(links[0].attrs.get('aria-current'), 'page')
        self.assertEqual(len(page.find('section', id='my-activity')), 1)

    def test_five_service_hubs_link_to_existing_routes(self):
        _, page = self.render()
        services = page.find('section', **{'aria-labelledby': 'services-heading'})[0]
        destinations = [a.attrs['href'] for a in services.find('a')]
        for path in ['/appointments/', '/rooms/', '/equipment/', '/waiting-lists/', '/feedback/']:
            with self.subTest(path=path):
                self.assertEqual(destinations.count(path), 1)
        self.assertNotIn('/appointments/availability', destinations)

    def test_empty_dashboard_is_honest_and_has_no_mock_search_or_filters(self):
        source, page = self.render()
        self.assertIn('No current appointment or room requests.', page.text)
        self.assertIn('No dated entries for this week.', page.text)
        self.assertFalse(page.find('input', type='search'))
        self.assertFalse(page.find('form', role='search'))
        for node in page.find():
            self.assertNotIn('data-filter', node.attrs)
            self.assertNotIn('data-service', node.attrs)
        for fictional_prototype_text in ['2 of 3 approvals', 'Seminar room reservation', 'Lab equipment borrowing', 'Project discussion with professors']:
            self.assertNotIn(fictional_prototype_text, source)

    def test_statuses_keep_pending_optional_and_partial_reservations_distinct(self):
        self.home['pending'] = [self.appointment(11, 'Fictional pending request', 'Pending Approval')]
        self.home['bookings'] = [self.appointment(12, 'Fictional confirmed meeting', 'Confirmed', 11)]
        self.home['invitations'] = [self.appointment(13, 'Fictional optional invitation', 'Confirmed', 12)]
        self.home['roomCards'] = [self.appointment(14, 'Fictional recurring room', 'Partially Confirmed', 13)]
        _, page = self.render()
        activity = page.find('section', id='my-activity')[0]
        articles = activity.find('article')
        self.assertEqual(len(articles), 4)
        self.assertIn('Pending Approval', articles[0].text)
        self.assertIn('My confirmed booking', articles[1].text)
        self.assertIn('Optional invitation', articles[2].text)
        self.assertIn('Attendance optional', articles[2].text)
        self.assertIn('Partially Confirmed', articles[3].text)
        self.assertEqual(articles[3].find('a')[0].attrs['href'], '/rooms/14')
        self.assertIn('Pending requests do not reserve time.', activity.text)

    def test_calendar_uses_supplied_entries_once_and_includes_weekend(self):
        optional = {'title': 'Fictional invitation entry', 'kind': 'Optional invitation', 'appointmentId': 21,
                    'start': self.now.replace(hour=10), 'end': self.now.replace(hour=11)}
        weekend = {'title': 'Fictional weekend room', 'kind': 'Room booking', 'appointmentId': None, 'roomRequestId': 22,
                   'start': self.now + timedelta(days=5), 'end': self.now + timedelta(days=5, hours=1)}
        self.home['schedule']['days'][0]['entries'] = [optional]
        self.home['schedule']['days'][1]['entries'] = [optional]
        self.home['schedule']['weekend'] = [weekend]
        _, page = self.render()
        planning = page.find('section', **{'aria-labelledby': 'preview-heading'})[0]
        self.assertEqual(planning.text.count('Fictional invitation entry'), 1)
        self.assertIn('Optional invitation', planning.text)
        self.assertIn('Attendance optional', planning.text)
        self.assertIn('Fictional weekend room', planning.text)
        links = [a.attrs['href'] for a in planning.find('a')]
        self.assertIn('/appointments/21', links)
        self.assertIn('/rooms/22', links)
        self.assertIn('/calendar/?view=week&date=2030-01-07', links)
        self.assertIn('Equipment reminders appear in the University Calendar', planning.text)
        self.assertIn('they do not reserve time.', planning.text)
        self.assertNotIn('No dated entries', planning.text)

    def test_unresolved_dates_remain_a_visible_warning(self):
        self.home['calendarUnresolved'] = True
        _, page = self.render()
        warnings = page.find('p', role='status')
        self.assertTrue(any('empty cells are not proof of availability' in node.text for node in warnings))

    def test_untrusted_names_and_titles_are_escaped(self):
        self.home['profile']['name'] = '<script>profile()</script>'
        self.home['pending'] = [self.appointment(31, '<img src=x onerror=alert(1)>', 'Pending Approval')]
        source, page = self.render()
        self.assertIn('&lt;img src=x onerror=alert(1)&gt;', source)
        self.assertIn('&lt;script&gt;profile()&lt;/script&gt;', source)
        self.assertFalse(page.find('img', src='x'))

    def test_shared_account_controls_preserve_real_notifications_and_csrf_logout(self):
        _, page = self.render()
        forms = page.find('form', action='/logout')
        self.assertEqual(len(forms), 1)
        self.assertEqual(forms[0].attrs['method'], 'post')
        self.assertTrue(forms[0].find('input', name='csrf_token')[0].attrs['value'])
        control = next(node for node in page.find('div') if 'data-notifications' in node.attrs)
        self.assertEqual(control.attrs['data-feed-url'], '/notifications/feed')
        self.assertEqual(control.attrs['data-read-url'], '/notifications/read')
        self.assertTrue(control.attrs['data-csrf'])

    def test_home_has_one_primary_heading_for_student_and_student_administrator(self):
        for administrator in (False, True):
            with self.subTest(administrator=administrator):
                _, page = self.render(administrator=administrator)
                self.assertEqual(len(page.find('h1')), 1)

    def test_professor_staff_and_administrator_use_their_role_shell(self):
        for role, administrator in [('Instructor', False), ('TeachingAssistant', False), ('Staff', False), ('Administrator', True), ('Student', True)]:
            with self.subTest(role=role, administrator=administrator):
                _, page = self.render(role, administrator, template='appointments.html')
                sheets = [node.attrs['href'] for node in page.find('link', rel='stylesheet')]
                self.assertEqual('/static/campus-shell.css' in sheets,role == 'Instructor' or administrator)
                self.assertNotIn('/static/campus-home.css', sheets)
                navigation = page.find('nav', **{'aria-label': 'Main navigation'})[0]
                self.assertIn('/administration/' if administrator else '/professor/' if role == 'Instructor' else '/appointments/', [a.attrs['href'] for a in navigation.find('a')])
                self.assertNotIn('/student/#my-activity', [a.attrs['href'] for a in navigation.find('a')])
                if role == 'Instructor':
                    self.assertIn('/professor/', [a.attrs['href'] for a in navigation.find('a')])
                if administrator:
                    self.assertIn('Administration', navigation.text)


class LoginTemplateTests(TestCase):
    def render(self, error=None, username=''):
        with mock.patch.dict(web_app.app.config, {'SECRET_KEY':'isolated-login-template-test-key-2030'}), \
                web_app.app.test_request_context('/login', method='POST', data={'username': username}):
            return render_template('login.html', error=error)

    def test_login_preserves_fields_csrf_autocomplete_and_no_extra_auth_features(self):
        page = Document(self.render()).root
        self.assertEqual(len(page.find('h1')), 1)
        form = page.find('form')[0]
        self.assertEqual(form.attrs['method'], 'post')
        self.assertTrue(form.find('input', name='csrf_token')[0].attrs['value'])
        self.assertEqual(form.find('input', name='username')[0].attrs['autocomplete'], 'username')
        self.assertEqual(form.find('input', name='password')[0].attrs['autocomplete'], 'current-password')
        self.assertEqual(form.find('input', name='password')[0].attrs['type'], 'password')
        self.assertEqual([a.attrs['href'] for a in page.find('a')], ['#main-content'])

    def test_failed_sign_in_escapes_identity_announces_error_and_never_refills_password(self):
        source = self.render('Credentials rejected', '<script>identity()</script>')
        page = Document(source).root
        self.assertIn('&lt;script&gt;', source)
        self.assertTrue(page.find('div', role='alert'))
        self.assertNotIn('value', page.find('input', name='password')[0].attrs)
        for name in ('username', 'password'):
            self.assertEqual(page.find('input', name=name)[0].attrs['aria-describedby'], 'sign-in-error')


class EquipmentControlTests(TestCase):
    def render(self, mode):
        with mock.patch.dict(web_app.app.config, {'SECRET_KEY':'isolated-equipment-ui-template-test-key'}), \
                web_app.app.test_request_context('/equipment/catalog', method='POST', data={'reservationMode':mode}):
            g.principal = SimpleNamespace(name='Fictional Student', role='Student', administrator=False, user_id=1)
            return Document(render_template('equipment_catalog.html', items=[],
                directory={'faculties':[], 'periods':[]}, result=None, preview_token=None,
                waiting_policy={'version':'test', 'noticeMinutes':60}, submission_key='a'*32,
                start='2030-01-07T10:00', due='2030-01-07T11:00', zone='Europe/Istanbul')).root

    def test_recurring_equipment_waiting_action_is_disabled_with_visible_reason(self):
        weekly = self.render('weekly')
        self.assertIn('disabled', weekly.find('button', value='wait')[0].attrs)
        self.assertEqual(weekly.find('button', value='wait')[0].attrs['aria-describedby'],'equipment-waiting-reason')
        self.assertNotIn('hidden', weekly.find('p', id='equipment-waiting-reason')[0].attrs)
        once = self.render('once')
        self.assertNotIn('disabled', once.find('button', value='wait')[0].attrs)
        self.assertNotIn('aria-describedby', once.find('button', value='wait')[0].attrs)
        self.assertIn('hidden', once.find('p', id='equipment-waiting-reason')[0].attrs)

    def test_equipment_actions_have_explicit_canonical_destinations(self):
        page = self.render('once')
        self.assertEqual(page.find('form', id='equipment-borrow-form')[0].attrs['action'], '/equipment/catalog')
        self.assertEqual(page.find('form', method='get')[0].attrs['action'], '/equipment/catalog')

    def test_pending_extension_has_waiting_message_instead_of_duplicate_form(self):
        now = datetime(2030, 1, 7, 10, tzinfo=ZoneInfo('Europe/Istanbul'))
        item = dict(id=1,purpose='Fictional loan',status='Borrowed',isBorrower=True,isCustodian=False,
                    overdue=False,borrower='Fictional Student',faculty='Faculty',start=now,due=now,
                    notes='',items=[],units=[],recurrence=None,history=[],canAudit=False)
        with mock.patch.dict(web_app.app.config, {'SECRET_KEY':'isolated-equipment-ui-template-test-key'}), \
                web_app.app.test_request_context('/equipment/1'):
            g.principal = SimpleNamespace(name='Fictional Student',role='Student',administrator=False,user_id=1)
            for state in ['Pending','Approved','Rejected']:
                item['extensions'] = [dict(id=1,status=state,due=now,reason='Fictional extension')]
                page = Document(render_template('equipment_detail.html',item=item,waiting=None)).root
                self.assertEqual(len(page.find('form',action='/equipment/1/extension')),0 if state=='Pending' else 1)
                self.assertEqual("awaiting the custodian's decision" in page.text,state=='Pending')


class StudentFailurePresentationTests(TestCase):
    def context(self, role='Student'):
        self.settings = mock.patch.dict(web_app.app.config, {'SECRET_KEY':'isolated-failure-template-test-key-2030'})
        self.settings.start()
        self.addCleanup(self.settings.stop)
        context = web_app.app.test_request_context('/equipment/catalog')
        context.push()
        self.addCleanup(context.pop)
        g.principal = SimpleNamespace(name='Fictional Student', role=role, administrator=False, user_id=1)

    def test_student_service_failure_retains_503_and_hides_internal_details(self):
        self.context()
        with self.assertLogs(web_app.app.logger):
            body, status, headers = web_app.application_error(web_app.EngineIntegrationError('PRIVATE internal path'))
        self.assertEqual(status, 503)
        self.assertNotIn('PRIVATE', body)
        self.assertIn('role="alert"', body)
        self.assertIn('Back to equipment requests', body)
        self.assertEqual(headers['Cache-Control'], 'private, no-store')

    def test_busy_error_retains_retry_after_and_other_roles_keep_their_response(self):
        self.context()
        _, status, headers = web_app.database_busy(web_app.DatabaseBusy('busy'))
        self.assertEqual((status, headers['Retry-After']), (503, '2'))
        g.principal.role = 'Staff'
        self.assertEqual(web_app.database_busy(web_app.DatabaseBusy('busy')), ('busy', 503, {'Retry-After':'2'}))

    def test_http_failure_preserves_method_headers_and_escapes_descriptions(self):
        from werkzeug.exceptions import MethodNotAllowed
        self.context()
        response = web_app.workspace_http_error(MethodNotAllowed(valid_methods=['GET'], description='<script>bad()</script>'))
        self.assertEqual(response.status_code, 405)
        self.assertIn('GET', response.headers['Allow'])
        self.assertIn('&lt;script&gt;', response.get_data(as_text=True))
        self.assertNotIn('<script>bad()', response.get_data(as_text=True))

    def test_submission_conflict_retains_409_and_safe_message(self):
        self.context()
        body, status, _ = web_app.submission_conflict(web_app.SubmissionConflict('Refresh this request.'))
        self.assertEqual(status, 409)
        self.assertIn('Refresh this request.', body)
