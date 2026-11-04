"""Professor presentation against real disposable PostgreSQL; no business mocks."""
from datetime import timedelta
import uuid
from unittest import mock

from sqlalchemy import event, select

from auth_fixtures import authorized_client
from test_appointments import START
from test_professor_services import ProfessorFixture
from web import app as web_app
from web.account_service import AccountService
from web.persistence.models import LoginAccount, Role, User
from web.professor_dashboard_service import ProfessorDashboardService


class ProfessorPortalTests(ProfessorFixture):
    def test_eligibility_navigation_is_expanded_for_administrators_and_protected_for_other_roles(self):
        from test_student_portal_ui import Document
        key=self.academic_request()
        administrator=authorized_client(web_app.app,6)
        for path in ('/academic-eligibility/',f'/academic-eligibility/{key}'):
            response=administrator.get(path)
            self.assertEqual(response.status_code,200)
            page=Document(response.get_data(as_text=True)).root
            disclosure=page.find('details',**{'class':'app-admin-navigation'})[0]
            self.assertIn('open',disclosure.attrs)
            self.assertEqual(disclosure.find('a',href='/academic-eligibility/')[0].attrs['aria-current'],'page')
        with self.database.transaction() as session:
            role=session.scalar(select(Role).where(Role.name=='TeachingAssistant'))
            session.add(User(id=9,source_order=9,name='Synthetic audit TA',primary_role_id=role.id))
        AccountService(self.database).provision(9,'synthetic-audit-ta','Synthetic-audit-password-only')
        for actor in (1,2,7,9):
            client=authorized_client(web_app.app,actor)
            self.assertEqual(client.get('/academic-eligibility/').status_code,403)
            self.assertEqual(client.get(f'/academic-eligibility/{key}').status_code,403)

    def meeting(self,title,organizer=1,professors=(2,),start=START):
        return self.service.submit(organizer,list(professors),[],title,60,start,self.faculty)

    def home(self, actor=2):
        return ProfessorDashboardService(self.database).load(actor, now=START-timedelta(hours=1))

    def test_home_reads_only_authorized_real_state_without_engine_or_writes(self):
        statements=[]
        def record(connection,cursor,statement,parameters,context,many):
            statements.append(statement.lstrip().split()[0].upper())
        event.listen(self.database.engine,'before_cursor_execute',record)
        try:
            with mock.patch('web.engine_gateway.EngineGateway._execute',side_effect=AssertionError('Home must never run C++')):
                home=self.home()
        finally:event.remove(self.database.engine,'before_cursor_execute',record)
        self.assertEqual(home['counts']['pending'],0)
        self.assertEqual(home['counts']['confirmed'],0)
        self.assertEqual(home['counts']['review'],0)
        self.assertEqual(home['academic'],[])
        self.assertFalse(set(statements)&{'INSERT','UPDATE','DELETE','TRUNCATE'})

    def test_dashboard_pending_decisions_confirmed_meetings_and_owner_requests_are_distinct(self):
        confirmed=self.meeting('Own confirmed appointment')
        self.service.decide(confirmed,2,1,True)
        pending=self.meeting('Required two-professor appointment',professors=(2,3),start=START+timedelta(hours=1))
        self.meeting('PRIVATE unrelated appointment',organizer=4,professors=(3,),start=START+timedelta(hours=2))
        own=self.academic_request(title='Own pending declaration')
        self.academic_request(actor=3,title='PRIVATE peer academic declaration')
        home=self.home()
        self.assertEqual([r['id'] for r in home['confirmed']],[confirmed])
        self.assertEqual([r['id'] for r in home['pending']],[pending])
        self.assertEqual([r['id'] for r in home['academic']],[own])
        self.assertEqual(home['counts']['review'],1)
        self.assertNotIn('PRIVATE',str(home))
        self.service.decide(pending,2,1,True)
        self.assertEqual(self.home()['counts']['pending'],0)
        self.assertEqual(self.home()['counts']['confirmed'],1)

    def test_home_uses_current_academic_outcomes_and_no_inferred_dates(self):
        own=self.academic_request()
        self.publish()
        item=self.home()
        self.assertEqual(item['academic'][0]['status'],'Approved')
        self.assertEqual(item['results'][0]['id'],own)
        self.assertTrue(item['schedule']['unresolved'])
        self.assertFalse(any(e['kind']=='University' for d in item['schedule']['days'] for e in d['entries']))

    def test_professor_home_role_identity_csrf_and_primary_destinations(self):
        with self.database.transaction() as session:
            role=session.scalar(select(Role.id).where(Role.name=='TeachingAssistant'))
            session.add(User(id=9,source_order=9,name='Synthetic TA',primary_role_id=role))
        AccountService(self.database).provision(9,'portal-ta','Synthetic-professor-portal-password')
        for actor in (1,6,7,9):
            with self.subTest(actor=actor):
                self.assertEqual(authorized_client(web_app.app,actor).get('/professor/').status_code,403)
                with self.assertRaises(PermissionError):self.home(actor)
        page=self.client.get('/professor/')
        self.assertEqual(page.status_code,200)
        self.assertEqual(page.headers['Cache-Control'],'private, no-store')
        from test_student_portal_ui import Document
        tree=Document(page.get_data(as_text=True)).root
        links=tree.find('nav',**{'aria-label':'Main navigation'})[0].find('a')
        self.assertEqual([r.attrs['href'] for r in links],['/professor/','/professor/requests','/calendar/','/notifications/'])
        self.assertEqual(len(tree.find('h1')),1)
        for path in ('/appointments/','/appointments/availability','/appointments/calendar','/rooms/'):
            self.assertTrue(tree.find('a',href=path),path)
        self.assertEqual(self.client.client.post('/logout').status_code,400)
        with self.database.transaction() as session:session.get(LoginAccount,2).enabled=False
        with self.assertRaises(PermissionError):self.home()
        self.assertEqual(self.client.get('/professor/').status_code,302)

    def test_professor_decision_ui_tracks_own_approval_and_student_reschedule(self):
        key=self.meeting('Shared approval',professors=(2,3))
        from test_student_portal_ui import Document
        def detail():return Document(self.client.get(f'/appointments/{key}').get_data(as_text=True)).root
        self.assertTrue(detail().find('button',name='decision',value='approve'))
        self.assertEqual(self.client.post(f'/appointments/{key}/decision',data=dict(revision=1,decision='approve')).status_code,302)
        self.assertFalse(detail().find('button',name='decision',value='approve'))
        self.assertTrue(detail().find('button',name='decision',value='decline'))
        self.assertIn('You approved this revision',detail().text)
        self.service.reschedule(key,1,1,START+timedelta(hours=2))
        self.assertTrue(detail().find('button',name='decision',value='approve'))
        self.assertEqual(self.client.post(f'/appointments/{key}/decision',data=dict(revision=1,decision='approve')).status_code,409)
        self.assertNotIn('/appointments/new',self.client.get('/appointments/').get_data(as_text=True))
        self.assertEqual(self.client.client.post(f'/appointments/{key}/decision',data=dict(revision=2,decision='approve')).status_code,400)

    def test_office_hour_validation_retains_fields_and_personal_schedule_has_mobile_agenda(self):
        from test_student_portal_ui import Document
        response=self.client.post('/appointments/availability',data=dict(action='hours',day=2,
            startTime='12:00',endTime='09:00',validFrom='2030-01-01',validUntil='2030-01-31',excludedDates='2030-01-15'))
        self.assertEqual(response.status_code,409)
        page=Document(response.get_data(as_text=True)).root
        self.assertTrue(page.find(role='alert'))
        self.assertEqual(page.find('input',name='validFrom')[0].attrs['value'],'2030-01-01')
        self.assertEqual(page.find('input',name='excludedDates')[0].attrs['value'],'2030-01-15')
        schedule=Document(self.client.get('/appointments/calendar?month=2030-01&week=2030-01-07').get_data(as_text=True)).root
        self.assertTrue(schedule.find('div',**{'class':'personal-agenda'}))

    def test_academic_form_preserves_midnight_and_declared_fields_on_unpublished_revision(self):
        data=dict(requestType='OneTime',submissionKey=uuid.uuid4().hex,title='End of day teaching',purpose='Declared activity',
            facultyDeclaration='Unverified faculty declaration',spaceId=302,participantCount=5,day=2,startTime='23:00',endTime='24:00')
        response=self.client.post('/professor/requests/new',data=data)
        self.assertEqual(response.status_code,302,response.data)
        key=int(response.location.rsplit('/',1)[-1])
        self.assertEqual(self.professors.detail(2,key)['item']['slots'][0]['endMinutes'],1440)
        from test_student_portal_ui import Document
        page=Document(self.client.get(f'/professor/requests/{key}/revise').get_data(as_text=True)).root
        self.assertEqual(page.find('input',name='endTime')[0].attrs['value'],'24:00')
        self.assertEqual(page.find('input',name='facultyDeclaration')[0].attrs['value'],data['facultyDeclaration'])
        self.assertNotIn('run-allocation',self.client.get(response.location).get_data(as_text=True))

    def test_invalid_committee_form_retains_required_people_and_roles(self):
        data=dict(requestType='CommitteeMeeting',submissionKey=uuid.uuid4().hex,title='',purpose='Declared committee',
            spaceId=301,participantCount=5,day=2,startTime='13:00',endTime='14:00',
            requiredParticipantIds=['2','3'],participantRole_2='Chair',participantRole_3='Secretary')
        response=self.client.post('/professor/requests/new',data=data)
        self.assertEqual(response.status_code,400)
        from test_student_portal_ui import Document
        page=Document(response.get_data(as_text=True)).root
        self.assertTrue(page.find(role='alert'))
        self.assertEqual(len([node for node in page.find('input',name='requiredParticipantIds') if 'checked' in node.attrs]),2)
        self.assertEqual(page.find('input',name='participantRole_2')[0].attrs['value'],'Chair')

    def test_owner_tracking_distinguishes_pending_allocation_and_type_revision_requires_review(self):
        key=self.academic_request(title='Own unallocated declaration')
        from test_student_portal_ui import Document
        page=Document(self.client.get(f'/professor/requests/{key}').get_data(as_text=True)).root
        self.assertIn('Not allocated',page.text)
        self.assertFalse(page.find('article',**{'class':'academic-allocation'}))
        changed=self.client.get(f'/professor/requests/{key}/revise?type=Exam')
        self.assertEqual(changed.status_code,200)
        self.assertTrue(Document(changed.get_data(as_text=True)).root.find('input',name='courseCode'))
        from web.academic_eligibility import EligibilityService
        item=self.professors.detail(2,key)['item']
        EligibilityService(self.database).decide(6,key,1,item['reviewVersion'],True,'Reviewed original declaration')
        data=dict(requestType='Exam',revision=1,submissionKey=uuid.uuid4().hex,title='Revised exam declaration',
            purpose='Declared examination',spaceId=302,participantCount=5,day=2,startTime='10:00',endTime='11:00',
            courseCode='SYN2',courseName='Declared course',examType='Final',canSplitAcrossRooms='true')
        response=self.client.post(f'/professor/requests/{key}/revise',data=data)
        self.assertEqual(response.status_code,302,response.data)
        item=self.professors.detail(2,key)['item']
        self.assertEqual((item['type'],item['revision'],item['eligibilityStatus']),('Exam',2,'Pending Eligibility Review'))
        self.assertEqual(item['allocations'],[])
        self.assertEqual(item['examDeclaration']['courseCode'],'SYN2')
        stale=self.client.post(f'/professor/requests/{key}/revise',data=data)
        self.assertEqual(stale.status_code,400)
        stale_page=Document(stale.get_data(as_text=True)).root
        self.assertEqual(stale_page.find('input',name='revision')[0].attrs['value'],'1')
        self.assertTrue(stale_page.find('a',href=f'/professor/requests/{key}/revise'))
        self.assertEqual(self.client.post(f'/professor/requests/{key}/revise',data=data).status_code,400)
        self.assertEqual(self.professors.detail(2,key)['item']['revision'],2)
        self.assertEqual(authorized_client(web_app.app,3).get(f'/professor/requests/{key}').status_code,403)

    def test_published_tracking_has_real_allocation_and_no_edit_control(self):
        key=self.academic_request()
        self.publish()
        from test_student_portal_ui import Document
        page=Document(self.client.get(f'/professor/requests/{key}').get_data(as_text=True)).root
        self.assertTrue(page.find('article',**{'class':'academic-allocation'}))
        self.assertFalse(page.find('a',href=f'/professor/requests/{key}/revise'))
        self.assertIn('read-only',page.text)
        self.assertIn('No explicit academic period',page.text)

    def test_professor_calendar_agenda_and_inbox_preserve_authorized_sources(self):
        self.meeting('Visible student request')
        from test_student_portal_ui import Document
        page=Document(self.client.get('/calendar/?view=week&date=2030-01-07').get_data(as_text=True)).root
        self.assertTrue(page.find('section',**{'class':'calendar-agenda'}))
        self.assertIn('Declared courses',page.text)
        self.assertFalse(page.find('a',href='/calendar/publications'))
        inbox=Document(self.client.get('/notifications/').get_data(as_text=True)).root
        self.assertIn('Academic allocation notifications are not enabled',inbox.text)
        self.assertTrue(inbox.find('form',action='/notifications/read'))
