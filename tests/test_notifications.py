"""Private shared-shell notifications with real PostgreSQL and real workflows."""

from datetime import timedelta
from unittest import mock
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from auth_fixtures import authorized_client
from test_room_requests import RoomFixture, START
from web import app as web_app
from web.notification_service import NotificationService
from web.persistence.database import Database
from web.persistence.models import Notification, RoomEvent, RoomInvitation


class NotificationTests(RoomFixture):
    def setUp(self):
        super().setUp()
        self.notifications = NotificationService(self.database)

    def test_pending_requests_notify_only_assigned_approver_and_invitees(self):
        key=self.request_room(invitees=(2,))
        for actor in (2,7):
            box=self.notifications.inbox(actor)
            self.assertEqual(box['unreadCount'],1)
            self.assertEqual(box['items'][0]['subject_id'],key)
        for actor in (1,4,6):
            self.assertEqual(self.notifications.inbox(actor)['unreadCount'],0)

    def test_room_decisions_responses_and_cancel_notify_relevant_people(self):
        key=self.request_room(invitees=(2,))
        self.rooms.decide(key,7,1,False,'Activity not approved')
        self.assertIn('Rejected',self.notifications.inbox(1)['items'][0]['message'])
        self.rooms.submit(1,self.values(start=START+timedelta(hours=1)),[2],302,key,1)
        self.rooms.decide(key,7,2,True)
        self.assertIn('Confirmed',self.notifications.inbox(1)['items'][0]['message'])
        self.rooms.respond(key,2,2,False)
        self.assertIn('declined',self.notifications.inbox(1)['items'][0]['message'])
        self.rooms.cancel(key,1,2)
        self.assertIn('Cancelled',self.notifications.inbox(7)['items'][0]['message'])

    def test_appointment_approval_rejection_and_cancellation_are_not_parsed(self):
        key=self.service.submit(1,[2,3],[4],'Appointment update',60,START,self.faculty)
        self.assertEqual(self.notifications.inbox(2)['unreadCount'],1)
        self.service.decide(key,2,1,True)
        self.assertIn('approved',self.notifications.inbox(1)['items'][0]['message'])
        self.service.decide(key,3,1,False)
        self.assertIn('declined',self.notifications.inbox(1)['items'][0]['message'])
        self.service.cancel(key,1,1)
        self.assertIn('Cancelled',self.notifications.inbox(4)['items'][0]['message'])
        self.assertFalse(self.notifications.inbox(6)['items'])

    def test_read_state_survives_restart_is_idempotent_and_does_not_read_new_arrivals(self):
        key=self.request_room()
        before=self.notifications.inbox(7)
        first=before['items'][0]['id']
        self.notifications.mark_read(7,notification_id=first)
        self.notifications.mark_read(7,notification_id=first)
        another=Database(self.url)
        try: self.assertEqual(NotificationService(another).inbox(7)['unreadCount'],0)
        finally: another.dispose()
        self.rooms.cancel(key,1,1)
        self.notifications.mark_read(7,through_id=before['throughId'])
        self.assertEqual(self.notifications.inbox(7)['unreadCount'],1)

    def test_removed_invitees_lose_notification_detail_and_read_access(self):
        key=self.request_room(invitees=(2,))
        notification=self.notifications.inbox(2)['items'][0]['id']
        self.rooms.submit(1,self.values(),[3],302,key,1)
        self.assertEqual(self.notifications.inbox(2)['unreadCount'],0)
        self.assertFalse(self.notifications.inbox(2)['items'])
        with self.assertRaises(PermissionError): self.notifications.mark_read(2,notification_id=notification)
        self.assertEqual(self.notifications.inbox(3)['unreadCount'],1)

    def test_notification_failure_rolls_back_request_history_and_reservations(self):
        from web.notification_service import publish_event
        def fail_after_history_and_inbox(session, event):
            publish_event(session, event)
            raise RuntimeError('injected inbox failure')
        with mock.patch('web.room_request_service.publish_event',side_effect=fail_after_history_and_inbox):
            with self.assertRaises(RuntimeError): self.request_room()
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Notification)),0)
            self.assertEqual(session.scalar(select(func.count()).select_from(RoomEvent)),0)
        self.assertEqual(self.totals(),(0,0))

    def test_notification_sources_and_recipients_are_constrained(self):
        key=self.request_room()
        with self.database.transaction(read_only=True) as session:
            event=session.scalar(select(RoomEvent.id).where(RoomEvent.request_id == key))
        for row in (Notification(recipient_id=7),Notification(recipient_id=99999,room_event_id=event),Notification(recipient_id=7,room_event_id=event)):
            with self.assertRaises(IntegrityError),self.database.transaction() as session: session.add(row)

    def test_feed_html_is_escaped_private_and_csrf_protected(self):
        self.request_room(purpose='<script>private activity</script>',invitees=(2,))
        self.configure_web()
        client=authorized_client(web_app.app,7,1)
        feed=client.get('/notifications/feed?userId=1')
        self.assertEqual(feed.status_code,200)
        self.assertEqual(feed.headers['Cache-Control'],'no-store')
        self.assertIn('&lt;script&gt;',feed.json['html'])
        self.assertNotIn('<script>',feed.json['html'])
        self.assertEqual(authorized_client(web_app.app,4,1).get('/notifications/feed').json['unreadCount'],0)
        self.assertEqual(client.client.post('/notifications/read',data={'throughId':'99'}).status_code,400)
        self.assertEqual(client.post('/notifications/read',data={'throughId':str(feed.json['throughId'])}).status_code,302)
        self.assertEqual(client.get('/notifications/feed').json['unreadCount'],0)
        self.assertEqual(web_app.app.test_client().get('/notifications/feed').status_code,302)

    def test_other_user_cannot_read_notification_and_bad_identifiers_fail_safely(self):
        self.request_room()
        key=self.notifications.inbox(7)['items'][0]['id']
        with self.assertRaises(PermissionError): self.notifications.mark_read(4,notification_id=key)
        for value in (-1,True,'1',9223372036854775808):
            with self.assertRaises(ValueError): self.notifications.mark_read(7,through_id=value)

    def test_shared_header_is_role_based_without_granting_backend_permissions(self):
        self.configure_web()
        for actor,role in ((1,'Student'),(2,'Professor'),(6,'Administrator'),(7,'Staff')):
            client=authorized_client(web_app.app,actor,1)
            page=client.get('/notifications/').get_data(as_text=True)
            self.assertIn('profile-avatar',page)
            self.assertIn(role,page)
            self.assertIn('notification-toggle',page)
            self.assertEqual('href="/appointments/availability"' in page,actor == 2)
            self.assertEqual('class="app-admin-navigation"' in page,actor == 6)
            if actor != 6: self.assertEqual(client.get('/users').status_code,403)


class NotificationUpgradeTests(RoomFixture):
    def test_existing_history_is_backfilled_without_duplicate_or_broadcast(self):
        from alembic import command
        from alembic.config import Config
        from postgres_fixtures import ROOT
        import os
        # Only this owned test schema is downgraded; its inbox is still empty.
        with mock.patch.dict(os.environ,{'DATABASE_URL':self.url}):
            command.downgrade(Config(str(ROOT/'alembic.ini')),'0043b')
        with self.database.transaction() as session:
            # Reflect the historical schema: current ORM defaults may reference
            # columns deliberately absent before this upgrade.
            from sqlalchemy import MetaData,Table
            legacy=Table('student_room_request',MetaData(),autoload_with=session.connection())
            key=session.execute(legacy.insert().values(organizer_id=1,resource_id=302,faculty_id=self.other_faculty,approver_id=7,
                category='study',purpose='Existing private room request',description='',club_affiliation='',preferred_building='',
                attendee_count=5,required_features=[],start_at=START,end_at=START+timedelta(hours=1),duration_minutes=60,
                revision=1,status='Pending Faculty Approval',explanation='')).inserted_primary_key[0]
            session.add(RoomInvitation(request_id=key,user_id=2,revision=1))
            session.add(RoomEvent(request_id=key,actor_id=1,revision=1,message='Existing submitted event'))
        with mock.patch.dict(os.environ,{'DATABASE_URL':self.url}):
            command.upgrade(Config(str(ROOT/'alembic.ini')),'head')
            command.upgrade(Config(str(ROOT/'alembic.ini')),'head')
        inbox=NotificationService(self.database)
        self.assertEqual(inbox.inbox(7)['unreadCount'],1)
        self.assertEqual(inbox.inbox(2)['unreadCount'],1)
        for actor in (1,4,6): self.assertEqual(inbox.inbox(actor)['unreadCount'],0)
