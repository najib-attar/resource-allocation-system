"""Real Flask/PG administration pages preserve capability and shared workspaces."""
from unittest import mock
from sqlalchemy import select

from auth_fixtures import authorized_client
from test_room_requests import RoomFixture
from web import app as web_app
from web.persistence.models import Role, User


class AdministrationPageTests(RoomFixture):
    def setUp(self):
        super().setUp()
        self.configure_web()
        self.client = authorized_client(web_app.app, 6)

    def test_home_reads_real_queues_without_legacy_snapshot_or_engine(self):
        key = self.request_room(room=301)
        with mock.patch.object(web_app, 'current_results', side_effect=AssertionError('Unbounded legacy read')):
            response = self.client.get('/administration/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Cache-Control'], 'private, no-store')
        text = response.get_data(as_text=True)
        self.assertIn('admin-shell', text)
        self.assertIn('/rooms/'+str(key), text)
        self.assertIn('No academic allocation has been published', text)
        self.assertNotIn('Professor workspace', text)

    def test_home_filters_and_errors_preserve_http_status_and_safe_recovery(self):
        self.assertEqual(self.client.get('/administration/?queue=rooms').status_code, 200)
        response = self.client.get('/administration/?queue=unknown')
        self.assertEqual(response.status_code, 400)
        self.assertIn('Choose a supported action queue', response.get_data(as_text=True))

    def test_student_instructor_ta_and_staff_cannot_open_administration(self):
        with self.database.transaction() as session:
            role = session.scalar(select(Role).where(Role.name == 'TeachingAssistant'))
            session.get(User, 4).primary_role_id = role.id
        for actor in (1, 2, 4, 7):
            with self.subTest(actor=actor):
                response = authorized_client(web_app.app, actor).get('/administration/')
                self.assertEqual(response.status_code, 403)
                self.assertNotIn('Your action queues', response.get_data(as_text=True))

    def test_student_and_professor_navigation_keep_their_workspace(self):
        for actor, path, marker in ((1, '/student/', 'student-shell'), (2, '/professor/', 'professor-shell')):
            text = authorized_client(web_app.app, actor).get(path).get_data(as_text=True)
            self.assertIn(marker, text)
            self.assertNotIn('admin-shell', text)

    def test_history_is_private_bounded_and_handles_invalid_parameters(self):
        self.assertEqual(self.client.get('/administration/runs/999999').status_code, 404)
        self.assertEqual(self.client.get('/administration/runs/1?page=bad').status_code, 400)
        self.assertEqual(self.client.get('/administration/runs/1?allocation_page=0').status_code, 400)
        self.assertEqual(authorized_client(web_app.app, 2).get('/administration/runs/1').status_code, 403)

    def test_history_page_displays_persisted_real_engine_outcomes(self):
        from academic_fixtures import execute_reviewed_allocation
        from web.admin_dashboard_service import AdminDashboardService
        repository = self.academic()
        execute_reviewed_allocation(repository, self.rooms.gateway)
        run = AdminDashboardService(self.database).load(6)['activeRun']['id']
        response = self.client.get('/administration/runs/'+str(run))
        self.assertEqual(response.status_code, 200)
        self.assertIn('Assigned resource segments', response.get_data(as_text=True))
        self.assertNotIn('snapshot', response.get_data(as_text=True))
