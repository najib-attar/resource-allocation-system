"""Synthetic PostgreSQL and HTTP regressions for the personal research workspace."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from sqlalchemy import func, select

from auth_fixtures import authorized_client
from postgres_fixtures import PostgresTestCase
from web import app as web_app
from web.account_service import AccountService
from web.persistence.models import ApplicationState, Appointment, CalendarBlock, Notification, Role, User
from web.research_assistant_service import ResearchAssistantService


HOME = "/research-assistant/"
TASKS = "/research-assistant/tasks"


class ResearchAssistantTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        self.accounts = AccountService(self.database)
        self.password = uuid4().hex
        with self.database.transaction() as session:
            roles = {name: Role(name=name) for name in (
                "TeachingAssistant", "Student", "Staff", "Instructor", "Administrator")}
            session.add_all(roles.values())
            session.flush()
            for user_id, role, assistant_type in (
                (1, "TeachingAssistant", "  rEsEaRcH   aSSISTANT "),
                (2, "TeachingAssistant", "Research and teaching"),
                (3, "TeachingAssistant", "Teaching Assistant"),
                (4, "Student", ""),
                (5, "Staff", "Research Assistant"),
                (6, "Instructor", ""),
                (7, "Administrator", ""),
            ):
                session.add(User(id=user_id, source_order=user_id, name=f"Synthetic person {user_id}",
                                 primary_role_id=roles[role].id, assistant_type=assistant_type))
        for user_id in range(1, 8):
            self.accounts.provision(user_id, f"ras-workspace-fixture-{user_id}", self.password)
        self.client = self.configure_web()
        self.service = ResearchAssistantService(self.database)

    def account(self, actor):
        return authorized_client(web_app.app, actor)

    def login(self, actor):
        client = web_app.app.test_client()
        self.assertEqual(client.get("/login").status_code, 200)
        with client.session_transaction() as session:
            csrf = session["csrf"]
        response = client.post("/login", data={
            "username": f"ras-workspace-fixture-{actor}", "password": self.password, "csrf_token": csrf})
        self.assertEqual(response.status_code, 302)
        return urlsplit(response.location).path

    def test_research_profiles_get_the_workspace_and_fresh_empty_tasks(self):
        for actor, destination in (
            (1, HOME), (2, HOME), (3, "/appointments/"), (4, "/student/"),
            (5, "/appointments/"), (6, "/professor/"), (7, "/administration/"),
        ):
            with self.subTest(actor=actor):
                self.assertEqual(self.login(actor), destination)
        for actor in (1, 2):
            with self.subTest(actor=actor):
                for url in (HOME, TASKS):
                    self.assertEqual(self.account(actor).get(url).status_code, 200)
                self.assertEqual(self.service.tasks(actor)["items"], [])

    def test_unconfigured_profiles_and_anonymous_requests_cannot_read_or_create(self):
        form = {"submission_key": uuid4().hex, "title": "Synthetic private plan"}
        for actor in range(3, 8):
            with self.subTest(actor=actor):
                client = self.account(actor)
                self.assertEqual(client.get(HOME).status_code, 403)
                self.assertEqual(client.get(TASKS).status_code, 403)
                self.assertEqual(client.post(TASKS, data=form).status_code, 403)
                with self.assertRaises(PermissionError):
                    self.service.tasks(actor)
        anonymous = web_app.app.test_client()
        self.assertEqual(anonymous.get(HOME).status_code, 302)
        self.assertEqual(anonymous.get(TASKS).status_code, 302)
        self.assertEqual(self.service.tasks(1)["items"], [])

    def test_workspace_does_not_grant_other_portals_and_preserves_calendar_and_inbox(self):
        for url in ("/student/", "/professor/", "/administration/", "/requests",
                    "/appointments/new", "/appointments/availability", "/calendar/publications"):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post("/run-allocation", data={}).status_code, 403)
        for url in ("/calendar/", "/appointments/calendar", "/notifications/", "/notifications/feed"):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_create_deduplicates_concurrent_retries_and_resolves_ownership_on_server(self):
        token = uuid4().hex
        with ThreadPoolExecutor(max_workers=2) as executor:
            ids = list(executor.map(lambda _: self.service.create(1, token, "Review dataset", "2031-02-03"), range(2)))
        self.assertIsInstance(ids[0], UUID)
        self.assertEqual(ids[0], ids[1])
        [task] = self.service.tasks(1)["items"]
        self.assertEqual((task["id"], task["title"], task["due"], task["completed"], task["revision"]),
                         (ids[0], "Review dataset", date(2031, 2, 3), False, 1))
        self.assertEqual(self.service.tasks(2)["items"], [])
        self.assertNotIn(b"Review dataset", self.account(2).get(TASKS).data)
        self.assertEqual(self.client.post(TASKS, data={"submission_key": token, "title": "Different task",
                                                     "due_date": "2031-02-03"}).status_code, 409)
        self.assertEqual(self.service.tasks(1)["items"], [task])

    def test_forms_validate_inputs_escape_titles_and_require_csrf(self):
        form = {"submission_key": uuid4().hex, "title": "Review <notes> & draft", "due_date": ""}
        for fields in ({"title": "   "}, {"title": "x" * 4096}, {"due_date": "2031-02-30"},
                       {"due_date": "20310203"}, {"submission_key": "not-a-uuid"}):
            with self.subTest(fields=list(fields)):
                self.assertEqual(self.client.post(TASKS, data=form | fields).status_code, 400)
        self.assertEqual(self.client.client.post(TASKS, data=form).status_code, 400)
        self.assertEqual(self.service.tasks(1)["items"], [])
        self.assertEqual(self.client.post(TASKS, data=form).status_code, 303)
        self.assertEqual(self.client.post(TASKS, data=form).status_code, 303)
        [task] = self.service.tasks(1)["items"]
        self.assertIsNone(task["due"])
        page = self.client.get(TASKS)
        self.assertIn(b"Review &lt;notes&gt; &amp; draft", page.data)
        self.assertNotRegex(page.get_data(as_text=True), r'''name\s*=\s*["'](?:owner(?:_?id)?|user_?id)["']''')
        self.assertNotIn(b"Review &lt;notes&gt; &amp; draft", self.account(2).get(TASKS).data)

    def test_missing_and_foreign_tasks_are_indistinguishable_and_cannot_be_changed(self):
        task_id = self.service.create(1, uuid4().hex, "Owner-only task")
        other = self.account(2)
        for action, form in (
            ("edit", {"title": "Peer edit"}),
            ("state", {"target": "complete"}),
        ):
            with self.subTest(action=action):
                fields = form | {"revision": 1}
                foreign = other.post(f"{TASKS}/{task_id}/{action}", data=fields)
                missing = other.post(f"{TASKS}/{uuid4()}/{action}", data=fields)
                self.assertEqual((foreign.status_code, missing.status_code), (404, 404))
                self.assertNotIn(b"Owner-only task", foreign.data)
        [task] = self.service.tasks(1)["items"]
        self.assertEqual((task["title"], task["completed"], task["revision"]), ("Owner-only task", False, 1))

    def test_edit_complete_reopen_and_stale_revisions_leave_other_services_untouched(self):
        def services_state():
            with self.database.transaction(read_only=True) as session:
                counts = [session.scalar(select(func.count()).select_from(model))
                          for model in (Appointment, CalendarBlock, Notification)]
                return session.get(ApplicationState, 1).calendar_revision, counts

        before = services_state()
        task_id = self.service.create(1, uuid4().hex, "Initial task")
        url = f"{TASKS}/{task_id}"
        edit_data = {"title": "Revised task", "due_date": "2031-02-03", "revision": 1}
        self.assertEqual(self.client.post(url + "/edit", data=edit_data).status_code, 303)
        self.assertEqual(self.client.post(url + "/edit", data=edit_data | {"title": "Stale title"}).status_code, 409)
        self.assertEqual(self.client.post(url + "/state", data={"target": "complete", "revision": 1}).status_code, 409)
        self.assertEqual(self.client.post(url + "/state", data={"target": "unknown", "revision": 2}).status_code, 400)
        self.assertEqual(self.client.post(url + "/state", data={"target": "complete", "revision": 2}).status_code, 303)
        self.assertEqual(self.service.tasks(1)["items"], [])
        [completed] = self.service.tasks(1, state="completed")["items"]
        self.assertEqual((completed["title"], completed["due"], completed["completed"], completed["revision"]),
                         ("Revised task", date(2031, 2, 3), True, 3))
        self.assertEqual(self.client.post(url + "/state", data={"target": "reopen", "revision": 3}).status_code, 303)
        [reopened] = self.service.tasks(1)["items"]
        self.assertEqual((reopened["completed"], reopened["revision"]), (False, 4))
        self.assertEqual(self.service.tasks(1, state="completed")["items"], [])
        self.assertEqual(services_state(), before)

    def test_current_eligibility_is_rechecked_for_an_existing_session(self):
        self.assertEqual(self.client.get(HOME).status_code, 200)
        self.service.create(1, uuid4().hex, "Private task")
        with self.database.transaction() as session:
            session.get(User, 1).assistant_type = "Teaching Assistant"
        self.assertEqual(self.client.get(HOME).status_code, 403)
        self.assertEqual(self.client.get(TASKS).status_code, 403)
        with self.assertRaises(PermissionError):
            self.service.tasks(1)
        self.assertEqual(self.client.get("/calendar/").status_code, 200)
