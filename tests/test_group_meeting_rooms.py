"""Physical group meetings attach to the existing approved room lifecycle."""

from datetime import timedelta
from unittest import TestCase, mock

from sqlalchemy import select

from test_appointments import START
from test_room_requests import RoomFixture
from web.group_meeting_rooms import (
    MeetingRoomError, meeting_room_choices, meeting_room_features, require_meeting_room,
)
from web.persistence.database import DatabaseBusy
from web.persistence.models import StudentRoomRequest
from web.persistence.repository import state_row


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
