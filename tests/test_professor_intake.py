"""Self-owned submissions, administrative review and full real-engine results."""
import uuid
from concurrent.futures import ThreadPoolExecutor
from auth_fixtures import authorized_client
from test_professor_services import ProfessorFixture
from web import app as web_app
from web.academic_eligibility import EligibilityService
from web.persistence.models import ApplicationState, ResourceRequest, RequestEligibility, User


class ProfessorIntakeTests(ProfessorFixture):
    def form(self,kind='OneTime',**changes):
        value=dict(requestType=kind,submissionKey=uuid.uuid4().hex,title='Declared academic activity',purpose='Synthetic course/activity',
            spaceId='302',participantCount='5',facultyDeclaration='Declared faculty',day='1',startTime='10:00',endTime='11:00',
            requiredFeature='',requiredBuilding='')
        if kind=='Exam':value.update(courseCode='FIC101',courseName='Declared course',examType='Midterm',canSplitAcrossRooms='false')
        if kind=='Recurring':value['timeData']='2-10:00-11:00;4-10:00-11:00'
        if kind=='CommitteeMeeting':value.update(spaceId='301',requiredParticipantIds=['2','3'],participantRole_2='Supervisor',participantRole_3='CommitteeMember')
        value.update(changes)
        return value

    def test_all_four_forms_submit_under_session_identity_then_admin_reviews_and_engine_allocates(self):
        reviewer=authorized_client(web_app.app,6)
        for kind in ('Exam','OneTime','Recurring','CommitteeMeeting'):
            with self.subTest(kind=kind):
                with self.database.transaction(read_only=True) as session:
                    previous_run=session.get(ApplicationState,1).active_run_id
                self.assertEqual(self.client.get('/professor/requests/new?type='+kind).status_code,200)
                response=self.client.post('/professor/requests/new',data=self.form(kind))
                self.assertEqual(response.status_code,302,response.get_data(as_text=True))
                key=int(response.location.rsplit('/',1)[-1])
                self.assertIn(b'Pending Eligibility Review',self.client.get(response.location).data)
                with self.database.transaction(read_only=True) as session:
                    self.assertEqual(session.get(ResourceRequest,key).requester_id,2)
                    meta=session.get(RequestEligibility,key)
                    self.assertEqual((meta.origin,meta.submitted_by,meta.status),('Professor',2,'Pending Eligibility Review'))
                    self.assertEqual(session.get(ApplicationState,1).active_run_id,previous_run)
                    version=meta.version
                self.assertEqual(self.repository.snapshot()['requests'],[])
                self.assertEqual(reviewer.get('/academic-eligibility/'+str(key)).status_code,200)
                reviewed=reviewer.post('/academic-eligibility/'+str(key),data=dict(revision='1',reviewVersion=version,decision='approve',reason='Reviewed declared academic need.'))
                self.assertEqual(reviewed.status_code,302)
                # Decline previous fixture inputs so only this declaration participates in this case.
                for item in EligibilityService(self.database).list_for(6)['items']:
                    if item['id']!=key and item['status']=='Eligible':
                        EligibilityService(self.database).decide(6,item['id'],item['revision'],item['reviewVersion'],False,'Retired synthetic fixture')
                from web.allocation_workflow import execute_allocation
                from web.engine_gateway import EngineGateway
                from postgres_fixtures import ROOT
                execute_allocation(self.repository,EngineGateway(ROOT))
                detail=self.professors.detail(2,key)['item']
                self.assertEqual(detail['status'],'Approved')
                self.assertEqual(len(detail['allocations']),2 if kind=='Recurring' else 1)
                # An explicit empty successor allocation replaces the prior result for the next isolated case.
                meta=next(i for i in EligibilityService(self.database).list_for(6)['items'] if i['id']==key)
                EligibilityService(self.database).decide(6,key,meta['revision'],meta['reviewVersion'],False,'Completed isolated case')
                execute_allocation(self.repository,EngineGateway(ROOT))

    def test_revision_invalidates_review_and_clears_old_engine_result_without_mutating_others(self):
        response=self.client.post('/professor/requests/new',data=self.form('CommitteeMeeting'))
        key=int(response.location.rsplit('/',1)[-1])
        meta=self.professors.detail(2,key)['item']
        EligibilityService(self.database).decide(6,key,1,meta['reviewVersion'],True,'Reviewed')
        response=self.client.get(f'/professor/requests/{key}/revise')
        self.assertEqual(response.status_code,200)
        self.assertIn(b'CommitteeMember',response.data)
        revised=self.client.post(f'/professor/requests/{key}/revise',data=self.form('Recurring',revision='1'))
        self.assertEqual(revised.status_code,302,revised.get_data(as_text=True))
        item=self.professors.detail(2,key)['item']
        self.assertEqual((item['revision'],item['eligibilityStatus'],len(item['slots']),item['participants']),
                         (2,'Pending Eligibility Review',2,[]))
        self.assertEqual(self.repository.snapshot()['requests'],[])
        self.assertEqual(self.client.post(f'/professor/requests/{key}/revise',data=self.form(revision='1')).status_code,400)
        peer=authorized_client(web_app.app,3)
        self.assertEqual(peer.get(f'/professor/requests/{key}').status_code,403)
        self.assertEqual(peer.post(f'/professor/requests/{key}/revise',data=self.form(revision='2')).status_code,403)

    def test_submission_csrf_roles_identity_validation_and_idempotency(self):
        form=self.form()
        for actor in (1,6,7):
            client=authorized_client(web_app.app,actor)
            self.assertEqual(client.post('/professor/requests/new',data=form).status_code,403)
        self.assertEqual(self.client.client.post('/professor/requests/new',data=form).status_code,400)
        self.assertEqual(self.client.post('/professor/requests/new',data=self.form(userId='3')).status_code,400)
        first=self.client.post('/professor/requests/new',data=form)
        self.assertEqual(self.client.post('/professor/requests/new',data=form).location,first.location)
        self.assertEqual(self.client.post('/professor/requests/new',data=dict(form,title='Changed retry')).status_code,400)
        peer=authorized_client(web_app.app,3)
        self.assertEqual(peer.post('/professor/requests/new',data=form).status_code,403)
        for values in (self.form('Exam',courseCode=''),self.form('Recurring',timeData='1-11:00-10:00'),
                       self.form('CommitteeMeeting',requiredParticipantIds=[]),self.form(spaceId='999999')):
            self.assertEqual(self.client.post('/professor/requests/new',data=values).status_code,400)

    def test_review_csrf_self_approval_and_administrator_controls_remain_protected(self):
        result=self.client.post('/professor/requests/new',data=self.form())
        key=int(result.location.rsplit('/',1)[-1])
        version=self.professors.detail(2,key)['item']['reviewVersion']
        data=dict(revision=1,reviewVersion=version,decision='approve',reason='Review')
        for actor in (1,2,3,7):
            client=authorized_client(web_app.app,actor)
            self.assertEqual(client.get('/academic-eligibility/').status_code,403)
            self.assertEqual(client.post('/academic-eligibility/'+str(key),data=data).status_code,403)
        admin=authorized_client(web_app.app,6)
        self.assertEqual(admin.client.post('/academic-eligibility/'+str(key),data=data).status_code,400)
        self.assertEqual(admin.post('/academic-eligibility/'+str(key),data=data).status_code,302)
        self.assertEqual(admin.post('/academic-eligibility/'+str(key),data=data).status_code,409)
        for url in ('/run-allocation',f'/run-allocation-now/{key}','/set-strategy'):
            self.assertEqual(self.client.post(url,data={'strategy':'priority'}).status_code,403)

    def test_json_submission_and_inactive_participants_are_validated(self):
        payload=dict(type='Exam',spaceId=302,participantCount=5,title='API exam',purpose='Declared API context',
            slots=[dict(day=1,startMinutes=600,endMinutes=660)],exam=dict(courseCode='API1',courseName='Declared',examType='Final',canSplitAcrossRooms=False),submissionKey=uuid.uuid4().hex)
        response=self.client.post('/professor/academic-requests',json=payload)
        self.assertEqual(response.status_code,201,response.data)
        self.assertEqual(response.get_json()['item']['eligibilityStatus'],'Pending Eligibility Review')
        with self.database.transaction() as session:session.get(User,3).status='inactive'
        self.assertEqual(self.client.post('/professor/requests/new',data=self.form('CommitteeMeeting')).status_code,400)

    def test_active_published_requests_are_read_only_after_eligibility_rejection(self):
        from datetime import date
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError
        from test_appointments import START
        from web.university_calendar import UniversityCalendarService
        response=self.client.post('/professor/requests/new',data=self.form())
        key=int(response.location.rsplit('/',1)[-1])
        item=self.professors.detail(2,key)['item']
        reviewer=EligibilityService(self.database)
        reviewer.decide(6,key,1,item['reviewVersion'],True,'Eligible declaration')
        self.service.bind_legacy('Explicit academic test week',date(2030,1,7),date(2030,1,13),
            request_id=key,week_start=date(2030,1,7))
        from web.allocation_workflow import execute_allocation
        from web.engine_gateway import EngineGateway
        from postgres_fixtures import ROOT
        execute_allocation(self.repository,EngineGateway(ROOT))
        calendar=UniversityCalendarService(self.database)
        def events():
            return calendar.load(2,view='week',day='2030-01-07',now=START,categories=['academic'])['events']
        published_events=events()
        self.assertTrue(published_events)
        item=self.professors.detail(2,key)['item']
        reviewer.decide(6,key,1,item['reviewVersion'],False,'Rejected for the next publication')
        self.assertFalse(self.professors.detail(2,key)['item']['canRevise'])
        self.assertEqual(self.client.get(f'/professor/requests/{key}/revise').status_code,400)
        self.assertEqual(self.client.post(f'/professor/requests/{key}/revise',data=self.form(revision='1',title='Forbidden change')).status_code,400)
        with self.assertRaises(IntegrityError),self.database.transaction() as session:
            session.get(ResourceRequest,key).title='Forbidden direct material change'
        with self.assertRaises(IntegrityError),self.database.transaction() as session:
            session.execute(text('UPDATE request_slot SET start_minutes=start_minutes+15 WHERE request_id=:key'),dict(key=key))
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.get(ResourceRequest,key).revision,1)
        self.assertEqual(self.professors.detail(2,key)['item']['status'],'Approved')
        self.assertEqual(events(),published_events)
        execute_allocation(self.repository,EngineGateway(ROOT))
        self.assertTrue(self.professors.detail(2,key)['item']['canRevise'])
        self.assertEqual(events(),[])

    def test_published_rejection_is_read_only_and_concurrent_unpublished_revisions_are_checked(self):
        response=self.client.post('/professor/requests/new',data=self.form(participantCount='999'))
        key=int(response.location.rsplit('/',1)[-1])
        item=self.professors.detail(2,key)['item']
        EligibilityService(self.database).decide(6,key,1,item['reviewVersion'],True,'Reviewed capacity declaration')
        from web.allocation_workflow import execute_allocation
        from web.engine_gateway import EngineGateway
        from postgres_fixtures import ROOT
        execute_allocation(self.repository,EngineGateway(ROOT))
        item=self.professors.detail(2,key)['item']
        self.assertEqual(item['status'],'Rejected')
        self.assertFalse(item['canRevise'])
        new=self.client.post('/professor/requests/new',data=self.form())
        new_key=int(new.location.rsplit('/',1)[-1])
        def revise(title):
            client=authorized_client(web_app.app,2)
            return client.post(f'/professor/requests/{new_key}/revise',data=self.form(revision='1',title=title)).status_code
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(revise,('First revision','Second revision')))
        self.assertEqual(sorted(results),[302,400])
