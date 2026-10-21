"""Presentation-only prototype preserves authenticated, database-backed workflows."""

from datetime import timedelta
from html.parser import HTMLParser
from pathlib import Path
import re
from unittest import TestCase, mock

from flask import g, render_template_string
from sqlalchemy import func, select

from auth_fixtures import TEST_SECRET, authorized_client
from test_appointments import AppointmentFixture, START
from web import app as web_app
from web.account_service import AccountService, Principal
from web.persistence.models import Appointment


class Document(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.nodes = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.nodes.append((tag, dict(attrs)))

    def select(self, tag, **attributes):
        return [attrs for name, attrs in self.nodes if name == tag and
                all(key.replace('_', '-') in attrs and (value is None or attrs[key.replace('_', '-')] == value)
                    for key, value in attributes.items())]


class SharedShellTests(TestCase):
    def render(self, role, administrator=False, path='/appointments/'):
        with mock.patch.dict(web_app.app.config, {'SECRET_KEY': TEST_SECRET}), web_app.app.test_request_context(path):
            g.principal = Principal(1, '<script>Private name</script>', role, administrator, 1)
            return render_template_string('{% extends "base.html" %}{% block content %}<p>Existing page</p>{% endblock %}')

    def test_role_navigation_and_private_identity_remain_escaped(self):
        for role, administrator in [('Student', False), ('Instructor', False), ('Staff', False), ('Administrator', True)]:
            with self.subTest(role=role):
                html = self.render(role, administrator)
                document = Document(html)
                self.assertEqual(bool(document.select('a', href='/student/')), role == 'Student')
                self.assertEqual(bool(document.select('a', href='/appointments/availability')), role == 'Instructor')
                self.assertEqual(bool(document.select('a', href='/users')), administrator)
                self.assertIn('&lt;script&gt;Private name&lt;/script&gt;', html)
                self.assertNotIn('<script>Private name</script>', html)

    def test_request_route_has_one_active_parent_navigation_item(self):
        html = self.render('Student', path='/appointments/new')
        active = [attrs for attrs in Document(html).select('a', aria_current='page')]
        self.assertEqual([attrs['href'] for attrs in active], ['/appointments/'])

    def test_shell_has_skip_target_post_logout_and_local_assets(self):
        html = self.render('Student')
        doc = Document(html)
        self.assertTrue(doc.select('a', href='#main-content'))
        self.assertTrue(doc.select('main', id='main-content', tabindex='-1'))
        self.assertTrue(doc.select('form', method='post', action='/logout'))
        self.assertTrue(doc.select('input', name='csrf_token'))
        self.assertTrue(doc.select('button', aria_controls='app-sidebar'))
        self.assertTrue(doc.select('link', rel='icon', href='/static/favicon.svg'))
        self.assertTrue(doc.select('details', **{'data-account-menu': None}))
        assets = [node['src'] for node in doc.select('script') if 'src' in node]
        assets += [node['href'] for node in doc.select('link', rel='stylesheet')]
        self.assertTrue(all(path.startswith('/static/') for path in assets))
        self.assertTrue(all(node.get('aria-hidden') == 'true' for node in doc.select('svg')))

    def test_ui_components_escape_data_and_preserve_accessible_states(self):
        with web_app.app.test_request_context('/'):
            html = render_template_string('{% from "components/ui.html" import badge, stat_card %}{{ badge(label, "warning") }}{{ stat_card(label, 0, "No requests", "/appointments/") }}', label='<img src=x>')
        self.assertNotIn('<img', html)
        self.assertIn('&lt;img src=x&gt;', html)
        self.assertIn('No requests', html)
        css = (Path(__file__).resolve().parents[1] / 'web/static/tokens.css').read_text()
        tokens = dict(re.findall(r'--(ui-[\w-]+):\s*(#[\da-fA-F]+)', css))
        def luminance(value):
            value = value.lstrip('#')
            if len(value) == 3:
                value = ''.join(character * 2 for character in value)
            rgb = [int(value[index:index + 2], 16) / 255 for index in (0, 2, 4)]
            rgb = [level / 12.92 if level <= .04045 else ((level + .055) / 1.055) ** 2.4 for level in rgb]
            return sum(level * weight for level, weight in zip(rgb, (.2126, .7152, .0722)))
        pairs = [('ui-ink', 'ui-surface', 4.5), ('ui-muted', 'ui-surface', 4.5),
                 ('ui-surface', 'ui-primary', 4.5), ('ui-success', 'ui-success-soft', 4.5),
                 ('ui-warning', 'ui-warning-soft', 4.5), ('ui-danger', 'ui-danger-soft', 4.5),
                 ('ui-control-line', 'ui-surface', 3)]
        for foreground, background, minimum in pairs:
            with self.subTest(foreground=foreground):
                low, high = sorted((luminance(tokens[foreground]), luminance(tokens[background])))
                self.assertGreaterEqual((high + .05) / (low + .05), minimum)


class FrontendPrototypeWorkflowTests(AppointmentFixture):
    def setUp(self):
        super().setUp()
        self.configure_web()
        accounts = AccountService(self.database)
        accounts.provision(1, 'prototype-student', 'isolated-fixture-password-123', reset=True, administrator=False)
        accounts.provision(2, 'prototype-professor', 'isolated-fixture-password-123')
        accounts.provision(4, 'prototype-peer', 'isolated-fixture-password-123')
        self.client = authorized_client(web_app.app, 1, 2)

    def test_dashboard_uses_real_counts_and_preserves_timetable_and_private_links(self):
        appointment = self.submit()
        self.service.submit(4, [3], [], 'Private peer appointment', 30, START + timedelta(hours=1), self.faculty)
        response = self.client.get('/student/?week=2030-01-07')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('ui-stat-value">1</strong>', html)
        self.assertIn(f'href="/appointments/{appointment}"', html)
        self.assertNotIn('Private peer appointment', html)
        self.assertIn('Monday to Friday hourly timetable', html)
        self.assertIn('name="month"', html)
        self.assertIn('id="my-timetable" open', html)
        for href in ('/appointments/new', '/rooms/new', '/equipment/catalog', '/calendar/'):
            self.assertTrue(Document(html).select('a', href=href))

    def test_form_preserves_contract_validation_and_successful_submission(self):
        response = self.client.get('/appointments/new')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        doc = Document(html)
        self.assertTrue(doc.select('form', id='appointment-form', method='post'))
        for name in ('csrf_token', 'facultyId', 'professorIds', 'invitedIds', 'purpose', 'duration', 'appointmentDate', 'start'):
            self.assertTrue(any(node.get('name') == name for _, node in doc.nodes), name)
        self.assertTrue(doc.select('div', id='appointment-validation', role='alert'))
        self.assertTrue(doc.select('p', id='times-message', role='status'))
        self.assertTrue(doc.select('button', id='submit-appointment'))
        self.assertIn('disabled', doc.select('button', id='submit-appointment')[0])
        fields = {'facultyId': self.faculty, 'professorIds': '2', 'invitedIds': '4', 'purpose': 'Prototype workflow',
                  'duration': '30', 'appointmentDate': '2030-01-07', 'start': '2030-01-07T10:00'}
        self.assertEqual(self.client.client.post('/appointments/new', data=fields).status_code, 400)
        saved = self.client.post('/appointments/new', data=fields)
        self.assertEqual(saved.status_code, 302)
        self.assertEqual(self.client.get(saved.location).status_code, 200)
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Appointment)), 1)
            row = session.scalar(select(Appointment))
            self.assertEqual(row.status, 'Pending Approval')
            self.assertEqual(row.organizer_id, 1)

    def test_authorization_and_invalid_time_still_enforced_by_backend(self):
        self.assertEqual(web_app.app.test_client().get('/student/').status_code, 302)
        professor = authorized_client(web_app.app, 2)
        self.assertEqual(professor.get('/appointments/new').status_code, 403)
        self.assertEqual(self.client.get('/users').status_code, 403)
        fields = {'facultyId': self.faculty, 'professorIds': '2', 'purpose': 'Invalid outside hours', 'duration': '30',
                  'appointmentDate': '2030-01-07', 'start': '2030-01-07T02:00'}
        self.assertEqual(self.client.post('/appointments/new', data=fields).status_code, 409)
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Appointment)), 0)

    def test_available_time_feedback_uses_existing_engine_and_safe_empty_state(self):
        response = self.client.post('/appointments/times', data={'facultyId': self.faculty, 'professorIds': '2',
                    'appointmentDate': '2030-01-07', 'duration': '30'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['items'])
        empty = self.client.post('/appointments/times', data={'facultyId': self.faculty, 'professorIds': '2',
                    'appointmentDate': '2030-01-08', 'duration': '30'})
        self.assertEqual(empty.status_code, 200)
        self.assertFalse(empty.json['items'])
        self.assertTrue(empty.json['reason'])
