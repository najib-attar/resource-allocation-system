"""Professor presentation against real disposable PostgreSQL; no business mocks."""
from datetime import timedelta
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
