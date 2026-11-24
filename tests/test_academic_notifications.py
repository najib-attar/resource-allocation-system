"""Private eligibility notices from committed administrative reviews."""
from concurrent.futures import ThreadPoolExecutor
import os
from unittest import mock
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from auth_fixtures import authorized_client
from postgres_fixtures import ROOT
from test_professor_services import ProfessorFixture
from web import app as web_app
from web.academic_eligibility import EligibilityError, EligibilityService
from web.notification_service import NotificationService
from web.persistence.models import ApplicationState, EligibilityEvent, LoginAccount, Notification, RequestEligibility


class AcademicNotificationTests(ProfessorFixture):
    def setUp(self):
        super().setUp()
        self.review = EligibilityService(self.database)
        self.inbox = NotificationService(self.database)

    def submit(self, title='Synthetic academic conference'):
        values = dict(type='OneTime', spaceId=302, participantCount=6, title=title,
                      purpose='Teaching', slots=[dict(day=2, startMinutes=780, endMinutes=840)])
        result = self.professors.submit(2, values, uuid4().hex)
        return result

    def review_current(self, key, approve, reason):
        with self.database.transaction(read_only=True) as session:
            version = session.get(RequestEligibility, key).version
        return self.review.decide(6, key, 1, version, approve, reason)

    def test_exact_private_notice_for_each_decision_and_current_eligibility(self):
        key = self.submit('<Synthetic topic>')
        self.assertEqual(self.inbox.inbox(2)['unreadCount'], 0)
        self.review_current(key, True, 'Check approved')
        self.review_current(key, False, 'Second review changed the decision')
        data = self.inbox.inbox(2)
        self.assertEqual(data['unreadCount'], 2)
        new, old = data['items']
        self.assertEqual({n['kind'] for n in (new, old)}, {'eligibility'})
        self.assertTrue(all(n['current_status'] == 'Eligibility Rejected' for n in (new, old)))
        self.assertIn('Eligible for request revision 1', old['message'])
        for item, reason in ((old, 'Check approved'), (new, 'Second review changed the decision')):
            anchor = f"eligibility-review-{item['review_version']}"
            url = f'/professor/requests/{key}#{anchor}'
            with self.subTest(url=url):
                feed = self.client.get('/notifications/feed').json['html']
                self.assertIn(url, feed)
                self.assertIn('&lt;Synthetic topic&gt;', feed)
                home = self.client.get('/professor/')
                self.assertEqual(home.status_code, 200)
                self.assertIn(url, home.get_data(as_text=True))
                detail = self.client.get(url).get_data(as_text=True).split(f'id="{anchor}"', 1)[1].split('</li>', 1)[0]
                self.assertIn(reason, detail)
        affected = {1, 3, 4, 6, 7}
        for actor in affected:
            peer = authorized_client(web_app.app, actor)
            self.assertEqual(peer.get('/notifications/feed').json['unreadCount'], 0)
            self.assertEqual(peer.post('/notifications/read', data={'id': new['id']}).status_code, 403)
            self.assertEqual(peer.get(f'/professor/requests/{key}').status_code, 403)
        self.assertEqual(self.client.client.post('/notifications/read', data={'id': old['id']}).status_code, 400)
        for _ in range(2):
            self.assertEqual(self.client.post('/notifications/read', data={'id': old['id']}).status_code, 302)
        self.assertEqual(self.inbox.inbox(2)['unreadCount'], 1)
        with self.database.transaction(read_only=True) as session:
            notices = session.execute(select(Notification.recipient_id, EligibilityEvent.version).join(
                EligibilityEvent, EligibilityEvent.id == Notification.eligibility_event_id)).all()
            self.assertEqual(set(notices), {(2, new['review_version']), (2, old['review_version'])})
            self.assertIsNone(session.get(ApplicationState, 1).active_run_id)

    def test_revision_keeps_the_recorded_review_without_sending_another_notice(self):
        key = self.submit()
        self.review_current(key, True, 'Original eligibility reason')
        [original] = self.inbox.inbox(2)['items']
        self.professors.submit(2, dict(type='OneTime', spaceId=302, participantCount=6,
            title='Revised activity declaration', purpose='Teaching',
            slots=[dict(day=2, startMinutes=780, endMinutes=840)]), uuid4().hex, key=key, revision=1)
        [after] = self.inbox.inbox(2)['items']
        self.assertEqual(after['id'], original['id'])
        self.assertEqual(after['review_version'], original['review_version'])
        self.assertEqual(after['current_status'], 'Pending Eligibility Review')
        detail = self.client.get(f'/professor/requests/{key}').get_data(as_text=True)
        self.assertIn('Original eligibility reason', detail)

    def test_concurrent_stale_retry_notifies_once_and_disabled_account_loses_visibility(self):
        key = self.submit()
        with self.database.transaction(read_only=True) as session:
            version = session.get(RequestEligibility, key).version

        def decide():
            try:
                return self.review.decide(6, key, 1, version, True, 'Concurrent review')
            except EligibilityError:
                return 'Stale'

        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertCountEqual(executor.map(lambda _: decide(), range(2)), ['Eligible', 'Stale'])
        [receipt] = self.inbox.inbox(2)['items']
        with self.database.transaction() as session:
            session.get(LoginAccount, 2).enabled = False
        self.assertEqual(self.inbox.inbox(2)['items'], [])
        with self.assertRaises(PermissionError):
            self.inbox.mark_read(2, notification_id=receipt['id'])

    def test_notice_persistence_failure_rolls_back_review_and_audit(self):
        key = self.submit()
        with self.database.transaction(read_only=True) as session:
            version = session.get(RequestEligibility, key).version
            events = session.scalar(select(func.count()).select_from(EligibilityEvent))
        from sqlalchemy.orm import Session
        add = Session.add

        def reject_notice(session, row, *args, **kwargs):
            if isinstance(row, Notification):
                raise RuntimeError('Injected receipt storage failure')
            return add(session, row, *args, **kwargs)

        with mock.patch.object(Session, 'add', new=reject_notice), self.assertRaises(RuntimeError):
            self.review_current(key, True, 'Will be rolled back')
        with self.database.transaction(read_only=True) as session:
            meta = session.get(RequestEligibility, key)
            self.assertEqual((meta.status, meta.version), ('Pending Eligibility Review', version))
            self.assertEqual(session.scalar(select(func.count()).select_from(EligibilityEvent)), events)
        self.assertEqual(self.inbox.inbox(2)['items'], [])

    def test_upgrade_preserves_existing_notices_and_old_reviews_and_guarded_downgrade(self):
        key = self.submit()
        self.request_room(invitees=(2,))
        with mock.patch.dict(os.environ, {'DATABASE_URL': self.url}):
            config = Config(str(ROOT/'alembic.ini'))
            with self.database.transaction(read_only=True) as session:
                version = session.get(RequestEligibility, key).version
            command.downgrade(config, '0051b')
            # Reflect a 0051b review through the existing 0051a database audit trigger.
            with self.database.transaction() as session:
                session.execute(text("""
                    UPDATE request_eligibility
                       SET status='Eligible', version=version+1, reviewed_revision=1,
                           reviewer_id=6, reason='Previous review', decided_at=now()
                     WHERE request_id=:key
                    """), {'key': key})
            command.upgrade(config, 'head')
            self.assertEqual([n['kind'] for n in self.inbox.inbox(2)['items']], ['room'])
            self.review_current(key, False, 'New review after upgrade')
            with self.assertRaisesRegex(RuntimeError, 'preserve Inbox history'):
                command.downgrade(config, '0051b')
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(text('SELECT version_num FROM alembic_version')), self.head_revision)
            event_id = session.scalar(select(Notification.eligibility_event_id).where(
                Notification.eligibility_event_id.is_not(None)))
        with self.assertRaises(IntegrityError), self.database.transaction() as session:
            session.add(Notification(recipient_id=2, eligibility_event_id=event_id))
        self.assertCountEqual([n['kind'] for n in self.inbox.inbox(2)['items']], ['room', 'eligibility'])
