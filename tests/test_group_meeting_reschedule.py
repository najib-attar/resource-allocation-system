"""Confirmed meeting replacement tests against a disposable PostgreSQL schema."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import os
from pathlib import Path
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from postgres_fixtures import ROOT
from test_appointments import AppointmentFixture, START
from web.account_service import AccountService
from web.backend_executable import file_sha256
from web.cdmcs_rehearsal import RehearsalFixture
from web.calendar_service import CalendarError
from web.group_meeting_planning import plan
from web.group_meeting_reschedule import decisions_for, propose, respond
from web.group_meeting_service import MeetingError, cancel, decide, submit
from web.notification_service import NotificationService
from web.persistence.models import (
    GroupMeeting, GroupMeetingAvailability, GroupMeetingCommitment, GroupMeetingConsent,
    GroupMeetingParticipant, GroupMeetingReschedule, Role, RoomOrganizerCommitment, RoomReservation, User,
)
from web.persistence.repository import state_row
from web.room_request_service import RoomRequestError, RoomRequestService
from web.university_calendar import UniversityCalendarService


NATIVE = os.environ.get("CDMCS_REHEARSAL_TEST_ENGINE")
DAY_START = START - timedelta(hours=10)
REPLACEMENT = START + timedelta(hours=2)
ROLES = {1: "Student", 2: "Instructor", 3: "Instructor", 4: "Student", 5: "Staff", 6: "Student"}


class ConfirmedMeetingRescheduleTests(AppointmentFixture):
    def setUp(self):
        super().setUp()
        self.database.sessions.configure(info={"group_meeting_pilot": True})
        self.roster = {uid: {"id": uid, "name": f"Synthetic person {uid}", "role": role} for uid, role in ROLES.items()}
        engine = Path(NATIVE or __file__)
        self.fixture = RehearsalFixture(self.database, engine, file_sha256(engine), tuple(self.roster),
                                        DAY_START, DAY_START + timedelta(days=3))
        with self.database.transaction() as session:
            session.get(User, 5).primary_role_id = session.scalar(select(Role.id).where(Role.name == "Staff"))
            session.add_all(GroupMeetingAvailability(owner_id=uid, revision=1, valid_from=date(2030, 1, 7),
                valid_until=date(2030, 1, 9), windows=[{"weekday": day, "start": "09:00", "end": "17:00"}
                for day in (1, 2, 3)], allow_relocation=True) for uid in self.roster)
        accounts = AccountService(self.database)
        for uid in self.roster:
            accounts.provision(uid, f"synthetic-reschedule-{uid}", "Fictional-test-password", administrator=uid == 5)

    def new_group(self, *, organizer=1, required=(2, 3), optional=(6,), start=START, **options):
        with self.database.transaction() as session:
            return submit(session, self.fixture, organizer, self.roster,
                sides={organizer: "host", **dict.fromkeys(required, "guest"), **dict.fromkeys(optional, "optional")},
                purpose="Synthetic group review", start=start, duration=30, **options)

    def initial_vote(self, meeting, actor, action="approve"):
        with self.database.transaction() as session:
            decide(session, self.fixture, actor, self.roster, meeting, 1, action)

    def confirmed(self, **options):
        meeting = self.new_group(**options)
        for uid in options.get("required", (2, 3)):
            self.initial_vote(meeting, uid)
        return meeting

    def proposal(self, meeting, *, actor=1, revision=1, start=REPLACEMENT, **options):
        with self.database.transaction() as session:
            return propose(session, self.fixture, actor, self.roster, meeting, revision, start, **options)

    def vote(self, meeting, proposal_id, actor, action="approve", revision=1, **options):
        with self.database.transaction() as session:
            respond(session, self.fixture, actor, self.roster, meeting, proposal_id, revision, action, **options)

    def saved(self, meeting, proposal_id):
        with self.database.transaction(read_only=True) as session:
            group = session.get(GroupMeeting, meeting)
            item = session.get(GroupMeetingReschedule, proposal_id)
            votes = {vote.user_id: vote.decision for vote in decisions_for(session, proposal_id)}
            busy = dict(session.execute(select(GroupMeetingCommitment.user_id, GroupMeetingCommitment.start_at)
                .where(GroupMeetingCommitment.meeting_id == meeting)).all())
            return (group.status, group.revision, group.start_at, item.status, votes, busy)

    def test_unanimous_replacement_updates_calendars_inbox_and_optional_invitation_atomically(self):
        meeting = self.confirmed()
        self.initial_vote(meeting, 6, "accept-invitation")
        with self.database.transaction(read_only=True) as session:
            revision = state_row(session).calendar_revision
        proposal = self.proposal(meeting, submission_key="same-synthetic-request")
        self.assertEqual(self.proposal(meeting, submission_key="same-synthetic-request"), proposal)
        with self.assertRaisesRegex(MeetingError, "Withdraw the current proposal"):
            self.proposal(meeting, start=REPLACEMENT + timedelta(hours=1))
        self.vote(meeting, proposal, 2)
        self.assertEqual(self.saved(meeting, proposal), ("Confirmed", 1, START, "Pending Approval",
                         {1: "Approved", 2: "Approved", 3: "Pending"}, dict.fromkeys((1, 2, 3), START)))
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(state_row(session).calendar_revision, revision)
            self.assertEqual(session.get(GroupMeetingParticipant, (meeting, 6)).decision, "Accepted")
        self.vote(meeting, proposal, 3)
        self.vote(meeting, proposal, 3)
        self.assertEqual(self.saved(meeting, proposal), ("Confirmed", 2, REPLACEMENT, "Applied",
                         dict.fromkeys((1, 2, 3), "Approved"), dict.fromkeys((1, 2, 3), REPLACEMENT)))
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(state_row(session).calendar_revision, revision + 1)
            optional = session.get(GroupMeetingParticipant, (meeting, 6))
            self.assertEqual((optional.decision, optional.revision), ("Invited", 2))
        calendar, inbox = UniversityCalendarService(self.database), NotificationService(self.database)
        for uid in (1, 2, 3, 6):
            matched, = [event for event in calendar.load(uid, view="day", day="2030-01-07",
                categories=["appointment"], now=START - timedelta(minutes=5))["events"]
                if event["url"] == f"/meetings/{meeting}"]
            self.assertEqual((matched["start"], matched["busy"], matched["state"]),
                             (REPLACEMENT, uid != 6, "pending" if uid == 6 else "confirmed"))
            notices = [row for row in inbox.inbox(uid)["items"]
                       if row["subject_id"] == meeting and "replacement is confirmed" in row["message"]]
            self.assertEqual(len(notices), 1)
        self.assertFalse(inbox.inbox(5)["items"])

    def test_permission_rejection_withdrawal_and_cancellation_never_move_original(self):
        meeting = self.confirmed()
        for actor in (2, 5, 6):
            with self.subTest(actor=actor), self.assertRaises(PermissionError):
                self.proposal(meeting, actor=actor)
        rejected = self.proposal(meeting)
        for actor in (1, 5, 6):
            with self.subTest(actor=actor), self.assertRaises(PermissionError):
                self.vote(meeting, rejected, actor)
        with self.assertRaises(PermissionError):
            self.vote(meeting, rejected, 2, "withdraw")
        with self.assertRaisesRegex(MeetingError, "revision changed"):
            self.vote(meeting, rejected, 2, revision=2)
        self.vote(meeting, rejected, 2, "decline")
        self.vote(meeting, rejected, 2, "decline")
        self.assertEqual(self.saved(meeting, rejected)[:4], ("Confirmed", 1, START, "Declined"))
        withdrawn = self.proposal(meeting)
        self.vote(meeting, withdrawn, 1, "withdraw")
        self.assertEqual(self.saved(meeting, withdrawn)[:4], ("Confirmed", 1, START, "Withdrawn"))
        superseded = self.proposal(meeting)
        with self.database.transaction() as session:
            cancel(session, 1, meeting, 1)
        self.assertEqual(self.saved(meeting, superseded), ("Cancelled", 1, START, "Superseded",
                         {1: "Approved", 2: "Pending", 3: "Pending"}, {}))
        with self.assertRaisesRegex(MeetingError, "no longer current"):
            self.vote(meeting, superseded, 3)

    def test_new_calendar_conflict_rolls_back_final_vote_and_keeps_published_reservations(self):
        meeting = self.confirmed()
        proposal = self.proposal(meeting)
        self.vote(meeting, proposal, 2)
        self.service.block(3, REPLACEMENT, REPLACEMENT + timedelta(minutes=30), "Synthetic protected event")
        with self.database.transaction(read_only=True) as session:
            revision = state_row(session).calendar_revision
        with self.assertRaisesRegex(MeetingError, "overlapping commitment"):
            self.vote(meeting, proposal, 3)
        self.assertEqual(self.saved(meeting, proposal), ("Confirmed", 1, START, "Pending Approval",
                         {1: "Approved", 2: "Approved", 3: "Pending"}, dict.fromkeys((1, 2, 3), START)))
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(state_row(session).calendar_revision, revision)

    def test_simultaneous_final_votes_confirm_only_one_conflicting_replacement(self):
        first = self.confirmed(required=(2,), optional=())
        later = START + timedelta(hours=1)
        second = self.confirmed(organizer=4, required=(2,), optional=(), start=later)
        first_option, second_option = self.proposal(first), self.proposal(second, actor=4)
        barrier = Barrier(2)

        def approve(pair):
            barrier.wait(10)
            try:
                self.vote(*pair, 2)
            except MeetingError:
                return "conflict"
            return "applied"

        with ThreadPoolExecutor(max_workers=2) as workers:
            self.assertEqual(sorted(workers.map(approve, ((first, first_option), (second, second_option)))),
                             ["applied", "conflict"])
        records = [self.saved(first, first_option), self.saved(second, second_option)]
        self.assertEqual(sum(row[2] == REPLACEMENT for row in records), 1)
        self.assertEqual(sum(row[3] == "Pending Approval" and row[4][2] == "Pending" for row in records), 1)
        self.assertTrue(all(len(record[-1]) == 2 for record in records))

    def test_physical_replacement_keeps_both_approved_room_reservations(self):
        rooms = RoomRequestService(self.database, self.service.gateway)
        rooms.configure_approver(5, self.faculty, 5)
        rooms.configure_room(5, 301, self.faculty, True, ["meeting"])

        def request(start):
            return rooms.submit(1, {"start": start, "duration": 30, "count": 2, "category": "meeting",
                                    "purpose": "Fictional room reservation", "features": []}, [], 301)

        old, new = request(START), request(REPLACEMENT)
        rooms.decide(old, 5, 1, True)
        meeting = self.confirmed(required=(2,), optional=(), room_id=old)
        with self.assertRaises(CalendarError):
            self.proposal(meeting, room_id=new)
        rooms.decide(new, 5, 1, True)
        proposal = self.proposal(meeting, room_id=new)
        with self.assertRaisesRegex(RoomRequestError, "Cancel the confirmed group meeting"):
            rooms.cancel(old, 1, 1)
        self.vote(meeting, proposal, 2)
        self.assertEqual(self.saved(meeting, proposal)[:4], ("Confirmed", 2, REPLACEMENT, "Applied"))
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.get(GroupMeeting, meeting).room_request_id, new)
            self.assertEqual(dict(session.execute(select(RoomReservation.request_id, RoomReservation.start_at)).all()),
                             {old: START, new: REPLACEMENT})
        with self.assertRaisesRegex(RoomRequestError, "Cancel the confirmed group meeting"):
            rooms.cancel(new, 1, 1)

    def test_scoped_physical_replacement_releases_the_original_room_and_organizer_hold(self):
        rooms = RoomRequestService(self.database, self.service.gateway)
        rooms.configure_approver(5, self.faculty, 5)
        rooms.configure_room(5, 301, self.faculty, True, ["meeting"])

        def request(start, key):
            with self.database.transaction() as session:
                return rooms.submit_group_meeting(session, 2, purpose="Synthetic group reservation", start=start,
                    duration=30, participant_ids=[1, 2], features=[], room_id=301, submission_key=key * 64)

        old, new = request(START, "a"), request(REPLACEMENT, "b")
        rooms.decide(old, 5, 1, True)
        meeting = self.confirmed(organizer=2, required=(1,), optional=(), room_id=old)
        rooms.decide(new, 5, 1, True)
        proposal = self.proposal(meeting, actor=2, room_id=new)
        self.assertEqual(rooms.detail(old, 2)["status"], "Confirmed")
        with self.assertRaisesRegex(MeetingError, "could not be released safely"):
            self.vote(meeting, proposal, 1)
        self.vote(meeting, proposal, 1, room_service=rooms)
        self.assertEqual(rooms.detail(old, 2)["status"], "Cancelled")
        self.assertEqual(rooms.detail(new, 2)["status"], "Confirmed")
        with self.database.transaction(read_only=True) as session:
            for model in (RoomOrganizerCommitment, RoomReservation):
                self.assertEqual(list(session.scalars(select(model.request_id))), [new])
        self.assertEqual(self.saved(meeting, proposal), ("Confirmed", 2, REPLACEMENT, "Applied",
                         {1: "Approved", 2: "Approved"}, {1: REPLACEMENT, 2: REPLACEMENT}))

    def test_rescheduled_meeting_keeps_prior_controlled_relocation_consent_history(self):
        original = self.confirmed(required=(2,), optional=(), flexible=True)
        second = self.new_group(required=(2, 3), optional=(), move=(original, 1, REPLACEMENT))
        stale = self.proposal(original, start=REPLACEMENT + timedelta(hours=1))
        for actor in (2, 3):
            self.initial_vote(second, actor)
        for actor in (1, 2):
            self.initial_vote(second, actor, "consent")
        self.assertEqual(self.saved(original, stale)[:4], ("Confirmed", 2, REPLACEMENT, "Superseded"))
        proposal = self.proposal(second, start=REPLACEMENT + timedelta(hours=1))
        for actor in (2, 3):
            self.vote(second, proposal, actor)
        with self.database.transaction(read_only=True) as session:
            consents = {row.user_id: (row.decision, row.revision) for row in
                        session.scalars(select(GroupMeetingConsent).where(GroupMeetingConsent.meeting_id == second))}
            self.assertEqual(consents, {1: ("Approved", 1), 2: ("Approved", 1)})
            self.assertEqual(session.get(GroupMeeting, second).move_target_id, original)
        self.assertEqual(self.saved(second, proposal)[:4],
                         ("Confirmed", 2, REPLACEMENT + timedelta(hours=1), "Applied"))

    def test_database_rejects_forged_application_and_downgrade_with_history(self):
        meeting = self.confirmed()
        proposal = self.proposal(meeting)
        with self.assertRaisesRegex(IntegrityError, "Applied replacements require unanimous approvals"), \
                self.database.transaction() as session:
            item = session.get(GroupMeetingReschedule, proposal)
            item.status, item.resolved_at = "Applied", datetime.now(timezone.utc)
        self.assertEqual(self.saved(meeting, proposal)[:4], ("Confirmed", 1, START, "Pending Approval"))
        with patch.dict(os.environ, {"DATABASE_URL": self.url}), \
                self.assertRaisesRegex(DBAPIError, "explicitly resolve reschedule history"):
            command.downgrade(Config(str(ROOT / "alembic.ini")), "0051f")
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(text("SELECT version_num FROM alembic_version")), self.head_revision)

    def test_schema_upgrade_preserves_prior_confirmed_group_arrangements(self):
        meeting = self.confirmed(required=(2,), optional=())
        config = Config(str(ROOT / "alembic.ini"))
        with patch.dict(os.environ, {"DATABASE_URL": self.url}):
            command.downgrade(config, "0051f")
            with self.database.transaction(read_only=True) as session:
                self.assertEqual(session.scalar(text("SELECT version_num FROM alembic_version")), "0051f")
                self.assertEqual(session.scalar(text("SELECT start_at FROM group_meeting WHERE id=:id"),
                                                {"id": meeting}), START)
            command.upgrade(config, "head")
            command.check(config)
        proposal = self.proposal(meeting)
        self.assertEqual(self.saved(meeting, proposal)[:4], ("Confirmed", 1, START, "Pending Approval"))

    @skipUnless(NATIVE, "Point CDMCS_REHEARSAL_TEST_ENGINE at the verified native executable.")
    def test_native_search_excludes_current_meeting_but_preserves_other_protected_time(self):
        meeting = self.confirmed(required=(2,), optional=())
        with self.database.transaction() as session:
            self.service.block(2, START + timedelta(minutes=45), START + timedelta(minutes=90), "Synthetic protected")
            group = session.get(GroupMeeting, meeting)
            selection = ([1, 2], [], 30, START, START + timedelta(minutes=90), None)
            direct, moved, room = plan(session, self.fixture, 1, self.roster, selection, None, [], replace_meeting=group)
            self.assertEqual([item["start"] for item in direct], [START + timedelta(minutes=15)])
            self.assertFalse(moved)
            self.assertIsNone(room)
            self.assertEqual(group.start_at, START)
