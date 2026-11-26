"""Verify the isolated group-rehearsal request, projection, and native contracts."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime, timedelta
import os
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest import TestCase, skipUnless
from unittest.mock import MagicMock, patch

from flask import Flask, g, session
from sqlalchemy.engine import make_url
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import Forbidden

from research.cdmcs.i3a.execution import validate_cdmcs
from web import cdmcs_rehearsal as rehearsal
from web.backend_executable import file_sha256
from web.calendar_service import epoch, local_instant


NATIVE_PATH = os.environ.get("CDMCS_REHEARSAL_TEST_ENGINE")


class RehearsalTests(TestCase):
    def setUp(self):
        zone = patch.dict(os.environ, {"RESOURCE_ALLOCATION_TIMEZONE": "Europe/Istanbul"})
        zone.start()
        self.addCleanup(zone.stop)
        self.roster = {
            user_id: {"id": user_id, "name": f"Synthetic person {user_id}", "role": role}
            for user_id, role in enumerate(
                ("Student", "Instructor", "Research Assistant", "Staff", "Administrator", "Instructor"), 1)
        }
        self.url = make_url("postgresql://rehearsal@127.0.0.1:55499/ras_cdmcs_rehearsal")
        self.database = MagicMock()
        self.database.engine.url = self.url
        self.database_session = self.database.transaction.return_value.__enter__.return_value
        self.database_session.get_bind.return_value.url = self.url
        self.database_session.scalar.return_value = None
        engine = Path(__file__)
        self.flexible = rehearsal.FlexibleMeeting(
            (1, 2), self.at(11), self.at(11, 30), (self.at(12), self.at(13))
        )
        self.fixture = rehearsal.RehearsalFixture(
            self.database, engine, file_sha256(engine), tuple(self.roster), self.at(0),
            self.at(0) + timedelta(days=2), (self.flexible,)
        )
        self.form = MultiDict([
            ("requiredIds", "2"), ("optionalIds", "6"), ("duration", "30"),
            ("fromDate", "2030-01-07"), ("untilDate", "2030-01-07"),
        ])

    @staticmethod
    def at(hour, minute=0):
        return local_instant(datetime(2030, 1, 7, hour, minute))

    def interval(self, person, start, end):
        return {"userId": person, "start": epoch(self.at(*start)), "end": epoch(self.at(*end))}

    def selection(self, form=None):
        return rehearsal._selection(self.form if form is None else form, 1, self.roster, self.fixture)

    def projected(self, **changes):
        facts = {
            "published": [self.interval(2, (10,), (12,)), self.interval(2, (12,), (13,))],
            "busy": [
                self.interval(2, (9, 45), (10, 15)),
                self.interval(2, (9, 50), (10, 30)),
                self.interval(2, (10, 30), (10, 45)),
                self.interval(6, (9,), (17,)),
            ],
            "unresolvedIds": [6],
        } | changes
        with patch.object(rehearsal, "calendar_snapshot", return_value=(facts, 7)) as snapshot:
            compiled = rehearsal._compile(
                self.database_session, self.fixture, 1, self.roster, self.selection()
            )
        return compiled, snapshot

    def test_group_shapes_and_separate_optional_membership(self):
        for hosts, guests in (((), (2,)), ((), (2, 3)), ((3,), (2,)), ((3,), (2, 4, 5))):
            with self.subTest(hosts=hosts, guests=guests):
                form = self.form.copy()
                form.setlist("cohostIds", [str(user_id) for user_id in hosts])
                form.setlist("requiredIds", [str(user_id) for user_id in guests])
                self.assertEqual(self.selection(form)[:2], ([1, *hosts, *guests], [6]))

    def test_form_rejects_spoofing_duplicate_and_missing_required_people(self):
        for field, values in (
            ("requiredIds", []), ("requiredIds", ["1"]), ("requiredIds", ["2", "2"]),
            ("cohostIds", ["2"]), ("optionalIds", ["2"]), ("optionalIds", ["2000"]),
            ("requiredIds", ["not-a-user"]),
        ):
            with self.subTest(field=field, values=values):
                form = self.form.copy()
                form.setlist(field, values)
                with self.assertRaises(rehearsal.RehearsalError):
                    self.selection(form)

    def test_form_rejects_invalid_duration_or_out_of_fixture_time(self):
        for key, value in (
            ("duration", "14"), ("duration", "121"), ("duration", "25"), ("duration", ""),
            ("fromDate", "2030-01-08"), ("untilDate", "2030-01-09"),
            ("fromDate", "invalid"), ("preferredStart", "2030-01-08T09:00"),
            ("preferredStart", "2030-01-07T10:00+00:00"),
        ):
            with self.subTest(key=key, value=value):
                form = self.form.copy()
                form[key] = value
                with self.assertRaises(rehearsal.RehearsalError):
                    self.selection(form)

    def test_required_calendar_absence_has_no_silent_fallback(self):
        with self.assertRaisesRegex(rehearsal.RehearsalError, "unresolved"):
            self.projected(unresolvedIds=[2])
        (payload, _, _, _), _ = self.projected(published=[])
        self.assertIsNone(payload)

    def test_compile_preserves_instructor_windows_protected_events_and_privacy(self):
        (payload, meeting, version, preferences), snapshot = self.projected()
        self.assertEqual((version, preferences), (7, (0, 0)))
        self.assertEqual(meeting, self.flexible)
        self.assertEqual(set(payload["required_people"]), {"person-0", "person-1"})
        self.assertEqual(set(payload["profiles"]), {"person-0", "person-1"})
        self.assertEqual(payload["profiles"]["person-1"]["published"], [[600, 720], [720, 780]])
        self.assertIn(690, payload["candidate_starts"])
        self.assertNotIn(705, payload["candidate_starts"])
        self.assertNotIn(540, payload["candidate_starts"])
        self.assertEqual(payload["move_participant_cost"], 50)
        protected = [row for row in payload["existing"] if row["id"].startswith("protected")]
        self.assertEqual([(row["start"], row["duration"]) for row in protected], [(585, 45), (630, 15)])
        self.assertTrue(all(row["people"] == ["person-1"] and not row["flexible"] for row in protected))
        self.assertEqual(snapshot.call_args.args[3], [6])

    def test_excluding_a_flexible_attendee_leaves_a_protected_block(self):
        self.fixture = replace(self.fixture, flexible=(replace(self.flexible, people=(1, 2, 3)),))
        (payload, meeting, _, _), _ = self.projected()
        block = next(row for row in payload["existing"] if row["id"] == "rehearsal-flex")
        self.assertIsNone(meeting)
        self.assertFalse(block["flexible"])
        self.assertEqual(set(block["people"]), {"person-0", "person-1"})
        self.assertEqual(rehearsal._relocation_rows(self.fixture, payload, meeting), [])

    def test_effective_persisted_preference_compiles_into_private_profile(self):
        self.database_session.scalar.side_effect = [
            None,
            SimpleNamespace(
                revision=3, status="configured", contract_version=1, created_at=self.at(0),
                timezone="Europe/Istanbul", effective_from=date(2030, 1, 1), effective_until=date(2030, 1, 31),
                preferred_weekdays=[1], preferred_windows=[{"weekday": 1, "start": "12:00", "end": "13:00"}],
                gap_indifferent=False, desired_gap_minutes=45,
            ),
        ]
        (payload, _, _, revisions), _ = self.projected()
        self.assertEqual(revisions, (0, 3))
        instructor = payload["profiles"]["person-1"]
        self.assertEqual(instructor["preferred_break"], 45)
        rates = instructor["rate_prefix"]
        self.assertEqual((rates[660 + 1] - rates[660], rates[720 + 1] - rates[720]), (2, 1))

    def test_read_requires_an_exact_bound_demo_roster_and_current_identity(self):
        app = Flask(__name__)
        app.secret_key = "synthetic-test-key"
        rows = [
            (SimpleNamespace(id=user_id, name=data["name"], status="Active",
                             assistant_type="Research Assistant" if user_id == 3 else None),
             "TeachingAssistant" if user_id == 3 else data["role"], True)
            for user_id, data in self.roster.items()
        ]
        principal = SimpleNamespace(user_id=1)
        with app.test_request_context("/"), patch.object(rehearsal, "AccountService") as accounts:
            identity = accounts.return_value.identity
            identity.return_value = principal
            g.principal, g.authenticated_database_url = principal, self.url
            session.update(login_format=2, user_id=1, session_version=4, csrf="synthetic-token")
            self.database_session.execute.return_value = rows
            with rehearsal._read(self.fixture) as (database_session, actor, roster):
                self.assertIs(database_session, self.database_session)
                self.assertEqual(actor, 1)
                self.assertEqual(roster, self.roster)
            identity.assert_called_once_with(1, 4, session=self.database_session, session_token="synthetic-token")
            self.database.transaction.assert_called_once_with(read_only=True)
            for condition in ("foreign database", "new roster user", "stale principal", "disabled account"):
                with self.subTest(condition=condition):
                    g.authenticated_database_url = self.url.set(port=55498) if condition == "foreign database" else self.url
                    self.database_session.execute.return_value = rows
                    if condition == "new roster user":
                        self.database_session.execute.return_value = rows + [(SimpleNamespace(id=7), "Student", True)]
                    if condition == "disabled account":
                        self.database_session.execute.return_value = [(*rows[0][:2], False), *rows[1:]]
                    identity.return_value = None if condition == "stale principal" else principal
                    with self.assertRaises(Forbidden):
                        with rehearsal._read(self.fixture):
                            self.fail("Unsafe rehearsal identity was admitted")

    def test_registration_rejects_an_ordinary_database(self):
        self.database.engine.url = self.url.set(database="resource_allocation")
        app = Flask(__name__)
        with self.assertRaises(rehearsal.RehearsalError):
            rehearsal.register_rehearsal(app, self.fixture)

    def test_normal_application_does_not_register_the_rehearsal(self):
        from web.app import app

        self.assertNotIn("cdmcs_rehearsal.index", app.view_functions)
        self.assertFalse(app.jinja_env.globals.get("cdmcs_rehearsal_enabled"))

    def test_booking_handoff_respects_existing_roles_and_faculty(self):
        with patch.object(rehearsal, "AppointmentService") as service:
            directory = service.return_value.directory
            directory.return_value = {"professors": [{"id": 2, "facultyId": 11}, {"id": 6, "facultyId": 12}]}
            for selection in (([2, 1], [], 30), ([1, 2, 3], [], 30), ([1, 2], [4], 30)):
                with self.subTest(selection=selection):
                    self.assertIsNone(rehearsal._standard_booking(self.fixture, selection, self.roster))
            directory.assert_not_called()
            self.assertIsNone(rehearsal._standard_booking(self.fixture, ([1, 2, 6], [], 30), self.roster))
            self.assertEqual(rehearsal._standard_booking(self.fixture, ([1, 2], [], 30), self.roster),
                             {"faculty": 11, "professors": [2], "invitees": [], "duration": 30})

    def test_request_from_outside_loopback_is_rejected_before_reading_calendars(self):
        app = Flask(__name__)
        rehearsal.register_rehearsal(app, self.fixture)
        with patch.object(rehearsal, "_read") as read:
            response = app.test_client().get("/appointments/rehearsal", environ_overrides={"REMOTE_ADDR": "192.0.2.15"})
        self.assertEqual(response.status_code, 403)
        read.assert_not_called()

    def test_changed_calendar_or_preference_revision_discards_recommendations(self):
        (payload, _, _, _), _ = self.projected()
        start = 10 * 60 + 45
        direct = {
            "operation": "cdmcs_schedule_v1", "model": "V15_restricted_one_blocking_move", "status": "OK",
            "solutions_evaluated": 1, "returned_count": 1, "truncated": False,
            "recommendations": [{
                "start_minute": start, "end_minute": start + 30, "total_cost": 60, "fairness_max_burden": 30,
                "moved_meeting_id": None, "replacement_start_minute": None,
                "proposal_status": "DIRECT_PENDING_NORMAL_MEETING_APPROVAL",
                "required_permissions": {"new_meeting_extra_availability": [],
                    "relocated_meeting_extra_availability": [], "relocation_participant_approval": []},
            }],
        }
        app = Flask(__name__)
        rehearsal.register_rehearsal(app, self.fixture)
        for calendar_revision, preference_revision in ((8, 0), (7, 1)):
            with self.subTest(calendar_revision=calendar_revision, preference_revision=preference_revision):
                with (
                    patch.object(rehearsal, "_read") as read,
                    patch.object(rehearsal, "_compile", return_value=(payload, None, 7, (0, 0))),
                    patch.object(rehearsal, "_run", return_value=direct),
                    patch.object(rehearsal, "state_row", return_value=SimpleNamespace(calendar_revision=calendar_revision)),
                    patch.object(rehearsal.SchedulingPreferenceService, "_view",
                                 return_value=SimpleNamespace(revision=preference_revision)),
                    patch.object(rehearsal, "render_template", return_value="rendered") as render,
                ):
                    read.return_value.__enter__.return_value = (self.database_session, 1, self.roster)
                    response = app.test_client().post("/appointments/rehearsal", data=self.form)
                self.assertEqual(response.status_code, 409)
                self.assertIn("no-store", response.headers["Cache-Control"])
                self.assertIsNone(render.call_args.kwargs["result"])
                self.assertIn("changed", render.call_args.kwargs["error"])
                self.assertEqual(read.call_count, 2)

    def test_concurrent_requests_do_not_run_two_native_searches(self):
        (payload, _, _, _), _ = self.projected()
        app = Flask(__name__)
        rehearsal.register_rehearsal(app, self.fixture)
        entered, released = Event(), Event()

        def paused_engine(*_):
            entered.set()
            if not released.wait(timeout=5):
                raise AssertionError("The second rehearsal did not finish in time")
            return {
                "operation": "cdmcs_schedule_v1", "model": "V15_restricted_one_blocking_move",
                "status": "NO_FEASIBLE_PROPOSAL", "solutions_evaluated": 0, "returned_count": 0,
                "truncated": False, "recommendations": [],
            }

        def post():
            return app.test_client().post("/appointments/rehearsal", data=self.form.copy())

        with (
            patch.object(rehearsal, "_read") as read,
            patch.object(rehearsal, "_compile", return_value=(payload, None, 7, (0, 0))),
            patch.object(rehearsal, "_run", side_effect=paused_engine) as run,
            patch.object(rehearsal, "state_row", return_value=SimpleNamespace(calendar_revision=7)),
            patch.object(rehearsal, "render_template", side_effect=lambda *_, **data: data["error"] or ""),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            read.return_value.__enter__.return_value = (self.database_session, 1, self.roster)
            first = pool.submit(post)
            try:
                self.assertTrue(entered.wait(timeout=5))
                second = pool.submit(post).result(timeout=5)
                self.assertEqual(second.status_code, 409)
                self.assertIn(b"Another rehearsal search", second.data)
                self.assertEqual(run.call_count, 1)
            finally:
                released.set()
            self.assertEqual(first.result(timeout=5).status_code, 200)
        self.assertFalse(self.fixture.admission.locked())

    def test_an_engine_with_an_unexpected_digest_never_starts(self):
        stale = replace(self.fixture, engine_sha256="f" * 64)
        with patch.object(rehearsal, "execute") as execute:
            with self.assertRaisesRegex(rehearsal.RehearsalError, "executable changed"):
                rehearsal._run(stale, {})
        execute.assert_not_called()

    def test_conditional_proposal_cannot_omit_a_required_move_approval(self):
        (payload, meeting, _, _), _ = self.projected()
        answer = {
            "operation": "cdmcs_schedule_v1", "model": "V15_restricted_one_blocking_move", "status": "OK",
            "solutions_evaluated": 1, "returned_count": 1, "truncated": False,
            "recommendations": [{
                "start_minute": 645, "end_minute": 675, "total_cost": 0, "fairness_max_burden": 0,
                "moved_meeting_id": "rehearsal-flex", "replacement_start_minute": 720,
                "proposal_status": "CONDITIONAL_PENDING_APPROVAL",
                "required_permissions": {"new_meeting_extra_availability": [],
                    "relocated_meeting_extra_availability": [], "relocation_participant_approval": ["person-0"]},
            }],
        }
        with patch.object(rehearsal, "_run", return_value=answer):
            with self.assertRaisesRegex(rehearsal.RehearsalError, "could not be verified"):
                rehearsal._relocation_rows(self.fixture, payload, meeting)

    @skipUnless(NATIVE_PATH, "Set CDMCS_REHEARSAL_TEST_ENGINE to the standalone C++ executable.")
    def test_native_direct_and_conditional_results_use_identical_protected_calendar(self):
        engine = Path(NATIVE_PATH).resolve(strict=True)
        fixture = replace(self.fixture, engine=engine, engine_sha256=file_sha256(engine))
        (payload, meeting, _, _), _ = self.projected()
        answer = rehearsal._run(fixture, payload)
        self.assertEqual(validate_cdmcs(answer, payload), "feasible")
        direct = answer["recommendations"]
        self.assertTrue(all(row["end_minute"] <= 660 or row["start_minute"] >= 690 for row in direct))
        self.assertTrue(all(row["start_minute"] >= 645 for row in direct))

        conditional = rehearsal._relocation_rows(fixture, payload, meeting)
        self.assertEqual({row["start_minute"] for row in conditional}, {645, 660, 675})
        self.assertEqual({row["replacement_start_minute"] for row in conditional}, {720})
        for row in conditional:
            self.assertEqual(row["proposal_status"], "CONDITIONAL_PENDING_APPROVAL")
            self.assertEqual(set(row["required_permissions"]["relocation_participant_approval"]),
                             {"person-0", "person-1"})
        self.assertFalse(next(row for row in payload["existing"] if row["id"] == "rehearsal-flex")["flexible"])
