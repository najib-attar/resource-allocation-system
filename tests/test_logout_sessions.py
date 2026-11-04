"""Logout must reject replayed cookies without ending another browser's login."""

import re
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from sqlalchemy import func, select

from auth_fixtures import authorized_client
from test_professor_services import ProfessorFixture
from web import app as web_app
from web.account_service import AccountService
from web.persistence.models import CalendarBlock, LoggedOutSession, LoginAccount, Role, User


class LogoutSessionTests(ProfessorFixture):
    def setUp(self):
        super().setUp()
        self.password = 'Synthetic-logout-regression-password'
        AccountService(self.database).provision(2, 'logout-regression', self.password, reset=True)

    def login(self):
        client = web_app.app.test_client()
        response = client.get('/login')
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', response.get_data(as_text=True))[1]
        self.assertEqual(client.post('/login', data=dict(username='logout-regression',
            password=self.password, csrf_token=csrf)).status_code, 302)
        with client.session_transaction() as session:
            token = session['csrf']
        return client, token

    def test_copied_authenticated_cookie_cannot_be_replayed_after_logout(self):
        client, csrf = self.login()
        copied_cookie = client.get_cookie(web_app.app.config['SESSION_COOKIE_NAME']).value
        self.assertEqual(client.post('/logout', data={'csrf_token': csrf}).status_code, 302)
        # A late response can put the original signed cookie back into the browser.
        client.set_cookie(web_app.app.config['SESSION_COOKIE_NAME'], copied_cookie)
        self.assertEqual(client.get('/appointments/').status_code, 302)

    def test_logout_preserves_an_independent_login_and_new_login(self):
        first, csrf = self.login()
        second, _ = self.login()
        self.assertEqual(first.post('/logout', data={'csrf_token': csrf}).status_code, 302)
        self.assertEqual(second.get('/professor/').status_code, 200)
        third, _ = self.login()
        self.assertEqual(third.get('/professor/').status_code, 200)

    def test_logout_persists_only_a_digest_and_does_not_change_account_version(self):
        client, csrf = self.login()
        with client.session_transaction() as login:
            version = login['session_version']
        self.assertEqual(client.post('/logout', data={'csrf_token': csrf}).status_code, 302)
        with self.database.transaction(read_only=True) as session:
            denial = session.scalar(select(LoggedOutSession))
            self.assertEqual((denial.user_id, denial.session_version), (2, version))
            self.assertEqual(len(denial.token_digest), 64)
            self.assertNotEqual(denial.token_digest, csrf)
            self.assertIsNotNone(denial.logged_out_at)
            self.assertEqual(session.get(LoginAccount, 2).session_version, version)
        self.assertIsNone(AccountService(self.database).identity(2, version, session_token=csrf))

    def test_invalid_csrf_cannot_log_out_or_create_denial(self):
        client, _ = self.login()
        self.assertEqual(client.post('/logout', data={'csrf_token': 'wrong'}).status_code, 400)
        self.assertEqual(client.get('/appointments/').status_code, 200)
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(LoggedOutSession)), 0)

    def test_replayed_cookie_cannot_mutate_private_calendar(self):
        client, csrf = self.login()
        cookie = client.get_cookie(web_app.app.config['SESSION_COOKIE_NAME']).value
        self.assertEqual(client.post('/logout', data={'csrf_token': csrf}).status_code, 302)
        client.set_cookie(web_app.app.config['SESSION_COOKIE_NAME'], cookie)
        response = client.post('/appointments/calendar', data=dict(csrf_token=csrf, action='block',
            start='2030-01-07T10:00', end='2030-01-07T11:00', reason='Must never be saved'))
        self.assertIn(response.status_code, (302, 400))
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(CalendarBlock)), 0)

    def test_all_five_roles_reject_replayed_session_without_affecting_other_users(self):
        with self.database.transaction() as session:
            role = session.scalar(select(Role.id).where(Role.name == 'TeachingAssistant'))
            session.add(User(id=9, source_order=9, name='Synthetic logout TA', primary_role_id=role))
        AccountService(self.database).provision(9, 'logout-ta', self.password)
        peer = authorized_client(web_app.app, 3)
        for actor in (1, 2, 9, 7, 6):
            with self.subTest(actor=actor):
                with self.database.transaction(read_only=True) as session:
                    version = session.get(LoginAccount, actor).session_version
                client = authorized_client(web_app.app, actor, version)
                cookie = client.get_cookie(web_app.app.config['SESSION_COOKIE_NAME']).value
                self.assertEqual(client.post('/logout').status_code, 302)
                client.set_cookie(web_app.app.config['SESSION_COOKIE_NAME'], cookie)
                self.assertEqual(client.get('/appointments/').status_code, 302)
                self.assertEqual(peer.get('/appointments/').status_code, 200)

    def test_concurrent_duplicate_logout_is_idempotent_and_independent_of_service_instance(self):
        client, csrf = self.login()
        with client.session_transaction() as login:
            version = login['session_version']
        def revoke(_):
            AccountService(self.database).revoke_session(2, version, csrf)
        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(revoke, range(2)))
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(LoggedOutSession)), 1)
        self.assertEqual(client.get('/appointments/').status_code, 302)

    def test_database_failure_does_not_report_successful_logout(self):
        client, _ = self.login()
        from web.persistence.database import DatabaseBusy
        with mock.patch.object(AccountService, 'revoke_session', side_effect=DatabaseBusy('Retry shortly.')):
            self.assertEqual(client.post('/logout', headers={'X-CSRF-Token': self._csrf(client)}).status_code, 503)
        self.assertEqual(client.get('/appointments/').status_code, 200)

    @staticmethod
    def _csrf(client):
        with client.session_transaction() as login:
            return login['csrf']

    def test_authenticated_cookie_without_nonce_is_rejected(self):
        client, _ = self.login()
        with client.session_transaction() as login:
            del login['csrf']
        self.assertEqual(client.get('/appointments/').status_code, 302)

    def test_pre_fix_cookie_requires_fresh_login_without_resetting_password(self):
        client, _ = self.login()
        with client.session_transaction() as login:
            del login['login_format']
        self.assertEqual(client.get('/appointments/').status_code, 302)
        fresh, _ = self.login()
        self.assertEqual(fresh.get('/appointments/').status_code, 200)

    def test_logged_out_cookie_stays_denied_after_account_deletion_and_reprovision(self):
        client = authorized_client(web_app.app, 3)
        cookie = client.get_cookie(web_app.app.config['SESSION_COOKIE_NAME']).value
        self.assertEqual(client.post('/logout').status_code, 302)
        with self.database.transaction() as session:
            session.delete(session.get(LoginAccount, 3))
        AccountService(self.database).provision(3, 'reprovisioned-logout-peer', self.password)
        client.set_cookie(web_app.app.config['SESSION_COOKIE_NAME'], cookie)
        self.assertEqual(client.get('/appointments/').status_code, 302)

    def test_logout_records_denial_even_when_global_revocation_wins_the_account_lock(self):
        client = authorized_client(web_app.app, 3)
        cookie = client.get_cookie(web_app.app.config['SESSION_COOKIE_NAME']).value
        with client.session_transaction() as login:
            csrf = login['csrf']
        accounts = AccountService(self.database)
        accounts.revoke(3)
        accounts.revoke_session(3, 1, csrf)
        with self.database.transaction() as session:
            session.delete(session.get(LoginAccount, 3))
        accounts.provision(3, 'reprovisioned-revocation-peer', self.password)
        client.set_cookie(web_app.app.config['SESSION_COOKIE_NAME'], cookie)
        self.assertEqual(client.get('/appointments/').status_code, 302)
