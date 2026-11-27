"""Physical group meetings attach to the existing approved room lifecycle."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from time import monotonic, sleep
from unittest import TestCase, mock

from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from postgres_fixtures import ROOT
from test_appointments import START
from test_room_requests import RoomFixture
from web.account_service import AccountService
from web.group_meeting_rooms import (
    MeetingRoomError, meeting_room_candidates, meeting_room_choices, meeting_room_features, require_meeting_room,
)
from web.persistence.database import DatabaseBusy
from web.persistence.models import GroupMeeting, GroupMeetingCommitment, GroupMeetingParticipant, Role, StudentRoomRequest, User
from web.persistence.repository import state_row
from web.personal_schedule_service import PersonalScheduleService
from web.room_request_service import RoomRequestError
from web.university_calendar import UniversityCalendarService


class MeetingRoomInputTests(TestCase):
    def test_room_facilities_are_bounded_distinct_and_supported(self):
        self.assertEqual(meeting_room_features(["projector", "computers"]), ("projector", "computers"))
        for invalid in ("projector", ["projector", "projector"], ["unknown"], [True], [("computers",)]):
            with self.subTest(invalid=invalid), self.assertRaises(MeetingRoomError):
                meeting_room_features(invalid)


class MeetingRoomIntegrationTests(RoomFixture):
    def approve_room(self, *, room=303, approval_actor=6, **values):
        key = self.request_room(room=room, **({"category": "meeting"} | values))
        self.assertEqual(self.rooms.decide(key, approval_actor, 1, True), "Confirmed")
        return key

    def attach(self, request_id, people=(1, 2), features=(), *, actor=1, start=START, duration=60):
        with self.database.transaction() as session:
            state_row(session, True)
            return require_meeting_room(session, actor, request_id, start, start + timedelta(minutes=duration),
                                        people, features, lock=True)

    def test_exact_approved_booking_is_reused_without_a_second_reservation(self):
        request = self.approve_room(features=["computers"], count=4)
        room = self.attach(request, (1, 2, 4), ("computers",))
        self.assertEqual((room.request_id, room.room_id, room.name, room.capacity, room.attendee_count),
                         (request, 303, "Computing Lab", 32, 4))
        self.assertEqual(room.features, ("computers",))
        self.assertEqual(self.totals(), (1, 1))

        with self.database.transaction(read_only=True) as session:
            self.assertEqual(meeting_room_choices(session, 1, start=START, end=START + timedelta(hours=1)), [room])
            self.assertEqual(meeting_room_choices(session, 4), [])
            self.assertEqual(meeting_room_choices(session, 6), [])
            self.assertEqual(meeting_room_choices(session, 1, start=START + timedelta(minutes=1),
                                                  end=START + timedelta(hours=1)), [])

    def test_privacy_unapproved_cancelled_or_different_interval_is_rejected(self):
        request = self.request_room(room=303, category="meeting")
        with self.assertRaises(MeetingRoomError):
            self.attach(request)
        self.assertEqual(self.rooms.decide(request, 6, 1, True), "Confirmed")
        for actor, people in ((4, (4, 2)), (6, (6, 1))):
            with self.subTest(actor=actor), self.assertRaises(MeetingRoomError):
                self.attach(request, people, actor=actor)
        with self.assertRaises(MeetingRoomError):
            self.attach(request, start=START + timedelta(minutes=15), duration=45)
        with self.assertRaises(MeetingRoomError):
            self.attach(request, duration=45)
        self.rooms.cancel(request, 1, 1)
        self.assertEqual(self.totals(), (0, 0))
        with self.assertRaises(MeetingRoomError):
            self.attach(request)

    def test_capacity_facilities_and_restricted_access_are_checked_again(self):
        self.rooms.configure_room(6, 303, self.faculty, True, ["meeting"], True, [1, 2])
        request = self.approve_room(features=["computers"], count=2)
        with self.assertRaisesRegex(MeetingRoomError, "headcount"):
            self.attach(request, (1, 2, 4))
        with self.assertRaisesRegex(MeetingRoomError, "facility"):
            self.attach(request, features=("projector",))
        with self.assertRaisesRegex(MeetingRoomError, "all selected participants"):
            self.attach(request, (1, 4))
        self.assertEqual(self.attach(request, (1, 2), ("computers",)).room_id, 303)

    def test_other_room_purpose_is_not_treated_as_meeting_approval(self):
        request = self.approve_room(category="study")
        self.assertEqual(self.rooms.detail(request, 1)["status"], "Confirmed")
        with self.assertRaises(MeetingRoomError):
            self.attach(request)
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(meeting_room_choices(session, 1), [])
        self.assertEqual(self.totals(), (1, 1))

    def test_protected_or_unresolved_room_use_blocks_revalidation(self):
        request = self.approve_room()
        self.assertEqual(self.attach(request).features, ())
        with self.assertRaisesRegex(MeetingRoomError, "facility"):
            self.attach(request, features=("computers",))
        for projected in (([{"resourceId": 303}], set()), ([], {303})):
            with self.subTest(projected=projected), mock.patch(
                    "web.group_meeting_rooms.room_usage_intervals", return_value=projected) as usage:
                with self.assertRaisesRegex(MeetingRoomError, "protected use or has unresolved"):
                    self.attach(request)
                self.assertEqual(usage.call_args.kwargs, {"exclude_request": request})
        self.assertEqual(self.totals(), (1, 1))

    def test_final_room_validation_locks_the_existing_approval_parent(self):
        request = self.approve_room()
        with self.database.transaction() as session:
            room = require_meeting_room(session, 1, request, START, START + timedelta(hours=1), [1, 2], lock=True)
            self.assertEqual(room.request_id, request)
            with self.assertRaises(DatabaseBusy), self.database.transaction() as concurrent:
                concurrent.scalar(select(StudentRoomRequest.id).where(
                    StudentRoomRequest.id == request).with_for_update(nowait=True))
        self.assertEqual(self.totals(), (1, 1))


class ScopedMeetingRoomIntegrationTests(RoomFixture):
    def setUp(self):
        super().setUp()
        self.database.sessions.configure(info={"group_meeting_pilot": True})
        with self.database.transaction() as session:
            assistant = session.get(User, 5)
            assistant.primary_role_id = session.scalar(select(Role.id).where(Role.name == "TeachingAssistant"))
            assistant.assistant_type = "Research Assistant"
        AccountService(self.database).provision(5, "room-research-fixture", "Fictional-isolated-password")

    def propose(self, actor=2, participants=(1, 2), *, room=303, key="a" * 64, features=("computers",)):
        with self.database.transaction() as session:
            return self.rooms.submit_group_meeting(session, actor, purpose="Fictional cross-role meeting", start=START,
                duration=60, participant_ids=participants, features=features, room_id=room, submission_key=key)

    def test_joint_preview_checks_occupancy_and_every_participants_access(self):
        self.rooms.configure_room(6, 303, self.faculty, True, ["meeting"], True, [1, 2])
        self.rooms.close_room(6, 303, START, START + timedelta(hours=1), "Fictional teaching demonstration")
        later = START + timedelta(hours=1)
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(meeting_room_candidates(session, 2, [1, 2, 5], [later], 60, ["computers"]), {})
            rooms = meeting_room_candidates(session, 2, [1, 2], [START, later], 60, ["computers"])
        self.assertEqual(list(rooms), [later])
        self.assertEqual([room.room_id for room in rooms[later]], [303])
        self.assertEqual(self.totals(), (0, 0))

    def test_scoped_approval_for_each_eligible_role_holds_one_room_and_keeps_participants_private(self):
        for organizer in (1, 2, 5, 7, 6):
            with self.subTest(organizer=organizer):
                participants = [organizer, 2 if organizer == 1 else 1]
                room_id, approver = (302, 7) if organizer == 6 else (303, 6)
                key = str(organizer) * 64
                request = self.propose(organizer, participants, room=room_id, key=key, features=())
                self.assertEqual(self.propose(organizer, participants, room=room_id, key=key, features=()), request)
                self.assertEqual(self.rooms.detail(request, organizer)["status"], "Pending Faculty Approval")
                self.assertEqual(self.totals(), (0, 0))
                with self.assertRaises(PermissionError):
                    self.rooms.detail(request, 4)
                with self.assertRaises(PermissionError):
                    self.rooms.decide(request, organizer, 1, True)
                self.assertEqual(self.rooms.decide(request, approver, 1, True), "Confirmed")
                self.assertEqual(self.totals(), (1, 1))
                with self.database.transaction(read_only=True) as session:
                    self.assertEqual([room.request_id for room in meeting_room_choices(session, organizer)], [request])
                    self.assertEqual(require_meeting_room(session, organizer, request, START, START + timedelta(hours=1),
                                                          participants).room_id, room_id)
                    with self.assertRaisesRegex(MeetingRoomError, "same required and optional"):
                        require_meeting_room(session, organizer, request, START, START + timedelta(hours=1), [organizer, 4])
                self.rooms.cancel(request, organizer, 1)
                self.assertEqual(self.totals(), (0, 0))

    def test_policy_changes_and_direct_ordinary_submissions_cannot_bypass_scope(self):
        with self.assertRaises(PermissionError):
            self.request_room(actor=2, category="meeting")
        with self.assertRaises(RoomRequestError):
            self.propose(6, (1, 6), room=303)
        request = self.propose()
        self.rooms.configure_room(6, 303, self.faculty, True, ["meeting"], True, [2])
        self.assertEqual(self.rooms.decide(request, 6, 1, True), "Needs Revision")
        self.assertEqual(self.totals(), (0, 0))
        with self.assertRaises(IntegrityError), self.database.transaction() as session:
            session.get(StudentRoomRequest, request).group_participant_ids = [2, 4]
        self.database.sessions.configure(info={})
        with self.assertRaises(PermissionError):
            self.propose(key="b" * 64)

    def test_downgrade_checks_for_scoped_requests_after_a_concurrent_insert_commits(self):
        config = Config(str(ROOT / "alembic.ini"))
        with mock.patch.dict(os.environ, {"DATABASE_URL": self.url}), ThreadPoolExecutor(max_workers=1) as pool:
            with self.database.transaction() as writer:
                request = self.rooms.submit_group_meeting(writer, 2, purpose="Fictional in-flight room request",
                    start=START, duration=60, participant_ids=[1, 2], features=["computers"], room_id=303,
                    submission_key="a" * 64)
                relation = writer.scalar(text("SELECT 'student_room_request'::regclass::oid"))
                downgrade = pool.submit(command.downgrade, config, "0051g")
                deadline = monotonic() + 10
                with self.database.transaction(read_only=True) as observer:
                    while not observer.scalar(text(
                        "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE relation = :relation AND NOT granted)"),
                        {"relation": relation}):
                        if downgrade.done() or monotonic() >= deadline:
                            self.fail("Downgrade did not wait for the scoped request transaction.")
                        sleep(0.01)
            with self.assertRaisesRegex(RuntimeError, "discard group room authorization history"):
                downgrade.result(timeout=10)
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(text("SELECT version_num FROM alembic_version")), self.head_revision)
            self.assertEqual(session.get(StudentRoomRequest, request).group_participant_ids, [1, 2])

    def test_confirmed_group_and_its_scoped_room_project_one_calendar_commitment(self):
        request = self.propose()
        self.assertEqual(self.rooms.decide(request, 6, 1, True), "Confirmed")
        end = START + timedelta(hours=1)
        with self.database.transaction() as session:
            meeting = GroupMeeting(organizer_id=2, purpose="Confirmed group with approved room", start_at=START,
                end_at=end, revision=1, status="Confirmed", location_mode="physical", room_request_id=request,
                required_features=["computers"], flexible=False)
            session.add(meeting)
            session.flush()
            session.add_all(GroupMeetingParticipant(meeting_id=meeting.id, user_id=person, side=side,
                revision=1, decision="Approved") for person, side in ((2, "host"), (1, "guest")))
            session.flush()
            session.add_all(GroupMeetingCommitment(meeting_id=meeting.id, user_id=person, start_at=START,
                end_at=end) for person in (1, 2))
        day = START.date().isoformat()
        calendar = UniversityCalendarService(self.database)
        for participant in (1, 2):
            with self.subTest(participant=participant):
                events = calendar.load(participant, "day", day)["events"]
                self.assertEqual([event["category"] for event in events if event["busy"]], ["appointment"])
                schedule = PersonalScheduleService(self.database).load(participant, week=day, now=START)
                self.assertEqual([event["kind"] for item in schedule["days"] for event in item["entries"]], ["Group meeting"])
        for actor in (2, 6):
            events = calendar.load(actor, "day", day, categories=["room"])["events"]
            self.assertEqual([event["id"] for event in events], [f"room:{request}"])
        self.assertEqual(self.totals(), (1, 1))
