"""Real PostgreSQL checks for private group meeting Inbox and calendar entries."""

from datetime import timedelta

from flask import Blueprint, Flask, render_template_string
from sqlalchemy import select

from postgres_fixtures import ROOT
from test_appointments import AppointmentFixture, START
from web.account_service import AccountService
from web.notification_routes import add_notification_urls
from web.notification_service import NotificationService, publish_event
from web.persistence.models import GroupMeeting, GroupMeetingCommitment, GroupMeetingEvent, GroupMeetingParticipant, Notification
from web.personal_schedule_service import PersonalScheduleService
from web.university_calendar import UniversityCalendarService


class GroupMeetingProjectionTests(AppointmentFixture):
    def setUp(self):
        super().setUp()
        self.database.sessions.configure(info={"group_meeting_pilot": True})
        for actor in (1, 2, 4, 5):
            AccountService(self.database).provision(actor, f"pilot-user-{actor}", "Fictional-pilot-password")
        self.inbox = NotificationService(self.database)
        self.calendar = UniversityCalendarService(self.database)
        self.personal = PersonalScheduleService(self.database)

    def meeting(self, *, confirmed=False, optional="Invited"):
        with self.database.transaction() as session:
            meeting = GroupMeeting(organizer_id=1, purpose="Synthetic pilot meeting",
                start_at=START, end_at=START + timedelta(minutes=30), location_mode="online",
                status="Confirmed" if confirmed else "Pending Approval")
            session.add(meeting)
            session.flush()
            session.add_all(GroupMeetingParticipant(meeting_id=meeting.id, user_id=actor,
                revision=1, side=side, decision=decision) for actor, side, decision in (
                    (1, "host", "Approved"), (2, "guest", "Approved" if confirmed else "Pending"),
                    (4, "optional", optional)))
            if confirmed:
                session.flush()
                session.add_all(GroupMeetingCommitment(meeting_id=meeting.id, user_id=actor,
                    start_at=meeting.start_at, end_at=meeting.end_at) for actor in (1, 2))
            event = GroupMeetingEvent(meeting_id=meeting.id, actor_id=1, revision=1, message="Meeting requested.")
            publish_event(session, event)
            return meeting.id, event.id

    def events(self, actor, scope="relevant"):
        return self.calendar.load(actor, view="day", day="2030-01-07", categories=["appointment"],
            scope=scope, now=START - timedelta(minutes=5))["events"]

    def timetable(self, actor):
        return self.personal.load(actor, week="2030-01-07", now=START)["days"][0]["entries"]

    def test_inbox_filters_and_links_require_recipient_membership(self):
        meeting_id, event_id = self.meeting()
        with self.database.transaction() as session:
            session.add(Notification(recipient_id=5, group_meeting_event_id=event_id))

        for participant in (2, 4):
            page = self.inbox.inbox_page(participant, kind="group_meeting", read_state="unread")
            self.assertEqual(page["kinds"]["group_meeting"], "Group meetings")
            self.assertEqual(page["unreadCount"], 1)
            self.assertEqual(page["items"][0]["subject_id"], meeting_id)
        app = Flask(__name__)
        routes = Blueprint("group_meetings", __name__)
        routes.add_url_rule("/meetings/<int:meeting_id>", endpoint="detail", view_func=lambda meeting_id: "")
        app.register_blueprint(routes)
        with app.test_request_context():
            self.assertEqual(add_notification_urls(page)["items"][0]["url"], f"/meetings/{meeting_id}")

        key = page["items"][0]["id"]
        for outsider in (1, 5):
            self.assertEqual(self.inbox.inbox(outsider)["unreadCount"], 0)
            with self.assertRaises(PermissionError):
                self.inbox.mark_read(outsider, notification_id=key)
        with self.database.transaction() as session:
            session.delete(session.get(GroupMeetingParticipant, (meeting_id, 4)))
        self.assertFalse(self.inbox.inbox(4)["items"])
        with self.assertRaises(PermissionError):
            self.inbox.mark_read(4, notification_id=key)
        remaining = self.inbox.inbox_page(2, kind="group_meeting")
        self.inbox.mark_read(2, through_id=remaining["throughId"], kind="group_meeting")
        self.assertEqual(self.inbox.inbox_page(2, kind="group_meeting", read_state="read")["unreadCount"], 0)
        self.assertTrue(self.inbox.inbox(2)["items"][0]["read_at"])
        with self.database.transaction() as session:
            event = GroupMeetingEvent(meeting_id=meeting_id, actor_id=1, revision=1, message="Scoped update")
            publish_event(session, event, recipient_ids=(2, 5))
            session.flush()
            self.assertEqual(list(session.scalars(select(Notification.recipient_id)
                .where(Notification.group_meeting_event_id == event.id))), [2])

    def test_private_calendar_entries_respect_optional_attendance(self):
        key, _ = self.meeting(confirmed=True)
        for actor in (1, 2):
            event, = self.events(actor)
            self.assertTrue(event["busy"])
            self.assertEqual(event["url"], f"/meetings/{key}")
            self.assertEqual(event["location"], "Online")
            self.assertEqual(self.timetable(actor)[0]["groupMeetingId"], key)
        app = Flask(__name__, template_folder=str(ROOT / "web/templates"))
        app.add_url_rule("/meetings/<int:meeting_id>", endpoint="group_meetings.detail", view_func=lambda meeting_id: "")
        app.add_url_rule("/appointments/calendar", endpoint="appointments.calendar", view_func=lambda: "")
        app.jinja_env.globals["timedelta"] = timedelta
        with app.test_request_context():
            schedule = self.personal.load(2, week="2030-01-07", now=START)
            markup = render_template_string(
                "{% from '_personal_timetable.html' import timetable %}{{ timetable(schedule, 'appointments.calendar', true) }}",
                schedule=schedule)
        self.assertIn(f'href="/meetings/{key}">Synthetic pilot meeting</a>', markup)
        event, = self.events(4)
        self.assertEqual(event["state"], "pending")
        self.assertFalse(event["busy"])
        self.assertFalse(self.timetable(4))
        with self.database.transaction() as session:
            session.get(GroupMeetingParticipant, (key, 4)).decision = "Accepted"
        event, = self.events(4)
        self.assertEqual(event["state"], "confirmed")
        self.assertFalse(event["busy"])
        self.assertEqual(self.timetable(4)[0]["kind"], "Optional invitation")
        with self.database.transaction() as session:
            session.get(GroupMeetingParticipant, (key, 4)).decision = "Declined"
        self.assertEqual(self.events(4)[0]["state"], "rejected")
        self.assertFalse(self.timetable(4))
        self.assertFalse(self.events(5))
        self.assertFalse(self.events(1, scope="published"))

    def test_disabled_context_hides_pilot_and_rejects_group_publication(self):
        key, _ = self.meeting(confirmed=True, optional="Accepted")
        self.database.sessions.configure(info={})
        self.assertNotIn("group_meeting", self.inbox.inbox_page(2)["kinds"])
        self.assertFalse(self.inbox.inbox(2)["items"])
        with self.assertRaises(ValueError):
            self.inbox.inbox_page(2, kind="group_meeting")
        self.assertFalse(self.events(2))
        self.assertFalse(self.timetable(2))
        with self.database.transaction() as session, self.assertRaises(PermissionError):
            publish_event(session, GroupMeetingEvent(meeting_id=key, actor_id=1, revision=1,
                message="Outside pilot"))
        with self.database.transaction(read_only=True) as session:
            self.assertIsNone(session.scalar(select(GroupMeetingEvent.id)
                .where(GroupMeetingEvent.message == "Outside pilot")))
