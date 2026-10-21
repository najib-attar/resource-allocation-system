"""Real-engine/PostgreSQL room workflow, permissions and concurrent confirmation."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
import multiprocessing
from unittest import mock
from sqlalchemy import func, select

from auth_fixtures import authorized_client
from postgres_fixtures import ROOT
from test_appointments import AppointmentFixture, START
from runtime_file_guard import forbid_runtime_files
from web import app as web_app
from web.account_service import AccountService
from web.allocation_workflow import execute_allocation
from web.calendar_service import CalendarError
from web.engine_gateway import EngineGateway, EngineIntegrationError, validate_room_result
from web.personal_schedule_service import PersonalScheduleService
from web.persistence.database import Database
from web.persistence.models import (ApplicationState, LoginAccount, OrganizationUnit, Resource,
    Role, RoomOrganizerCommitment, RoomReservation, User)
from web.persistence.repository import Repository
from web.room_request_service import RoomRequestService, RoomRequestError


def confirm_room_process(url, key, output):
    database=Database(url)
    try:
        output.put(RoomRequestService(database,EngineGateway(ROOT)).decide(key,7,1,True))
    except RoomRequestError:
        output.put('conflict')
    finally:
        database.dispose()


class RoomFixture(AppointmentFixture):
    def setUp(self):
        super().setUp()
        with self.database.transaction() as session:
            roles={row.name:row.id for row in session.scalars(select(Role))}
            session.get(User,6).primary_role_id=roles['Administrator']
            faculty=OrganizationUnit(name='Fictional Arts Faculty',unit_type='Faculty')
            session.add(faculty); session.flush(); self.other_faculty=faculty.id
            session.add(User(id=7,source_order=7,name='Faculty Coordinator',primary_role_id=roles['Staff']))
            session.add(Resource(id=302,source_order=2,type='Classroom',name='Study Studio',capacity=8,building='Arts'))
            session.add(Resource(id=303,source_order=3,type='Laboratory',name='Computing Lab',capacity=32,building='Science',computers=True))
        for actor in (1,2,3,4,6,7):
            AccountService(self.database).provision(actor,'room-fixture-'+str(actor),'Fictional-isolated-password',administrator=actor == 6)
        self.rooms=RoomRequestService(self.database,EngineGateway(ROOT))
        self.rooms.configure_approver(6,self.faculty,6)
        self.rooms.configure_approver(6,self.other_faculty,7)
        for room,faculty in ((301,self.faculty),(302,self.other_faculty),(303,self.faculty)):
            self.rooms.configure_room(6,room,faculty,True,['study','meeting','lecture','club','other'])

    def values(self,**changes):
        values=dict(start=START,duration=60,count=5,category='study',purpose='Private study activity',features=[])
        values.update(changes)
        return values

    def request_room(self,actor=1,room=302,invitees=(),**changes):
        return self.rooms.submit(actor,self.values(**changes),list(invitees),room)

    def totals(self):
        with self.database.transaction(read_only=True) as session:
            return tuple(session.scalar(select(func.count()).select_from(model)) for model in (RoomReservation,RoomOrganizerCommitment))

    def academic(self, room=301, bound=True):
        repo=Repository(self.database)
        key=repo.save_request({'type':'OneTime','requesterId':4,'spaceId':room,'participantCount':5,
                              'title':'Known university course','purpose':'University teaching',
                              'slots':[{'day':1,'startMinutes':600,'endMinutes':660}]})
        if bound:
            self.service.bind_legacy('Known fictional January',date(2030,1,7),date(2030,1,31),request_id=key,week_start=date(2030,1,7))
        return repo


class RoomWorkflowTests(RoomFixture):
    def test_recommendation_uses_needs_and_routes_across_faculties(self):
        result=self.rooms.recommend(1,self.values(),[])
        self.assertTrue(result['feasible'])
        self.assertEqual(result['candidates'][0]['roomId'],302)
        key=self.request_room()
        detail=self.rooms.detail(key,1)
        self.assertEqual(detail['facultyId'],self.other_faculty)
        self.assertEqual(detail['approverId'],7)
        self.assertEqual(self.totals(),(0,0))
        self.assertEqual(self.rooms.decide(key,7,1,True),'Confirmed')
        self.assertEqual(self.totals(),(1,1))

    def test_supported_categories_share_one_lifecycle_and_club_is_declared(self):
        for category in ('study','meeting','lecture','club','other'):
            key=self.request_room(category=category,club='Declared fictional club')
            self.rooms.decide(key,7,1,True)
            self.assertEqual(self.rooms.detail(key,1)['club'],'Declared fictional club')
            self.rooms.cancel(key,1,1)
            self.assertEqual(self.totals(),(0,0))

    def test_wrong_faculty_student_and_unrelated_users_cannot_approve_or_view(self):
        key=self.request_room()
        for actor in (1,4,6):
            with self.subTest(actor=actor),self.assertRaises(PermissionError):
                self.rooms.decide(key,actor,1,True)
        with self.assertRaises(PermissionError): self.rooms.detail(key,4)
        self.assertFalse(self.rooms.list_for(4))
        self.assertEqual(self.totals(),(0,0))

    def test_missing_approver_capacity_features_and_whitelist_are_enforced(self):
        self.assertFalse(self.rooms.recommend(1,self.values(count=1000),[])['feasible'])
        self.assertEqual(self.rooms.recommend(1,self.values(features=['computers']),[])['candidates'][0]['roomId'],303)
        self.rooms.configure_room(6,302,self.other_faculty,True,['study'],True,[4])
        self.assertNotIn(302,[r['roomId'] for r in self.rooms.recommend(1,self.values(faculty=self.other_faculty),[])['candidates']])
        self.assertIn(302,[r['roomId'] for r in self.rooms.recommend(4,self.values(),[])['candidates']])
        with self.database.transaction() as session:
            session.get(LoginAccount,7).enabled=False
        self.assertNotIn(302,[r['roomId'] for r in self.rooms.recommend(4,self.values(),[])['candidates']])

    def test_rejection_stale_selection_revision_and_cancellation_keep_history(self):
        key=self.request_room(invitees=(2,))
        self.rooms.decide(key,7,1,False,'Room use not approved')
        self.assertEqual(self.totals(),(0,0))
        self.rooms.submit(1,self.values(start=START+timedelta(hours=1)),[3],301,key,1)
        detail=self.rooms.detail(key,1)
        self.assertEqual((detail['revision'],detail['status'],detail['approverId']),(2,'Pending Faculty Approval',6))
        self.assertEqual([i['id'] for i in detail['invitations']],[3])
        with self.assertRaises(RoomRequestError): self.rooms.decide(key,6,1,True)
        self.rooms.configure_room(6,301,self.faculty,False,['study'])
        self.assertEqual(self.rooms.decide(key,6,2,True),'Needs Revision')
        self.assertEqual(self.totals(),(0,0))
        self.rooms.cancel(key,1,2)
        self.assertGreaterEqual(len(self.rooms.detail(key,1)['history']),4)

    def test_optional_professor_responses_never_veto_room_approval(self):
        key=self.request_room(invitees=(2,3))
        self.rooms.respond(key,2,1,True)
        self.rooms.respond(key,3,1,False)
        self.assertEqual(self.rooms.decide(key,7,1,True),'Confirmed')
        self.assertEqual([i['status'] for i in self.rooms.detail(key,1)['invitations']],['Accepted','Declined'])
        self.assertEqual(self.totals(),(1,1))
        with self.assertRaises(PermissionError): self.rooms.cancel(key,2,1)

    def test_invitation_acceptance_cannot_override_professor_appointment(self):
        appointment=self.service.submit(4,[2],[],'Existing professor commitment',60,START,self.faculty)
        self.service.decide(appointment,2,1,True)
        key=self.request_room(invitees=(2,))
        with self.assertRaises(RoomRequestError): self.rooms.respond(key,2,1,True)
        self.rooms.respond(key,2,1,False)
        self.assertEqual(self.rooms.decide(key,7,1,True),'Confirmed')
        self.assertEqual(self.service.detail(appointment,2)['status'],'Confirmed')

    def test_organizer_appointments_and_room_bookings_conflict_both_directions(self):
        key=self.request_room()
        self.rooms.decide(key,7,1,True)
        with self.assertRaises(CalendarError): self.service.submit(1,[2],[],'Conflicting appointment',60,START,self.faculty)
        self.rooms.cancel(key,1,1)
        appointment=self.service.submit(1,[2],[],'Organizer appointment',60,START,self.faculty)
        self.service.decide(appointment,2,1,True)
        self.assertFalse(self.rooms.recommend(1,self.values(),[])['feasible'])
        self.assertTrue(self.rooms.recommend(1,self.values(start=START+timedelta(hours=1)),[])['feasible'])

    def test_academic_allocations_need_explicit_dates_and_block_only_applicable_week(self):
        repo=self.academic(bound=False)
        execute_allocation(repo,EngineGateway(ROOT))
        result=self.rooms.recommend(1,self.values(),[])
        self.assertNotIn(301,[r['roomId'] for r in result['candidates']])
        self.assertIn('UNRESOLVED_CALENDAR',result['explanations'])
        with self.database.transaction(read_only=True) as session:
            from web.persistence.models import ResourceRequest
            key=session.scalar(select(ResourceRequest.id))
        self.service.bind_legacy('Known fictional January',date(2030,1,7),date(2030,1,31),request_id=key,week_start=date(2030,1,7))
        self.assertNotIn(301,[r['roomId'] for r in self.rooms.recommend(1,self.values(),[])['candidates']])
        self.assertIn(301,[r['roomId'] for r in self.rooms.recommend(1,self.values(start=START+timedelta(days=7)),[])['candidates']])

    def test_all_five_future_strategy_publications_cannot_overwrite_booking(self):
        key=self.request_room(room=301)
        self.rooms.decide(key,6,1,True)
        repo=self.academic()
        for strategy in ('greedy','priority','multi_room_exam_greedy','multi_room_exam_best_fit','shared_room_exam_best_fit'):
            repo.set_strategy(strategy)
            with self.subTest(strategy=strategy),self.assertRaises(CalendarError): execute_allocation(repo,EngineGateway(ROOT))
        with self.database.transaction(read_only=True) as session:
            self.assertIsNone(session.get(ApplicationState,1).active_run_id)
        self.assertEqual(self.totals(),(1,1))

    def test_closures_adjacent_intervals_and_failed_engine_do_not_publish(self):
        self.rooms.close_room(6,302,START,START+timedelta(hours=1),'Maintenance')
        self.assertNotIn(302,[r['roomId'] for r in self.rooms.recommend(1,self.values(),[])['candidates']])
        self.assertIn(302,[r['roomId'] for r in self.rooms.recommend(1,self.values(start=START+timedelta(hours=1)),[])['candidates']])
        with mock.patch.object(self.rooms.gateway,'execute_room',side_effect=EngineIntegrationError('failure')):
            with self.assertRaises(EngineIntegrationError): self.request_room(room=301)
        self.assertEqual(self.totals(),(0,0))

    def test_competing_thread_and_process_confirmations_never_double_book(self):
        for process in (False,True):
            keys=[self.request_room(actor=actor) for actor in (1,4)]
            if process:
                context=multiprocessing.get_context('spawn'); queue=context.Queue()
                workers=[context.Process(target=confirm_room_process,args=(self.url,key,queue)) for key in keys]
                for worker in workers: worker.start()
                outcomes=[queue.get(timeout=40) for _ in workers]
                for worker in workers:
                    worker.join(40)
                    if worker.is_alive(): worker.terminate(); worker.join(); self.fail('Worker did not finish')
                    self.assertEqual(worker.exitcode,0)
                queue.close()
            else:
                def confirm(key):
                    try: return self.rooms.decide(key,7,1,True)
                    except RoomRequestError: return 'conflict'
                with ThreadPoolExecutor(max_workers=2) as pool: outcomes=list(pool.map(confirm,keys))
            self.assertEqual(outcomes.count('Confirmed'),1)
            self.assertEqual(self.totals(),(1,1))
            for key,actor in zip(keys,(1,4)): self.rooms.cancel(key,actor,1)

    def test_room_schedule_and_cancellation_are_private_and_persist_after_restart(self):
        key=self.request_room(invitees=(2,))
        self.rooms.respond(key,2,1,True); self.rooms.decide(key,7,1,True)
        for actor in (1,2):
            schedule=PersonalScheduleService(self.database).load(actor,week='2030-01-07',now=START)
            self.assertTrue(any(e.get('roomRequestId') == key for day in schedule['days'] for e in day['entries']))
        other=PersonalScheduleService(self.database).load(4,week='2030-01-07',now=START)
        self.assertFalse(any(e.get('roomRequestId') for day in other['days'] for e in day['entries']))
        database=Database(self.url)
        try: self.assertEqual(RoomRequestService(database,EngineGateway(ROOT)).detail(key,1)['status'],'Confirmed')
        finally: database.dispose()
        self.rooms.cancel(key,7,1)
        self.assertEqual(self.totals(),(0,0))

    def test_web_student_faculty_invitation_csrf_and_privacy_flow(self):
        client=self.configure_web()
        def client_for(actor): return authorized_client(web_app.app,actor,1)
        data={'csrf_token':'fixture-csrf-token'}
        with client.session_transaction() as session: data['csrf_token']=session['csrf']
        data.update(category='study',purpose='<script>Private purpose</script>',count='5',duration='60',start='2030-01-07T10:00',roomId='302',professorIds='2')
        with forbid_runtime_files():
            self.assertEqual(client.get('/rooms/new').status_code,200)
            self.assertEqual(client.post('/rooms/candidates',data=data).status_code,200)
            saved=client.post('/rooms/new',data=data)
        self.assertEqual(saved.status_code,302)
        page=client.get(saved.location)
        self.assertIn(b'Pending Faculty Approval',page.data)
        self.assertNotIn(b'<script>Private purpose</script>',page.data)
        self.assertEqual(client_for(4).get(saved.location).status_code,403)
        self.assertEqual(client_for(7).get(saved.location).status_code,200)
        self.assertEqual(client.client.post(saved.location+'/cancel',data={'revision':'1'}).status_code,400)
        manager=client_for(7)
        scoped=manager.get('/rooms/configuration')
        self.assertEqual(scoped.status_code,200)
        self.assertIn(b'Study Studio',scoped.data)
        self.assertNotIn(b'Computing Lab',scoped.data)
        self.assertNotIn(b'Designate a faculty approver',scoped.data)
        self.assertEqual(manager.post('/rooms/configuration',data={'action':'approver','faculty':str(self.faculty),'approver':'7'}).status_code,403)
        self.assertEqual(manager.post('/rooms/configuration',data={'action':'policy','roomId':'301','faculty':str(self.faculty),'categories':['study']}).status_code,403)
        self.assertEqual(manager.post('/rooms/configuration',data={'action':'close','roomId':'301','start':'2030-01-08T10:00','end':'2030-01-08T11:00','reason':'Wrong faculty'}).status_code,403)
        self.assertEqual(client_for(6).get('/rooms/configuration').status_code,200)
        self.assertEqual(client.get('/student/').status_code,200)

    def test_malformed_requirements_and_foreign_identifiers_do_not_save(self):
        for changes in ({'count':0},{'duration':-1},{'category':'unsupported'},{'features':['invented']},{'faculty':999999}):
            with self.subTest(changes=changes),self.assertRaises(RoomRequestError): self.request_room(**changes)
        with self.assertRaises(PermissionError): self.request_room(actor=2)
        with self.assertRaises(PermissionError): self.request_room(invitees=(999999,))
        self.assertEqual(self.totals(),(0,0))

    def test_gateway_rejects_wrong_correlation_room_and_capacity(self):
        from copy import deepcopy
        from web.room_calendar import room_snapshot
        values=self.values(); values['end']=START+timedelta(hours=1)
        with self.database.transaction(read_only=True) as session:
            snapshot,_=room_snapshot(session,1,'Student',values,(START,values['end']))
        result,_=EngineGateway(ROOT).execute_room(snapshot)
        for change in ('run','room','capacity','version'):
            invalid=deepcopy(result)
            if change == 'run': invalid['runId']='wrong'
            if change == 'room': invalid['candidates'][0]['roomId']=999999
            if change == 'capacity': invalid['candidates'][0]['capacity']=999999
            if change == 'version': invalid['protocolVersion']=2
            with self.subTest(change=change),self.assertRaises(EngineIntegrationError): validate_room_result(invalid,snapshot)

    def test_free_busy_calendar_never_leaks_private_event_details(self):
        key=self.request_room()
        self.rooms.decide(key,7,1,True)
        self.assertEqual(len(self.rooms.availability(4,302,date(2030,1,7))['busy']),1)
        self.configure_web()
        other=authorized_client(web_app.app,4,1)
        page=other.get('/rooms/availability/302?date=2030-01-07')
        self.assertEqual(page.status_code,200)
        self.assertNotIn(b'Private study activity',page.data)
        self.assertNotIn(b'Student Mira',page.data)
        self.assertEqual(other.get('/rooms/availability/302?date=wrong').status_code,409)

    def test_revision_is_checked_before_approval_or_invitation_evaluation(self):
        key=self.request_room(invitees=(2,))
        with mock.patch.object(self.rooms.gateway,'execute_room') as evaluate:
            with self.assertRaises(RoomRequestError): self.rooms.decide(key,7,2,True)
            with self.assertRaises(RoomRequestError): self.rooms.respond(key,2,2,True)
            evaluate.assert_not_called()
        self.assertEqual(self.totals(),(0,0))
