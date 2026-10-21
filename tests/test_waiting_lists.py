"""Real PostgreSQL/engine waiting queues; no duplicate booking implementation."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import multiprocessing
import re
import uuid
from unittest import mock

from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError

from auth_fixtures import authorized_client
from postgres_fixtures import ROOT
from runtime_file_guard import forbid_runtime_files
from test_appointments import START
from test_equipment import EquipmentFixture
from test_room_requests import RoomFixture
from web.engine_gateway import EngineGateway, EngineIntegrationError
from web.notification_service import NotificationService
from web.persistence.database import Database
from web.persistence.models import (ApplicationState, BorrowRequest, EquipmentReservation,
    RoomEvent, WaitingListEntry)
from web.waiting_list_service import POLICY_VERSION, WaitingListError, WaitingListService


def process_queue(url, kind, faculty, output):
    database = Database(url)
    try:
        output.put(WaitingListService(database, EngineGateway(ROOT)).process(kind, faculty))
    except Exception as error:
        output.put(type(error).__name__)
    finally:
        database.dispose()


class WaitingRoomTests(RoomFixture):
    def setUp(self):
        super().setUp()
        self.waiting = WaitingListService(self.database, EngineGateway(ROOT))
        self.waiting.configure_notice(6, 60)
        for room in (301, 302, 303):
            self.rooms.close_room(6, room, START, START + timedelta(hours=1), 'Fictional temporary occupancy')

    def join(self, actor=1, key=None, **changes):
        return self.waiting.join_room(actor, self.values(**changes), [], self.other_faculty,
            POLICY_VERSION, True, key or uuid.uuid4().hex)

    def open_room(self):
        from web.persistence.models import RoomClosure
        with self.database.transaction(read_only=True) as session:
            key = session.scalar(select(RoomClosure.id).where(RoomClosure.resource_id == 302))
        self.rooms.reopen_room(6, key)

    def test_consent_required_and_no_unexplained_defaults(self):
        for version, consent in [(POLICY_VERSION, False), ('old', True)]:
            with self.assertRaises(WaitingListError):
                self.waiting.join_room(1, self.values(), [], self.other_faculty, version, consent, uuid.uuid4().hex)
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(WaitingListEntry)), 0)
        with self.assertRaises(PermissionError): self.waiting.configure_notice(1, 1)
        for value in (None, 0, -1, True):
            with self.assertRaises(WaitingListError): self.waiting.configure_notice(6, value)

    def test_join_is_idempotent_and_preapproval_holds_nothing(self):
        key = uuid.uuid4().hex
        first = self.join(key=key)
        self.assertEqual(self.join(key=key), first)
        self.assertEqual(self.waiting.detail(first, 1)['position'], 1)
        self.assertEqual(self.totals(), (0, 0))
        self.waiting.review(first, 7, True)
        self.assertEqual(self.waiting.detail(first, 1)['status'], 'Preapproved')
        self.assertEqual(self.totals(), (0, 0))
        with self.assertRaises(WaitingListError): self.join(key=key, count=7)

    def test_only_current_owning_faculty_can_review_or_inspect(self):
        key = self.join()
        for actor in (4, 6, 2):
            with self.assertRaises(PermissionError): self.waiting.review(key, actor, True)
            with self.assertRaises(PermissionError): self.waiting.detail(key, actor)
        self.assertEqual(self.waiting.list_for(4), [])
        self.assertEqual(len(self.waiting.list_for(7)), 1)
        self.waiting.review(key, 7, False, 'Not an eligible university activity')
        self.assertEqual(self.waiting.detail(key, 1)['status'], 'Rejected')
        self.assertIsNone(self.waiting.detail(key, 1)['position'])
        self.assertEqual(self.totals(), (0, 0))

    def test_room_reopening_automatically_confirms_fcfs_without_second_acceptance(self):
        first, second = self.join(), self.join(actor=4)
        self.waiting.review(first, 7, True)
        self.waiting.review(second, 7, True)
        self.assertEqual(self.waiting.detail(second, 4)['position'], 2)
        self.open_room()
        winner = self.waiting.detail(first, 1)
        self.assertEqual(winner['status'], 'Assigned')
        self.assertEqual(self.waiting.detail(second, 4)['status'], 'Preapproved')
        parent = self.rooms.detail(winner['requestId'], 1)
        self.assertEqual((parent['status'], parent['roomId'], parent['start'], parent['count']), ('Confirmed', 302, START, 5))
        self.assertEqual(self.totals(), (1, 1))
        self.rooms.cancel(parent['id'], 1, 1)
        self.assertEqual(self.waiting.detail(second, 4)['status'], 'Assigned')
        self.assertEqual(self.totals(), (1, 1))

    def test_queue_cancellation_updates_positions_and_milestones_once(self):
        keys = [self.join(actor=actor) for actor in (1, 4)]
        for key in keys: self.waiting.review(key, 7, True)
        self.waiting.process('room', self.other_faculty)
        self.waiting.cancel(keys[0], 1)
        self.waiting.cancel(keys[0], 1)
        self.waiting.process('room', self.other_faculty)
        self.assertEqual(self.waiting.detail(keys[1], 4)['position'], 1)
        with self.database.transaction(read_only=True) as session:
            parent = session.get(WaitingListEntry, keys[1]).room_request_id
            messages = list(session.scalars(select(RoomEvent.message).where(RoomEvent.request_id == parent)))
        self.assertEqual(sum('First entry into the top three' in m for m in messages), 1)
        self.assertEqual(sum('You reached eligible waiting position one' in m for m in messages), 1)
        self.assertTrue(any('Joined waiting list' in row['message'] for row in NotificationService(self.database).inbox(4)['items']))

    def test_direct_approval_and_revision_cannot_bypass_waiting_review(self):
        key = self.join()
        parent = self.waiting.detail(key, 1)['requestId']
        from web.calendar_service import CalendarError
        with self.assertRaises(CalendarError): self.rooms.decide(parent, 7, 1, True)
        with self.assertRaises(CalendarError): self.rooms.submit(1, self.values(), [], 302, parent, 1)
        self.rooms.cancel(parent, 1, 1)
        self.assertEqual(self.waiting.detail(key, 1)['status'], 'Cancelled')

    def test_missing_notice_or_late_availability_never_confirms(self):
        with self.database.transaction() as session:
            session.get(ApplicationState, 1).waiting_notice_minutes = None
        key = self.join()
        self.waiting.review(key, 7, True)
        self.open_room()
        self.assertEqual(self.totals(), (0, 0))
        self.assertIn('disabled', self.waiting.detail(key, 1)['explanation'])
        late = WaitingListService(self.database, EngineGateway(ROOT), clock=lambda: START-timedelta(minutes=10))
        late.configure_notice(6, 60)
        late.process('room', self.other_faculty)
        self.assertEqual(self.totals(), (0, 0))
        self.assertIn('advance notice', late.detail(key, 1)['explanation'])
        expired = WaitingListService(self.database, EngineGateway(ROOT), clock=lambda: START)
        expired.process('room', self.other_faculty)
        self.assertEqual(expired.detail(key, 1)['status'], 'Expired')

    def test_eligibility_change_and_staff_replacement_cannot_use_old_authority(self):
        key = self.join()
        self.waiting.review(key, 7, True)
        self.rooms.configure_approver(6, self.other_faculty, 6)
        self.waiting.process('room', self.other_faculty)
        self.assertEqual(self.waiting.detail(key, 1)['status'], 'Pending Review')
        with self.assertRaises(PermissionError): self.waiting.review(key, 7, True)
        self.waiting.review(key, 6, True)
        self.rooms.configure_room(6, 302, self.other_faculty, False, ['study'])
        self.waiting.process('room', self.other_faculty)
        self.assertEqual(self.waiting.detail(key, 1)['status'], 'Ineligible')

    def test_incompatible_requirements_have_contextual_not_global_positions(self):
        first = self.join()
        other = self.join(actor=4, count=7)
        self.assertEqual(self.waiting.detail(first, 1)['position'], 1)
        self.assertEqual(self.waiting.detail(other, 4)['position'], 1)

    def test_fourth_entry_is_notified_once_when_entering_top_three(self):
        from web.account_service import AccountService
        from web.persistence.models import Role, User
        with self.database.transaction() as session:
            role = session.scalar(select(Role.id).where(Role.name == 'Student'))
            session.add(User(id=8, source_order=8, name='Fictional waiting student', primary_role_id=role))
        AccountService(self.database).provision(5, 'waiting-five', 'Fictional-isolated-password')
        AccountService(self.database).provision(8, 'waiting-eight', 'Fictional-isolated-password')
        keys = [self.join(actor=actor) for actor in (1, 4, 5, 8)]
        for key in keys: self.waiting.review(key, 7, True)
        with self.database.transaction(read_only=True) as session:
            self.assertFalse(session.get(WaitingListEntry, keys[3]).top_three_notified)
        self.waiting.cancel(keys[0], 1)
        self.waiting.process('room', self.other_faculty)
        self.assertEqual(self.waiting.detail(keys[3], 8)['position'], 3)
        with self.database.transaction(read_only=True) as session:
            parent = session.get(WaitingListEntry, keys[3]).room_request_id
            messages = list(session.scalars(select(RoomEvent.message).where(RoomEvent.request_id == parent)))
        self.assertEqual(sum('First entry into the top three' in m for m in messages), 1)

    def test_revoked_consent_or_disabled_student_cannot_be_automatically_booked(self):
        from web.persistence.models import LoginAccount
        first, second = self.join(), self.join(actor=4)
        for key in (first, second): self.waiting.review(key, 7, True)
        with self.database.transaction() as session:
            session.get(WaitingListEntry, first).policy_version = 'outdated-policy'
            session.get(LoginAccount, 4).enabled = False
        self.open_room()
        self.assertEqual(self.totals(), (0, 0))
        with self.database.transaction(read_only=True) as session:
            self.assertEqual([session.get(WaitingListEntry, key).status for key in (first, second)], ['Ineligible', 'Ineligible'])

    def test_available_or_intrinsically_ineligible_room_requests_cannot_join(self):
        with self.assertRaises(WaitingListError): self.join(count=999)
        self.open_room()
        with self.assertRaises(WaitingListError): self.join()

    def test_optional_professor_gets_assignment_not_private_queue_positions(self):
        key = self.waiting.join_room(1, self.values(), [2], self.other_faculty, POLICY_VERSION, True, uuid.uuid4().hex)
        self.waiting.review(key, 7, True)
        self.assertFalse(any('waiting position' in row['message'] for row in NotificationService(self.database).inbox(2)['items']))
        with self.assertRaises(PermissionError): self.waiting.detail(key, 2)
        self.open_room()
        self.assertTrue(any('Automatically assigned' in row['message'] for row in NotificationService(self.database).inbox(2)['items']))
        self.assertFalse(any('position one' in row['message'] for row in NotificationService(self.database).inbox(2)['items']))

    def test_academic_publication_rechecks_newly_freed_rooms(self):
        from web.allocation_workflow import execute_allocation
        from web.persistence.models import RoomClosure, RequestSlot
        from web.persistence.repository import state_row
        with self.database.transaction() as session:
            session.delete(session.scalar(select(RoomClosure).where(RoomClosure.resource_id == 302)))
        repository = self.academic(room=302)
        execute_allocation(repository, EngineGateway(ROOT))
        key = self.join()
        self.waiting.review(key, 7, True)
        self.assertEqual(self.waiting.detail(key, 1)['status'], 'Preapproved')
        with self.database.transaction() as session:
            session.scalar(select(RequestSlot)).day = 2  # Explicit fixture move to Tuesday.
            state_row(session, True).input_revision += 1
        execute_allocation(repository, EngineGateway(ROOT))
        self.assertEqual(self.waiting.detail(key, 1)['status'], 'Assigned')
        self.assertEqual(self.totals(), (1, 1))

    def test_engine_failure_rolls_back_publication_and_keeps_release_committed(self):
        key = self.join()
        self.waiting.review(key, 7, True)
        with mock.patch.object(self.rooms.gateway, 'execute_room', side_effect=EngineIntegrationError('fixture failure')):
            with self.assertLogs('web.waiting_list_state', level='ERROR'): self.open_room()
        self.assertEqual(self.waiting.detail(key, 1)['status'], 'Preapproved')
        self.assertEqual(self.totals(), (0, 0))
        self.waiting.process('room', self.other_faculty)
        self.assertEqual(self.waiting.detail(key, 1)['status'], 'Assigned')

    def test_flask_join_review_privacy_csrf_and_existing_calendar(self):
        from web import app as web_app
        self.configure_web()
        student = authorized_client(web_app.app, 1)
        data = {'action': 'wait', 'category': 'study', 'count': '5', 'purpose': 'Private waiting activity',
            'start': '2030-01-07T10:00', 'duration': '60', 'waitingFaculty': str(self.other_faculty),
            'policyVersion': POLICY_VERSION, 'acceptWaiting': 'yes', 'submission_key': uuid.uuid4().hex}
        with forbid_runtime_files():
            for path in ('/rooms/new', '/waiting-lists/', '/waiting-lists/policy', '/calendar/?date=2030-01-07'):
                self.assertEqual(student.get(path).status_code, 200, path)
            response = student.post('/rooms/new', data=data)
            self.assertEqual(response.status_code, 302)
            url = response.location
            self.assertEqual(student.post('/rooms/new', data=data).location, url)
            detail = student.get(url)
            self.assertIn(b'Estimated position 1', detail.data)
            outsider = authorized_client(web_app.app, 4)
            self.assertEqual(outsider.get(url).status_code, 403)
            self.assertNotIn(b'Private waiting activity', outsider.get('/waiting-lists/').data)
            self.assertEqual(student.post(url+'/review', data={'decision': 'approve'}).status_code, 403)
            staff = authorized_client(web_app.app, 7)
            self.assertEqual(staff.post(url+'/review', data={'decision': 'approve'}).status_code, 302)
            self.assertIn(b'Eligible position 1', student.get(url).data)
            self.assertEqual(student.get('/waiting-lists/configuration').status_code, 403)
            self.assertEqual(staff.get('/waiting-lists/configuration').status_code, 403)
            admin = authorized_client(web_app.app, 6)
            self.assertEqual(admin.post('/waiting-lists/configuration', data={'noticeMinutes': '90'}).status_code, 302)
            with student.session_transaction() as session: session.pop('csrf', None)
            self.assertEqual(student.post(url+'/cancel').status_code, 400)
        self.assertEqual(web_app.app.test_client().get('/waiting-lists/').status_code, 302)

    def test_real_sign_in_and_sign_out_preserve_waiting_review_notification_status(self):
        from web import app as web_app
        self.configure_web()
        client = web_app.app.test_client()

        def csrf(response):
            match = re.search(r'name="csrf_token" value="([^"]+)"', response.get_data(as_text=True))
            self.assertIsNotNone(match)
            return match.group(1)

        def login(actor):
            token = csrf(client.get('/login'))
            response = client.post('/login', data={'csrf_token': token,
                'username': 'room-fixture-' + str(actor), 'password': 'Fictional-isolated-password'})
            self.assertEqual(response.status_code, 302)
            self.assertNotIn('/login', response.location)

        login(1)
        page = client.get('/rooms/new')
        self.assertIn(b'Fictional Arts Faculty', page.data)
        values = {'csrf_token': csrf(page), 'category': 'study', 'count': '5',
            'purpose': 'Real sign-in waiting-list check', 'start': '2030-01-07T10:00',
            'duration': '60', 'waitingFaculty': str(self.other_faculty),
            'policyVersion': POLICY_VERSION, 'submission_key': uuid.uuid4().hex}
        result = client.post('/rooms/candidates', data=values)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['candidates'], [])
        self.assertEqual(client.get('/waiting-lists/policy').status_code, 200)
        values.update(action='wait', acceptWaiting='yes')
        joined = client.post('/rooms/new', data=values)
        self.assertEqual(joined.status_code, 302)
        path = joined.location
        page = client.get(path)
        self.assertIn(b'Pending Review', page.data)
        self.assertEqual(client.post('/logout', data={'csrf_token': csrf(page)}).status_code, 302)
        self.assertEqual(client.get(path).status_code, 302)

        login(7)
        self.assertIn(values['purpose'].encode(), client.get('/waiting-lists/').data)
        self.assertIn('Joined waiting list', client.get('/notifications/feed').json['html'])
        page = client.get(path)
        reviewed = client.post(path + '/review', data={'csrf_token': csrf(page),
            'decision': 'approve', 'reason': 'Faculty review completed'})
        self.assertEqual(reviewed.status_code, 302)
        page = client.get(path)
        self.assertIn(b'Preapproved', page.data)
        self.assertNotIn(b'<h2>Pending Review</h2>', page.data)
        client.post('/logout', data={'csrf_token': csrf(page)})

        login(1)
        self.assertIn(b'Eligible position 1', client.get(path).data)
        feed = client.get('/notifications/feed').json['html']
        self.assertIn('Current status: Waiting list: Preapproved', feed)
        self.assertNotIn('Current status: Pending Faculty Approval', feed)
        self.assertEqual(self.totals(), (0, 0))
        with self.database.transaction(read_only=True) as session:
            entry = session.scalar(select(WaitingListEntry))
            parent = entry.room_request_id
            self.assertEqual((entry.status, entry.approved_by), ('Preapproved', 7))
            self.assertGreaterEqual(session.scalar(select(func.count()).select_from(RoomEvent)
                .where(RoomEvent.request_id == entry.room_request_id)), 2)
        self.assertIn(b'<h2>Waiting list: Preapproved</h2>', client.get('/rooms/' + str(parent)).data)
        self.open_room()
        feed = client.get('/notifications/feed').json['html']
        self.assertIn('Current status: Confirmed', feed)
        self.assertNotIn('Current status: Waiting list:', feed)
        self.assertEqual(self.totals(), (1, 1))

    def test_room_competing_processes_assign_only_once(self):
        first, second = self.join(), self.join(actor=4)
        self.waiting.review(first, 7, True)
        self.waiting.review(second, 7, True)
        from web.persistence.models import RoomClosure
        with self.database.transaction() as session:
            session.delete(session.scalar(select(RoomClosure).where(RoomClosure.resource_id == 302)))
        context = multiprocessing.get_context('spawn')
        output = context.Queue()
        workers = [context.Process(target=process_queue, args=(self.url, 'room', self.other_faculty, output)) for _ in range(2)]
        for worker in workers: worker.start()
        for worker in workers:
            worker.join(60)
            self.assertEqual(worker.exitcode, 0)
        results = [output.get(timeout=5) for _ in workers]
        self.assertTrue(all(isinstance(result, list) for result in results), results)
        self.assertEqual(sum(len(result) for result in results), 1)
        self.assertEqual(self.waiting.detail(first, 1)['status'], 'Assigned')
        self.assertEqual(self.totals(), (1, 1))


class WaitingEquipmentTests(EquipmentFixture):
    def setUp(self):
        super().setUp()
        self.waiting = WaitingListService(self.database, EngineGateway(ROOT))
        self.waiting.configure_notice(6, 60)
        self.blocker = self.request(quantity=2, actor=4)
        self.service.decide(6, self.blocker, True)

    def join(self, actor=1, key=None, quantity=1):
        return self.waiting.join_equipment(actor, self.faculty, [{'typeId': self.type_id, 'quantity': quantity}],
            START, START+timedelta(days=3), 'Fictional waiting project', '', POLICY_VERSION, True, key or uuid.uuid4().hex)

    def test_equipment_release_promotes_one_full_fcfs_request_and_keeps_handover_separate(self):
        first, second = self.join(quantity=2), self.join(actor=5)
        self.waiting.review(first, 6, True)
        self.waiting.review(second, 6, True)
        self.service.cancel(4, self.blocker)
        entry = self.waiting.detail(first, 1)
        self.assertEqual(entry['status'], 'Assigned')
        loan = self.service.detail(1, entry['requestId'])
        self.assertEqual((loan['status'], len(loan['units'])), ('Approved', 2))
        self.assertTrue(all(u['handed'] is None for u in loan['units']))
        self.assertEqual(self.waiting.detail(second, 5)['status'], 'Preapproved')

    def test_verified_return_not_intent_or_due_date_releases_equipment(self):
        self.handover(self.blocker)
        # A future reservation never assumes that a currently held unit was returned.
        key = self.join()
        self.waiting.review(key, 6, True)
        self.service.intend_return(4, self.blocker)
        self.waiting.process('equipment', self.faculty)
        self.assertEqual(self.waiting.detail(key, 1)['status'], 'Preapproved')
        self.return_units(self.blocker, [self.units[0]], 'usable', 'Verified physically')
        self.assertEqual(self.waiting.detail(key, 1)['status'], 'Assigned')
        self.assertEqual(self.service.detail(4, self.blocker)['status'], 'Partially Returned')

    def test_damaged_return_does_not_allocate_and_repair_triggers_recheck(self):
        self.handover(self.blocker)
        key = self.join(quantity=2)
        self.waiting.review(key, 6, True)
        self.return_units(self.blocker, self.units, 'damaged', 'Not usable')
        self.assertEqual(self.waiting.detail(key, 1)['status'], 'Preapproved')
        for unit in self.units: self.service.set_condition(6, unit, 'usable', 'Repair inspected')
        self.assertEqual(self.waiting.detail(key, 1)['status'], 'Assigned')

    def test_duplicate_submissions_threads_and_process_refresh_are_idempotent(self):
        identity = uuid.uuid4().hex
        with ThreadPoolExecutor(2) as workers:
            keys = list(workers.map(lambda _: self.join(key=identity, quantity=2), range(2)))
        self.assertEqual(keys[0], keys[1])
        key = keys[0]
        second = self.join(actor=5, quantity=2)
        self.waiting.review(key, 6, True)
        self.waiting.review(second, 6, True)
        # Release without callback to make both workers compete for the same snapshot.
        with self.database.transaction() as session:
            row = session.get(BorrowRequest, self.blocker)
            row.status = 'Cancelled'
            for booking in self.service._reservations(session, self.blocker): booking.released = True
        context = multiprocessing.get_context('spawn')
        output = context.Queue()
        processes = [context.Process(target=process_queue, args=(self.url, 'equipment', self.faculty, output)) for _ in range(2)]
        for process in processes: process.start()
        for process in processes:
            process.join(60)
            self.assertEqual(process.exitcode, 0)
        results = [output.get(timeout=5) for _ in processes]
        self.assertTrue(all(isinstance(row, list) for row in results), results)
        self.assertEqual(sum(len(row) for row in results), 1)
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(WaitingListEntry)), 2)
            self.assertEqual(session.scalar(select(func.count()).select_from(EquipmentReservation).where(EquipmentReservation.released.is_(False))), 2)
        self.assertEqual(self.waiting.detail(key, 1)['status'], 'Assigned')
        self.assertEqual(self.waiting.detail(second, 5)['status'], 'Preapproved')

    def test_database_rejects_parent_mismatch_and_active_direct_publication(self):
        key = self.join()
        with self.assertRaises(IntegrityError), self.database.transaction() as session:
            session.get(WaitingListEntry, key).owner_id = 5
        with self.assertRaises(IntegrityError), self.database.transaction() as session:
            parent = session.get(WaitingListEntry, key).borrow_request_id
            session.get(BorrowRequest, parent).status = 'Approved'

    def test_custodian_rejection_privacy_and_normal_approval_guard(self):
        key = self.join()
        entry = self.waiting.detail(key, 1)
        from web.calendar_service import CalendarError
        with self.assertRaises(CalendarError): self.service.decide(6, entry['requestId'], True)
        for actor in (2, 4):
            with self.assertRaises(PermissionError): self.waiting.detail(key, actor)
        self.waiting.review(key, 6, False, 'Borrowing purpose not approved')
        self.assertEqual(self.service.detail(1, entry['requestId'])['status'], 'Rejected')

    def test_existing_custodian_authorization_is_not_replaced_with_a_new_role_policy(self):
        # The existing account grant, not only the primary role label, defines
        # custodian authority. Waiting lists must preserve that existing policy.
        key = self.join(actor=6)
        self.assertTrue(self.waiting.detail(key, 6)['canReview'])
        self.waiting.review(key, 6, True)
        self.assertEqual(self.waiting.detail(key, 6)['status'], 'Preapproved')

    def test_other_faculty_custodian_is_denied_and_replacement_requires_new_review(self):
        from web.account_service import AccountService
        from web.persistence.models import OrganizationUnit, Role, User
        with self.database.transaction() as session:
            staff_role = session.scalar(select(Role.id).where(Role.name == 'Staff'))
            session.add_all(User(id=uid, source_order=uid, name='Fictional custodian '+str(uid), primary_role_id=staff_role) for uid in (7,8))
            other = OrganizationUnit(name='Fictional other equipment faculty', unit_type='Faculty')
            session.add(other); session.flush(); other_faculty = other.id
        for uid in (7,8): AccountService(self.database).provision(uid, 'other-custodian-'+str(uid), 'Fictional-isolated-password')
        self.service.assign_custodian(6, other_faculty, 8)
        key = self.join()
        self.waiting.review(key, 6, True)
        with self.assertRaises(PermissionError): self.waiting.review(key, 8, False, 'Wrong faculty')
        with self.assertRaises(PermissionError): self.waiting.detail(key, 8)
        self.service.assign_custodian(6, self.faculty, 7)
        self.assertEqual(self.waiting.detail(key, 1)['status'], 'Pending Review')
        with self.assertRaises(PermissionError): self.waiting.review(key, 6, True)
        self.waiting.review(key, 7, True)
        self.service.cancel(4, self.blocker)
        self.assertEqual(self.waiting.detail(key, 1)['status'], 'Assigned')

    def test_notice_change_cannot_overtake_in_flight_equipment_assignment(self):
        import threading
        from concurrent.futures import TimeoutError
        key = self.join()
        self.waiting.review(key, 6, True)
        with self.database.transaction() as session:
            session.get(BorrowRequest, self.blocker).status = 'Cancelled'
            for booking in self.service._reservations(session, self.blocker): booking.released = True
        entered, release = threading.Event(), threading.Event()
        execute = self.waiting.gateway.execute_equipment

        def pause(snapshot):
            entered.set()
            if not release.wait(10): raise RuntimeError('Fixture synchronization timed out')
            return execute(snapshot)

        with mock.patch.object(self.waiting.gateway, 'execute_equipment', side_effect=pause), ThreadPoolExecutor(2) as workers:
            processing = workers.submit(self.waiting.process, 'equipment', self.faculty)
            self.assertTrue(entered.wait(10))
            configuration = workers.submit(self.waiting.configure_notice, 6, 120)
            try:
                with self.assertRaises(TimeoutError): configuration.result(timeout=0.2)
            finally:
                release.set()
            self.assertEqual(processing.result(timeout=15), [key])
            configuration.result(timeout=15)
        self.assertEqual(self.waiting.detail(key, 1)['status'], 'Assigned')

    def test_migration_keeps_single_queue_and_can_upgrade_from_previous_head(self):
        self.assertIn('waiting_list_entry', inspect(self.database.engine).get_table_names())
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(text('select version_num from alembic_version')), '0047a')

    def test_equipment_flask_submission_and_staff_review_reuse_existing_forms(self):
        from web import app as web_app
        self.configure_web()
        student = authorized_client(web_app.app, 1)
        data = {'action': 'wait', 'faculty': str(self.faculty), 'qty_'+str(self.type_id): '1',
            'start': '2030-01-07T10:00', 'due': '2030-01-10T10:00', 'purpose': 'Waiting kit project',
            'policyVersion': POLICY_VERSION, 'acceptWaiting': 'yes', 'submission_key': uuid.uuid4().hex}
        with forbid_runtime_files():
            response = student.post('/equipment/catalog', data=data)
            self.assertEqual(response.status_code, 302)
            self.assertIn(b'Waiting kit project', student.get(response.location).data)
            staff = authorized_client(web_app.app, 6)
            self.assertEqual(staff.post(response.location+'/review', data={'decision': 'approve'}).status_code, 302)
            parent = self.waiting.list_for(1)[0]['requestId']
            normal = staff.get('/equipment/'+str(parent))
            self.assertEqual(normal.status_code, 200)
            self.assertNotIn(b'Approve and reserve</button>', normal.data)
            self.assertIn(b'View waiting-list review', normal.data)
            self.assertIn(b'Waiting list: Preapproved', normal.data)
            feed = student.get('/notifications/feed').json['html']
            self.assertIn('Current status: Waiting list: Preapproved', feed)
            self.assertNotIn('Current status: Pending Approval', feed)
            self.service.cancel(4, self.blocker)
            feed = student.get('/notifications/feed').json['html']
            self.assertIn('Current status: Approved', feed)
            self.assertNotIn('Current status: Waiting list:', feed)

    def test_additive_migration_downgrade_and_reupgrade_preserve_existing_loans(self):
        import os
        from alembic import command
        from alembic.config import Config
        with mock.patch.dict(os.environ, {'DATABASE_URL': self.url}):
            command.downgrade(Config(str(ROOT/'alembic.ini')), '0045a')
            self.assertNotIn('waiting_list_entry', inspect(self.database.engine).get_table_names())
            command.upgrade(Config(str(ROOT/'alembic.ini')), 'head')
            command.check(Config(str(ROOT/'alembic.ini')))
        self.assertEqual(self.service.detail(4, self.blocker)['status'], 'Approved')
