"""Instructor-owned academic reads against disposable PostgreSQL and the real engine."""
from datetime import date
from unittest import mock

from sqlalchemy import event, func, select

from auth_fixtures import authorized_client
from postgres_fixtures import ROOT
from test_room_requests import RoomFixture
from web import app as web_app
from web.account_service import AccountService
from web.allocation_workflow import execute_allocation
from web.engine_gateway import EngineGateway
from web.persistence.database import DatabaseBusy
from web.persistence.models import (Allocation, ApplicationState, Appointment, LoginAccount,
    Notification, RequestDecision, ResourceRequest, Role, User)
from web.persistence.repository import Repository
from web.professor_service import ProfessorRequestError, ProfessorService


class ProfessorFixture(RoomFixture):
    def setUp(self):
        super().setUp()
        self.configure_web()
        self.client = authorized_client(web_app.app, 2)
        self.professors = ProfessorService(self.database)
        self.repository = Repository(self.database)

    def academic_request(self, kind='OneTime', actor=2, day=1, **changes):
        value = dict(type=kind, requesterId=actor, spaceId=302, participantCount=5,
            title='Declared fictional academic activity', purpose='Synthetic academic request',
            slots=[dict(day=day, startMinutes=600, endMinutes=660)])
        if kind == 'Exam':
            value['exam'] = dict(courseCode='FIC101', courseName='Declared course',
                                 examType='Midterm', canSplitAcrossRooms=False)
        elif kind == 'Recurring':
            value['slots'].append(dict(day=day + 1, startMinutes=600, endMinutes=660))
        elif kind == 'CommitteeMeeting':
            value.update(spaceId=301, participants=[dict(userId=2, role='Supervisor'),
                                                   dict(userId=3, role='Participant')])
        value.update(changes)
        return self.repository.save_request(value)

    def publish(self):
        return execute_allocation(self.repository, EngineGateway(ROOT))


class ProfessorReadTests(ProfessorFixture):
    def test_empty_list_is_private_and_explains_blocked_intake(self):
        response = self.client.get('/professor/academic-requests')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Cache-Control'], 'private, no-store')
        data = response.get_json()
        self.assertEqual((data['items'], data['total'], data['publicationId']), ([], 0, None))
        for flag in ('creationEnabled', 'eligibilityReviewSupported', 'academicNotificationsSupported'):
            self.assertIs(data[flag], False)
        self.assertIn('not eligibility approval', ' '.join(data['warnings']))

    def test_all_four_types_are_owned_pending_with_validated_filters_and_pagination(self):
        keys = [self.academic_request(kind, day=day) for kind, day in
                [('OneTime', 1), ('Exam', 2), ('Recurring', 3), ('CommitteeMeeting', 5)]]
        self.academic_request(actor=3, day=6, title='OTHER PRIVATE TITLE')
        response = self.client.get('/professor/academic-requests?limit=2&offset=1')
        data = response.get_json()
        self.assertEqual(data['total'], 4)
        self.assertEqual([item['id'] for item in data['items']], list(reversed(keys))[1:3])
        self.assertNotIn('OTHER PRIVATE TITLE', response.get_data(as_text=True))
        for kind, key in zip(('OneTime', 'Exam', 'Recurring', 'CommitteeMeeting'), keys):
            selected = self.client.get('/professor/academic-requests?type=' + kind).get_json()['items']
            self.assertEqual([(i['id'], i['status']) for i in selected], [(key, 'Pending')])
        self.assertEqual(self.professors.list_for(2, status='Approved')['total'], 0)
        self.assertEqual(self.professors.list_for(2, offset=99)['items'], [])

    def test_detail_keeps_declarations_and_committee_separate_from_appointments(self):
        exam = self.academic_request('Exam')
        committee = self.academic_request('CommitteeMeeting', day=5)
        data = self.professors.detail(2, exam)['item']
        self.assertEqual(data['examDeclaration']['courseCode'], 'FIC101')
        self.assertFalse(data['examDeclaration']['canSplitAcrossRooms'])
        self.assertEqual(data['allocations'], [])
        data = self.professors.detail(2, committee)['item']
        self.assertEqual([(p['id'], p['declaredRole']) for p in data['participants']],
                         [(2, 'Supervisor'), (3, 'Participant')])
        self.assertEqual([h['kind'] for h in data['history']], ['saved'])
        self.assertIsNone(data['examDeclaration'])
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Appointment)), 0)
            self.assertEqual(session.scalar(select(func.count()).select_from(Notification)), 0)

    def test_active_real_engine_decisions_and_allocations_round_trip(self):
        approved = self.academic_request()
        rejected = self.academic_request('Exam', day=2, participantCount=999)
        self.publish()
        approved_item = self.client.get(f'/professor/academic-requests/{approved}').get_json()['item']
        rejected_item = self.professors.detail(2, rejected)['item']
        self.assertEqual(approved_item['status'], 'Approved')
        self.assertEqual(approved_item['allocations'][0]['resourceId'], 302)
        self.assertEqual(approved_item['allocations'][0]['assignedParticipants'], 5)
        self.assertEqual(rejected_item['status'], 'Rejected')
        self.assertTrue(rejected_item['decision']['reason'])
        self.assertEqual(rejected_item['allocations'], [])
        self.assertEqual(self.professors.list_for(2, status='Approved')['total'], 1)
        self.assertEqual(self.professors.list_for(2, status='Rejected')['total'], 1)
        with self.database.transaction(read_only=True) as session:
            run_id = session.get(ApplicationState, 1).active_run_id
            self.assertEqual(session.get(RequestDecision, (run_id, approved)).status, approved_item['status'])
            self.assertEqual(session.scalar(select(Allocation.resource_id).where(
                Allocation.run_id == run_id, Allocation.request_id == approved)), 302)

    def test_real_engine_results_for_exam_teaching_recurrence_and_committee(self):
        keys = {kind:self.academic_request(kind, day=day) for kind,day in
                [('OneTime',1),('Exam',2),('Recurring',3),('CommitteeMeeting',5)]}
        self.publish()
        for kind, key in keys.items():
            with self.subTest(kind=kind):
                item = self.professors.detail(2,key)['item']
                self.assertEqual(item['status'], 'Approved')
                self.assertEqual(len(item['allocations']), 2 if kind == 'Recurring' else 1)
                self.assertTrue(all(a['assignedParticipants'] == 5 for a in item['allocations']))
                self.assertEqual(len(item['participants']), 2 if kind == 'CommitteeMeeting' else 0)

    def test_changed_inputs_and_failed_run_keep_previous_active_results(self):
        key = self.academic_request()
        self.publish()
        old = self.professors.list_for(2)['publicationId']
        pending = self.academic_request(day=2)
        failed, _ = self.repository.start_run()
        self.repository.fail_run(failed, 'Synthetic failure; private engine diagnostic')
        data = self.professors.list_for(2)
        self.assertEqual(data['publicationId'], old)
        self.assertTrue(data['inputsChangedSincePublication'])
        self.assertEqual({i['id']: i['status'] for i in data['items']}, {key: 'Approved', pending: 'Pending'})
        self.assertNotIn('private engine diagnostic', str(data))

    def test_explicit_calendar_bindings_are_metadata_without_invented_dates(self):
        key = self.academic_request()
        self.publish()
        self.assertEqual(self.professors.detail(2, key)['item']['academicBindings'], [])
        self.service.bind_legacy('Fictional bound week', date(2030, 1, 7), date(2030, 1, 31),
                                 request_id=key, week_start=date(2030, 1, 7))
        data = self.professors.detail(2, key)['item']
        self.assertEqual(data['academicBindings'][0]['weekStart'], '2030-01-07')
        self.assertIn('explicit academic bindings', data['calendarNote'])
        self.assertNotIn('startAt', data)

    def test_cross_user_unknown_public_and_attributed_records_do_not_grant_ownership(self):
        other = self.academic_request(actor=3, title='PRIVATE THIRD PARTY')
        with self.database.transaction() as session:
            row = session.get(ResourceRequest, other)
            row.calendar_public = True
            row.academic_instructor_id = 2
        for key in (other, 2147483647):
            response = self.client.get(f'/professor/academic-requests/{key}')
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.get_json(), dict(error='This academic request is unavailable or private.'))
        self.assertEqual(self.professors.list_for(2)['items'], [])
        # Even a mandatory committee participant cannot read another request through this owner API.
        committee = self.academic_request('CommitteeMeeting', actor=3, day=5)
        with self.assertRaises(PermissionError):
            self.professors.detail(2, committee)

    def test_five_role_boundaries_leave_administrator_interfaces_unchanged(self):
        with self.database.transaction() as session:
            role_id = session.scalar(select(Role.id).where(Role.name == 'TeachingAssistant'))
            session.add(User(id=9, source_order=9, name='Fictional TA', primary_role_id=role_id))
        AccountService(self.database).provision(9, 'professor-ta-fixture', 'Fictional-isolated-password')
        key = self.academic_request()
        for actor in (1, 7, 9, 6):
            client = authorized_client(web_app.app, actor)
            for url in ('/professor/academic-requests', f'/professor/academic-requests/{key}'):
                with self.subTest(actor=actor, url=url):
                    self.assertEqual(client.get(url).status_code, 403)
            with self.assertRaises(PermissionError):
                self.professors.list_for(actor)
        for url in ('/requests', f'/request/{key}', '/add-request', '/calendar/publications'):
            self.assertEqual(self.client.get(url).status_code, 403)
        for url in ('/run-allocation', '/set-strategy'):
            self.assertEqual(self.client.post(url, data={'strategy': 'priority'}).status_code, 403)

    def test_unsupported_writes_csrf_and_spoofed_identity_never_mutate(self):
        key = self.academic_request()
        before = self.repository.snapshot()
        response = self.client.get('/professor/academic-requests?userId=3&requesterId=3')
        self.assertEqual([i['id'] for i in response.get_json()['items']], [key])
        for url in ('/professor/academic-requests', f'/professor/academic-requests/{key}'):
            self.assertEqual(self.client.client.post(url, json={'requesterId': 3}).status_code, 400)
            self.assertIn(self.client.post(url, json={'requesterId': 3}).status_code, (403, 405))
        self.assertEqual(self.repository.snapshot()['requests'], before['requests'])
        with self.database.transaction(read_only=True) as session:
            self.assertIsNone(session.get(ApplicationState, 1).active_run_id)

    def test_disabled_inactive_and_revoked_accounts_fail_closed(self):
        with self.database.transaction() as session:
            session.get(LoginAccount, 2).enabled = False
        with self.assertRaises(PermissionError):
            self.professors.list_for(2)
        self.assertEqual(self.client.get('/professor/academic-requests').status_code, 302)
        with self.database.transaction() as session:
            session.get(LoginAccount, 2).enabled = True
            session.get(User, 2).status = 'inactive'
        with self.assertRaises(PermissionError):
            self.professors.list_for(2)
        with self.database.transaction() as session:
            session.get(User, 2).status = 'active'
            session.get(LoginAccount, 2).session_version += 1
        self.assertEqual(self.client.get('/professor/academic-requests').status_code, 302)
        self.assertEqual(web_app.app.test_client().get('/professor/academic-requests').status_code, 302)

    def test_invalid_filters_pagination_ids_and_actor_types(self):
        for query in ('type=Appointment', 'type=exam', 'status=Confirmed', 'limit=0', 'limit=101',
                      'limit=x', 'offset=-1', 'offset=2147483648', 'offset=1.5'):
            with self.subTest(query=query):
                self.assertEqual(self.client.get('/professor/academic-requests?' + query).status_code, 400)
        for key in (0, True, '1', 2147483648):
            with self.assertRaises(ProfessorRequestError):
                self.professors.detail(2, key)
        for actor in (True, '2', -1):
            with self.assertRaises(PermissionError):
                self.professors.list_for(actor)

    def test_reads_never_write_or_load_global_engine_snapshots_or_raw_decision_payloads(self):
        key = self.academic_request()
        self.publish()
        statements = []
        def record(connection, cursor, statement, parameters, context, many):
            statements.append(statement.lower())
        event.listen(self.database.engine, 'before_cursor_execute', record)
        try:
            self.professors.list_for(2)
            response = self.professors.detail(2, key)
        finally:
            event.remove(self.database.engine, 'before_cursor_execute', record)
        self.assertFalse(any(s.lstrip().startswith(('insert ', 'update ', 'delete ')) for s in statements))
        self.assertFalse(any('allocation_run.snapshot' in s for s in statements))
        self.assertFalse(any('request_decision.payload' in s for s in statements))
        self.assertNotIn('snapshot', str(response))
        self.assertNotIn('submissionFingerprint', str(response))

    def test_database_busy_is_generic_retryable_error(self):
        with mock.patch('web.professor_routes.ProfessorService.list_for', side_effect=DatabaseBusy('PRIVATE SQL')):
            response = self.client.get('/professor/academic-requests')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('PRIVATE SQL', response.get_data(as_text=True))
        self.assertEqual(response.headers['Cache-Control'], 'private, no-store')

