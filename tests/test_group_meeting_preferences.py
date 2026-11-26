"""Owner authorization, validation and revision checks for meeting settings."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
import os
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from zoneinfo import ZoneInfo

from flask import Blueprint, Flask, g, session as login_session
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader
from werkzeug.datastructures import MultiDict

from auth_fixtures import authorized_client
from postgres_fixtures import PostgresTestCase, ROOT
from web.account_service import AccountService
from web.calendar_service import local_instant
from web.group_meeting_preferences import (_hard_form, _soft_form, availability_intervals,
                                           create_preferences_blueprint)
from web.persistence.models import GroupMeetingAvailability, LoginAccount, Role, SchedulingPreferenceRevision, User
from web.persistence.repository import state_row
from web.preference_values import PreferenceError
from web.scheduling_preference_service import PreferenceAccessDenied, SchedulingPreferenceService
from web.security import init_security


ZONE = ZoneInfo("Europe/Istanbul")
ROUTE = "/meetings/preferences"


def at(day, hour=0):
    return local_instant(datetime(2030, 1, day, hour), ZONE)


def fixture(**changes):
    return SimpleNamespace(**({"start": at(7), "end": at(10)} | changes))


def hard_form(**changes):
    return {"action": "availability", "revision": "0", "valid_from": "2030-01-07",
            "valid_until": "2030-01-09", "start_1": "08:30", "end_1": "12:30",
            "allow_relocation": "1"} | changes


def soft_form(**changes):
    return {"action": "preferences", "revision": "0", "preferred_weekday": "1",
            "start_1": "10:30", "end_1": "11:30", "desired_gap": "22"} | changes


class PreferenceFormTests(TestCase):
    def test_hard_availability_is_bounded_and_relocation_defaults_off(self):
        form = MultiDict(hard_form())
        self.assertEqual(_hard_form(form, fixture(), ZONE),
                         (date(2030, 1, 7), date(2030, 1, 9),
                          [{"weekday": 1, "start": "08:30", "end": "12:30"}], True))
        del form["allow_relocation"]
        self.assertFalse(_hard_form(form, fixture(), ZONE)[3])
        for updates in ({"valid_until": "2030-01-10"}, {"start_1": "13:00"}, {"end_1": ""}):
            with self.subTest(updates=updates), self.assertRaises(PreferenceError):
                _hard_form(MultiDict(hard_form(**updates)), fixture(), ZONE)

    def test_soft_preferences_allow_indifference_and_keep_separate_time_ranges(self):
        form = MultiDict(soft_form(gap_indifferent="1", desired_gap=""))
        document = _soft_form(form, fixture(), ZONE)
        self.assertEqual(document["desired_gap_minutes"], "indifferent")
        self.assertEqual(document["preferred_weekdays"], [1])
        self.assertEqual(document["preferred_windows"], [{"weekday": 1, "start": "10:30", "end": "11:30"}])

    def test_hard_intervals_clip_to_requested_horizon_and_none_publishes_nothing(self):
        first, last, windows, _ = _hard_form(MultiDict(hard_form()), fixture(), ZONE)
        row = SimpleNamespace(valid_from=first, valid_until=last, windows=windows)
        self.assertEqual(availability_intervals(row, at(7, 9), at(7, 12), ZONE), ((at(7, 9), at(7, 12)),))
        self.assertEqual(availability_intervals(row, at(8), at(9), ZONE), ())
        self.assertEqual(availability_intervals(None, at(7), at(9), ZONE), ())


class PreferenceRouteTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        self.enterContext(patch.dict(os.environ, {"RESOURCE_ALLOCATION_TIMEZONE": ZONE.key}))
        self.app = Flask(__name__)
        self.app.testing = True
        self.app.jinja_loader = ChoiceLoader([
            DictLoader({"service_base.html": "{% block service_actions %}{% endblock %}"
                        "{% block service_content %}{% endblock %}"}),
            FileSystemLoader(ROOT / "web" / "templates"),
        ])
        init_security(self.app, lambda: self.database)
        for blueprint in ("appointments", "group_meetings"):
            routes = Blueprint(blueprint, __name__, url_prefix="/" + blueprint)
            route = "calendar" if blueprint == "appointments" else "index"
            routes.add_url_rule("/", endpoint=route, view_func=lambda: "")
            self.app.register_blueprint(routes)
        self.app.register_blueprint(create_preferences_blueprint(fixture(database=self.database, people=(1, 2))))
        self.database.sessions.configure(info={"group_meeting_pilot": True})
        self.student = authorized_client(self.app, 1)
        self.instructor = authorized_client(self.app, 2)
        with self.database.transaction() as session:
            for owner, role in ((1, "Student"), (2, "Instructor")):
                session.add(Role(id=owner, name=role))
            session.flush()
            for owner in (1, 2):
                session.add(User(id=owner, source_order=owner, name=f"Private owner {owner}", primary_role_id=owner))
            session.flush()
            for owner in (1, 2):
                session.add(LoginAccount(user_id=owner, username=f"meeting-preference-user-{owner}",
                    password_hash="not-a-real-password-hash", session_version=1))
            self.calendar_revision = state_row(session).calendar_revision

    def test_owner_only_settings_saved_with_independent_revisions(self):
        self.assertEqual(self.student.get(ROUTE).status_code, 200)
        self.assertEqual(self.student.post(ROUTE, data=hard_form(owner_id="2")).status_code, 303)
        self.assertEqual(self.student.post(ROUTE, data=soft_form(owner_id="2")).status_code, 303)
        own = self.student.get(ROUTE)
        self.assertEqual(own.headers["Cache-Control"], "private, no-store")
        self.assertIn(b'value="08:30"', own.data)
        self.assertIn(b'value="10:30"', own.data)
        other = self.instructor.get(ROUTE)
        self.assertNotIn(b'value="08:30"', other.data)
        self.assertNotIn(b'value="10:30"', other.data)
        with self.database.transaction(read_only=True) as session:
            hard = session.get(GroupMeetingAvailability, 1)
            soft = session.get(SchedulingPreferenceRevision, (1, 1))
            self.assertEqual((hard.revision, hard.allow_relocation, soft.desired_gap_minutes), (1, True, 22))
            self.assertIsNone(session.get(GroupMeetingAvailability, 2))
            self.assertIsNone(session.get(SchedulingPreferenceRevision, (2, 1)))
            self.assertEqual(state_row(session).calendar_revision, self.calendar_revision + 2)

    def test_stale_and_invalid_updates_do_not_change_calendar(self):
        self.assertEqual(self.student.post(ROUTE, data=hard_form()).status_code, 303)
        result = self.student.post(ROUTE, data=hard_form(start_1="09:00"))
        self.assertEqual(result.status_code, 409)
        self.assertIn(b'value="08:30"', result.data)
        result = self.student.post(ROUTE, data=hard_form(revision="1", start_1="13:00"))
        self.assertEqual(result.status_code, 422)
        self.assertIn(b'value="13:00"', result.data)
        self.assertEqual(self.student.post(ROUTE, data=soft_form(desired_gap="2000")).status_code, 422)
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.get(GroupMeetingAvailability, 1).revision, 1)
            self.assertIsNone(session.get(SchedulingPreferenceRevision, (1, 1)))
            self.assertEqual(state_row(session).calendar_revision, self.calendar_revision + 1)

    def test_same_revision_concurrent_requests_have_one_winner(self):
        def try_save(start):
            client = authorized_client(self.app, 1)
            return client.post(ROUTE, data=hard_form(start_1=start)).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(try_save, ("08:00", "08:15"))), [303, 409])
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(state_row(session).calendar_revision, self.calendar_revision + 1)

    def test_anonymous_csrf_and_disabled_pilot_paths_are_denied(self):
        anonymous = self.app.test_client()
        self.assertEqual(anonymous.get(ROUTE).status_code, 302)
        self.assertEqual(self.student.client.post(ROUTE, data=hard_form()).status_code, 400)
        self.database.sessions.configure(info={})
        self.assertEqual(self.student.get(ROUTE).status_code, 403)
        self.assertEqual(self.student.post(ROUTE, data=hard_form()).status_code, 403)

    def test_base_preference_service_rechecks_revoked_browser_nonce(self):
        accounts = AccountService(self.database)
        with self.app.test_request_context(ROUTE):
            g.authenticated_database_url = self.database.engine.url
            g.principal = accounts.identity(1, 1, session_token=self.student.csrf)
            login_session.update(user_id=1, session_version=1, login_format=2, csrf=self.student.csrf)
            accounts.revoke_session(1, 1, self.student.csrf)
            service = SchedulingPreferenceService(self.database)
            with self.assertRaises(PreferenceAccessDenied):
                service.current()
            with self.assertRaises(PreferenceAccessDenied):
                service.replace(0, {"preference_version": 1, **_soft_form(MultiDict(soft_form()), fixture(), ZONE)})
