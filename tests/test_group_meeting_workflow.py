"""Persistent meeting rules verified with real PostgreSQL and the native schedulers."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
import os
from threading import Barrier
from unittest import skipUnless

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from test_appointments import AppointmentFixture, START
from web.account_service import AccountService
from web.appointment_service import AppointmentError
from web.backend_executable import file_sha256
from web.calendar_service import CalendarError
from web.cdmcs_rehearsal import RehearsalFixture
from web.group_meeting_planning import plan
from web.group_meeting_service import MeetingError, cancel, decide, revise, submit, visible_meeting
from web.notification_service import NotificationService
from web.persistence.models import (
    AcademicPeriod, AppointmentCommitment, Course, CourseSection, CourseSession,
    GroupMeeting, GroupMeetingAvailability, GroupMeetingCommitment,
    GroupMeetingConsent, GroupMeetingEvent, GroupMeetingParticipant, Role, RoomOrganizerCommitment,
    RoomReservation, TeachingAssignment, User,
)
from web.persistence.repository import state_row
from web.room_request_service import RoomRequestError, RoomRequestService
from web.teaching_calendar import assert_teaching_commitments_compatible
from web.university_calendar import UniversityCalendarService


NATIVE = os.environ.get("CDMCS_REHEARSAL_TEST_ENGINE")
DAY_START = START - timedelta(hours=10)
FIRST, LAST = date(2030, 1, 7), date(2030, 1, 9)
ROLES = {1: "Student", 2: "Instructor", 3: "Instructor", 4: "Research Assistant",
         5: "Staff", 6: "Student"}


class GroupMeetingWorkflowTests(AppointmentFixture):
    def setUp(self):
        super().setUp()
        self.database.sessions.configure(info={"group_meeting_pilot": True})
        self.roster = {actor: {"id": actor, "name": f"Fictional account {actor}", "role": role}
                       for actor, role in ROLES.items()}
        engine = Path(NATIVE) if NATIVE else Path(__file__)
        self.fixture = RehearsalFixture(self.database, engine, file_sha256(engine),
                                        tuple(self.roster), DAY_START, DAY_START + timedelta(days=3))
        with self.database.transaction() as session:
            assistants = session.scalar(select(Role).where(Role.name == "TeachingAssistant"))
            staff = session.scalar(select(Role).where(Role.name == "Staff"))
            session.get(User, 4).primary_role_id = assistants.id
            session.get(User, 4).assistant_type = "Research Assistant"
            session.get(User, 5).primary_role_id = staff.id
            session.add_all(
                GroupMeetingAvailability(owner_id=actor, revision=1, valid_from=FIRST, valid_until=LAST,
                    windows=[{"weekday": day, "start": "09:00", "end": "17:00"} for day in (1, 2, 3)],
                    allow_relocation=True)
                for actor in self.roster
            )
        accounts = AccountService(self.database)
        for actor in self.roster:
            accounts.provision(actor, f"group-workflow-{actor}", "Fictional-test-password",
                               administrator=actor == 5)
        self.inbox = NotificationService(self.database)
        self.calendar = UniversityCalendarService(self.database)

    def request(self, sides=None, *, actor=1, start=START, duration=30, **options):
        with self.database.transaction() as session:
            return submit(session, self.fixture, actor, self.roster, sides=sides or {1: "host", 2: "guest"},
                          purpose="Fictional group planning", start=start, duration=duration, **options)

    def respond(self, meeting, actor, action="approve", revision=1, roster=None):
        with self.database.transaction() as session:
            decide(session, self.fixture, actor, self.roster if roster is None else roster,
                   meeting, revision, action)

    def record(self, meeting):
        with self.database.transaction(read_only=True) as session:
            row = session.get(GroupMeeting, meeting)
            return row.status, row.revision, row.start_at

    def commits(self, meeting):
        with self.database.transaction(read_only=True) as session:
            return dict(session.execute(select(GroupMeetingCommitment.user_id,
                GroupMeetingCommitment.start_at).where(GroupMeetingCommitment.meeting_id == meeting)).all())

    def responses(self, meeting, model=GroupMeetingParticipant):
        with self.database.transaction(read_only=True) as session:
            return {row.user_id: (row.decision, row.revision) for row in session.scalars(
                select(model).where(model.meeting_id == meeting))}

    def calendar_entry(self, actor, meeting):
        return next((event for event in self.calendar.load(actor, view="day", day="2030-01-07",
            categories=["appointment"], now=START - timedelta(minutes=5))["events"]
            if event["url"] == f"/meetings/{meeting}"), None)

    def confirmed_flexible(self):
        meeting = self.request({1: "host", 2: "guest", 6: "optional"}, flexible=True)
        self.respond(meeting, 2)
        self.respond(meeting, 6, "accept-invitation")
        return meeting

    def moving_request(self, original, *, replacement=START + timedelta(hours=2)):
        return self.request({1: "host", 2: "guest", 4: "guest"}, move=(original, 1, replacement))

    def test_all_four_meeting_shapes_across_supported_roles(self):
        shapes = (
            (1, {1: "host", 2: "guest", 6: "optional"}),
            (2, {2: "host", 4: "guest", 5: "guest", 6: "optional"}),
            (4, {4: "host", 1: "host", 5: "guest", 6: "optional"}),
            (5, {5: "host", 4: "host", 1: "guest", 2: "guest", 6: "optional"}),
        )
        for offset, (organizer, sides) in enumerate(shapes):
            with self.subTest(organizer=organizer, sides=sides):
                start = START + timedelta(hours=offset)
                meeting = self.request(sides, actor=organizer, start=start)
                required = {uid for uid, side in sides.items() if side != "optional"}
                self.assertEqual(self.commits(meeting), {})
                self.respond(meeting, 6, "accept-invitation" if offset % 2 else "decline-invitation")
                for uid in sorted(required - {organizer}):
                    self.respond(meeting, uid)
                self.assertEqual(self.record(meeting), ("Confirmed", 1, start))
                self.assertEqual(self.commits(meeting), dict.fromkeys(required, start))
                self.assertTrue(self.calendar_entry(organizer, meeting)["busy"])
                self.assertFalse(self.calendar_entry(6, meeting)["busy"])
                self.assertEqual(self.calendar_entry(6, meeting)["state"],
                                 "confirmed" if offset % 2 else "rejected")

    def test_privacy_unanimity_and_recipient_notifications(self):
        meeting = self.request({1: "host", 2: "guest", 4: "guest", 6: "optional"})
        for actor in (2, 4, 6):
            notice, = self.inbox.inbox(actor)["items"]
            self.assertEqual((notice["kind"], notice["subject_id"]), ("group_meeting", meeting))
        self.assertFalse(self.inbox.inbox(5)["items"])
        with self.database.transaction(read_only=True) as session, self.assertRaises(PermissionError):
            visible_meeting(session, meeting, 5)
        for actor in (1, 5, 6):
            with self.subTest(actor=actor), self.assertRaises(PermissionError):
                self.respond(meeting, actor)
        self.respond(meeting, 2)
        self.respond(meeting, 2)
        self.assertFalse(self.commits(meeting))
        self.assertEqual(self.record(meeting)[0], "Pending Approval")
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(list(session.scalars(select(GroupMeetingEvent.message)
                .where(GroupMeetingEvent.meeting_id == meeting).order_by(GroupMeetingEvent.id))),
                ["Meeting requested. Required approvals are pending.", "Required approval recorded."])
        self.respond(meeting, 4, "decline")
        self.assertEqual(self.record(meeting)[0], "Declined")
        self.assertFalse(self.commits(meeting))
        self.assertIsNone(self.calendar_entry(5, meeting))

    def test_revision_clears_approvals_and_cancellation_releases_commitments(self):
        meeting = self.request({1: "host", 2: "guest", 4: "guest", 6: "optional"})
        self.respond(meeting, 2)
        self.respond(meeting, 6, "accept-invitation")
        start = START + timedelta(hours=1)
        with self.database.transaction() as session, self.assertRaises(PermissionError):
            revise(session, self.fixture, 4, self.roster, meeting, 1, start)
        with self.database.transaction() as session:
            revise(session, self.fixture, 1, self.roster, meeting, 1, start)
        self.assertEqual(self.responses(meeting), {1: ("Approved", 2), 2: ("Pending", 2),
                                                   4: ("Pending", 2), 6: ("Invited", 2)})
        with self.assertRaises(MeetingError):
            self.respond(meeting, 4)
        for actor in (2, 4):
            self.respond(meeting, actor, revision=2)
        with self.assertRaises(PermissionError), self.database.transaction() as session:
            cancel(session, 6, meeting, 2)
        with self.database.transaction() as session:
            cancel(session, 4, meeting, 2)
        self.assertEqual(self.record(meeting), ("Cancelled", 2, start))
        self.assertFalse(self.commits(meeting))
        self.assertEqual(self.calendar_entry(1, meeting)["state"], "cancelled")

    def test_concurrent_confirmations_of_overlapping_groups_have_one_winner(self):
        first = self.request()
        second = self.request({4: "host", 2: "guest"}, actor=4)
        barrier = Barrier(2)

        def compete(meeting):
            barrier.wait(10)
            try:
                self.respond(meeting, 2)
            except MeetingError:
                return "conflict"
            return "confirmed"

        with ThreadPoolExecutor(max_workers=2) as workers:
            self.assertEqual(sorted(workers.map(compete, (first, second))), ["confirmed", "conflict"])
        self.assertEqual(sorted(self.record(key)[0] for key in (first, second)),
                         ["Confirmed", "Pending Approval"])
        self.assertEqual(sum(2 in self.commits(key) for key in (first, second)), 1)

    def test_protected_standard_appointment_cannot_be_moved_or_overlapped(self):
        appointment = self.submit(start=START)
        self.service.decide(appointment, 2, 1, True)
        for arrangement in ({}, {"move": (appointment, 1, START + timedelta(hours=2))}):
            with self.subTest(arrangement=arrangement), self.assertRaises(MeetingError):
                self.request(**arrangement)
        with self.database.transaction(read_only=True) as session:
            rows = list(session.scalars(select(AppointmentCommitment).where(
                AppointmentCommitment.appointment_id == appointment)))
            self.assertEqual({(row.user_id, row.start_at) for row in rows}, {(1, START), (2, START)})

    def test_standard_scheduler_and_personal_blocks_respect_group_confirmation(self):
        meeting = self.request()
        self.respond(meeting, 2)
        with self.assertRaises(AppointmentError):
            self.submit(organizer=6, professors=(2,), start=START)
        with self.assertRaises(CalendarError):
            self.service.block(2, START, START + timedelta(minutes=30), "Protected by meeting")
        self.assertEqual(self.commits(meeting), {1: START, 2: START})

    def test_teaching_publication_and_group_confirmation_protect_each_other(self):
        def publish_class():
            with self.database.transaction() as session:
                state_row(session, True)
                period = AcademicPeriod(name="Fictional protected group term", start_date=FIRST,
                    end_date=LAST, timezone="Europe/Istanbul", is_semester=True)
                course = Course(code="BLG 107", title="Fictional teaching for group integrity")
                session.add_all((period, course))
                session.flush()
                section = CourseSection(course_id=course.id, academic_period_id=period.id,
                    crn="30107", quota=20, published_title=course.title, branch="BLG", academic_level="LS",
                    instruction_method="In person", source_kind="archive", source_url="https://example.invalid/course",
                    publication_status="scheduled", published_schedule={}, excluded_dates=[])
                session.add(section)
                session.flush()
                session.add_all((TeachingAssignment(section_id=section.id, ordinal=1, user_id=2,
                    published_name="Fictional course instructor"),
                    CourseSession(section_id=section.id, ordinal=1, resource_id=301, building_code="BBB", room_code="M301",
                    day=1, start_minutes=600, end_minutes=660, published_day="Pazartesi", published_start="10:00",
                    published_end="10:59", published_building="BBB", published_room="M301")))
                session.flush()
                assert_teaching_commitments_compatible(session)

        group = self.request()
        self.respond(group, 2)
        with self.assertRaisesRegex(CalendarError, "Published teaching conflicts"):
            publish_class()
        self.assertEqual(self.commits(group), {1: START, 2: START})
        with self.database.transaction() as session:
            cancel(session, 1, group, 1)
        publish_class()
        with self.assertRaisesRegex(MeetingError, "overlapping commitment"):
            self.request()
        next_start = START + timedelta(hours=1)
        adjacent = self.request(start=next_start)
        self.respond(adjacent, 2)
        self.assertEqual(self.commits(adjacent), {1: next_start, 2: next_start})

    def test_physical_group_reuses_approved_room_and_guards_its_release(self):
        rooms = RoomRequestService(self.database, self.service.gateway)
        rooms.configure_approver(5, self.faculty, 5)
        rooms.configure_room(5, 301, self.faculty, True, ["meeting"])
        key = rooms.submit(1, {"start": START, "duration": 30, "count": 3, "category": "meeting",
            "purpose": "Fictional physical arrangement", "features": []}, [], 301)
        with self.assertRaises(CalendarError):
            self.request(room_id=key)
        self.assertEqual(rooms.decide(key, 5, 1, True), "Confirmed")
        meeting = self.request({1: "host", 2: "guest", 6: "optional"}, room_id=key)
        self.respond(meeting, 2)
        self.assertEqual(self.record(meeting), ("Confirmed", 1, START))
        self.assertEqual(self.commits(meeting), {1: START, 2: START})
        with self.assertRaisesRegex(RoomRequestError, "Cancel the confirmed group meeting"):
            rooms.cancel(key, 1, 1)
        with self.database.transaction() as session:
            cancel(session, 1, meeting, 1)
        self.assertFalse(self.commits(meeting))
        self.assertEqual(rooms.detail(key, 1)["status"], "Confirmed")
        with self.database.transaction(read_only=True) as session:
            for model in (RoomReservation, RoomOrganizerCommitment):
                self.assertEqual(session.scalar(select(func.count()).select_from(model)), 1)
        rooms.cancel(key, 1, 1)
        self.assertEqual(rooms.detail(key, 1)["status"], "Cancelled")

    def test_unanimous_move_consent_replaces_both_arrangements_in_one_commit(self):
        original = self.confirmed_flexible()
        replacement = START + timedelta(hours=2)
        new = self.moving_request(original, replacement=replacement)
        for actor in (2, 4):
            self.respond(new, actor)
        self.respond(new, 1, "consent")
        self.assertEqual(self.record(original), ("Confirmed", 1, START))
        self.assertFalse(self.commits(new))
        self.assertEqual(self.responses(new, GroupMeetingConsent), {1: ("Approved", 1), 2: ("Pending", 1)})
        self.respond(new, 2, "consent")
        self.assertEqual(self.record(original), ("Confirmed", 2, replacement))
        self.assertEqual(self.commits(original), {1: replacement, 2: replacement})
        self.assertEqual(self.responses(original)[6], ("Invited", 2))
        self.assertEqual(self.record(new), ("Confirmed", 1, START))
        self.assertEqual(self.commits(new), {1: START, 2: START, 4: START})
        self.assertTrue(any(item["subject_id"] == original and "moved" in item["message"].lower()
                            for item in self.inbox.inbox(6)["items"]))
        self.assertTrue(any(item["subject_id"] == new and "confirmed" in item["message"].lower()
                            for item in self.inbox.inbox(4)["items"]))

    def test_move_refusal_or_missing_affected_membership_cannot_release_original(self):
        original = self.confirmed_flexible()
        invalid = (original, 1, START + timedelta(hours=2))
        for actor, sides in ((1, {1: "host", 4: "guest"}), (4, {4: "host", 1: "guest", 2: "guest"})):
            with self.subTest(actor=actor), self.assertRaises(MeetingError):
                self.request(sides, actor=actor, move=invalid)
        new = self.moving_request(original)
        with self.assertRaises(PermissionError):
            self.respond(new, 4, "consent")
        self.respond(new, 1, "consent")
        self.respond(new, 2, "refuse-move")
        self.assertEqual(self.record(new)[0], "Declined")
        self.assertFalse(self.commits(new))
        self.assertEqual(self.commits(original), {1: START, 2: START})
        retry_start = START + timedelta(hours=1)
        retry = self.request(start=retry_start)
        self.respond(retry, 2)
        self.assertEqual(self.commits(retry), {1: retry_start, 2: retry_start})

    def test_block_added_before_last_move_consent_rolls_back_every_change(self):
        original = self.confirmed_flexible()
        replacement = START + timedelta(hours=2)
        new = self.moving_request(original, replacement=replacement)
        for actor in (2, 4):
            self.respond(new, actor)
        self.respond(new, 1, "consent")
        self.service.block(2, replacement, replacement + timedelta(minutes=30), "Fictional new class")
        with self.database.transaction(read_only=True) as session:
            prior_revision = state_row(session).calendar_revision
        with self.assertRaises(MeetingError):
            self.respond(new, 2, "consent")
        self.assertEqual(self.record(original), ("Confirmed", 1, START))
        self.assertEqual(self.record(new), ("Pending Approval", 1, START))
        self.assertEqual(self.commits(original), {1: START, 2: START})
        self.assertFalse(self.commits(new))
        self.assertEqual(self.responses(new, GroupMeetingConsent)[2], ("Pending", 1))
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(state_row(session).calendar_revision, prior_revision)

    def test_confirmed_group_requires_correct_commitments_at_database_commit(self):
        meeting = self.request()
        with self.assertRaises(IntegrityError), self.database.transaction() as session:
            row = session.get(GroupMeeting, meeting)
            row.status = "Confirmed"
            session.get(GroupMeetingParticipant, (meeting, 2)).decision = "Approved"
            session.add(GroupMeetingCommitment(meeting_id=meeting, user_id=2,
                start_at=START, end_at=START + timedelta(minutes=30)))
        self.assertEqual(self.record(meeting)[0], "Pending Approval")
        self.assertFalse(self.commits(meeting))

    def test_database_rejects_confirmed_move_missing_an_affected_consent(self):
        original = self.confirmed_flexible()
        replacement = START + timedelta(hours=2)
        new = self.moving_request(original, replacement=replacement)
        with self.assertRaisesRegex(IntegrityError, "Group confirmation requires current approvals and exact commitments"), \
                self.database.transaction() as session:
            # Arrange a conflict-free result directly, with only one missing
            # consent. The deferred constraint must reject the entire result.
            session.execute(delete(GroupMeetingCommitment).where(GroupMeetingCommitment.meeting_id == original))
            target = session.get(GroupMeeting, original)
            target.start_at, target.end_at, target.revision = replacement, replacement + timedelta(minutes=30), 2
            for actor in (1, 2, 6):
                session.get(GroupMeetingParticipant, (original, actor)).revision = 2
            new_meeting = session.get(GroupMeeting, new)
            new_meeting.status = "Confirmed"
            for actor in (2, 4):
                session.get(GroupMeetingParticipant, (new, actor)).decision = "Approved"
            session.get(GroupMeetingConsent, (new, 1)).decision = "Approved"
            session.delete(session.get(GroupMeetingConsent, (new, 2)))
            for key, at, actors in ((original, replacement, (1, 2)), (new, START, (1, 2, 4))):
                session.add_all(GroupMeetingCommitment(meeting_id=key, user_id=actor,
                    start_at=at, end_at=at + timedelta(minutes=30)) for actor in actors)
        self.assertEqual(self.record(original), ("Confirmed", 1, START))
        self.assertEqual(self.record(new), ("Pending Approval", 1, START))
        self.assertEqual(self.commits(original), {1: START, 2: START})
        self.assertFalse(self.commits(new))

    @skipUnless(NATIVE, "Point CDMCS_REHEARSAL_TEST_ENGINE at the verified native CDMCS executable.")
    def test_native_ranked_plans_are_explained_and_separate_conditional_options(self):
        old = self.confirmed_flexible()
        end = DAY_START + timedelta(days=1)
        selection = ([1, 2, 4], [6], 30, DAY_START, end, START)
        with self.database.transaction(read_only=True) as session:
            direct, conditional, room = plan(session, self.fixture, 1, self.roster, selection, None, [])
        self.assertIsNone(room)
        self.assertTrue(direct and conditional)
        for row in direct:
            self.assertIsNone(row["move"])
            self.assertTrue(row["start"] + timedelta(minutes=30) <= START
                            or row["start"] >= START + timedelta(minutes=30))
        for row in conditional:
            self.assertEqual(row["move"][:2], (old, 1))
            self.assertIsNotNone(row["replacement"])
            self.assertIsInstance(row["cost"], int)
            self.assertIn(row["coverage"], range(101))
            self.assertGreaterEqual(row["wait"], 0)
            self.assertIsInstance(row["gaps"], int)
        self.assertEqual(self.record(old), ("Confirmed", 1, START))
