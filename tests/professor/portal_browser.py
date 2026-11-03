"""Real Flask acceptance per professor frontend phase in owned PostgreSQL fixtures."""
from datetime import date,timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT)]
from flask import g,request
from sqlalchemy import create_engine,select,text
from werkzeug.serving import make_server
from test_professor_services import ProfessorFixture
from test_appointments import START
from browser_review import persisted as original_state,verify as verify_original
from eligibility_browser import persisted as academic_state,verify as verify_academic
from web import app as web_app
from web.account_service import AccountService
from web.persistence.models import LoginAccount,Role,User


def main():
    if not os.environ.get('TEST_DATABASE_URL'):raise RuntimeError('Disposable PostgreSQL required.')
    phase=os.environ.get('PROFESSOR_PORTAL_PHASE','PROF-UI-01')
    output=ROOT/'docs/professor-services/portal'/phase
    fixture=ProfessorFixture();server=None;thread=None;posts=[]
    try:
        fixture.setUp()
        confirmed=fixture.submit();fixture.service.decide(confirmed,2,1,True)
        multi=fixture.submit(professors=(2,3),invitees=(4,5),start=START+timedelta(hours=1))
        decline=fixture.submit(start=START+timedelta(hours=2))
        rooms=[fixture.request_room(invitees=(2,),start=START+timedelta(days=1,hours=4)),
               fixture.request_room(invitees=(2,),start=START+timedelta(days=2,hours=4))]
        academic={kind:fixture.academic_request(kind,day=day) for kind,day in
                  [('Exam',2),('OneTime',3),('Recurring',4),('CommitteeMeeting',6)]}
        rejected=fixture.academic_request('Exam',day=7,participantCount=999)
        foreign=fixture.academic_request(actor=3,day=7,title='PRIVATE PEER ACADEMIC TITLE')
        for key in [*academic.values(),foreign]:
            fixture.service.bind_legacy('Explicit synthetic academic week',date(2030,1,7),date(2030,1,13),
                request_id=key,week_start=date(2030,1,7))
        fixture.publish()
        pending=fixture.academic_request(day=7,title='Awaiting administrative review')
        fixture.service.block(3,START+timedelta(days=4,hours=4),START+timedelta(days=4,hours=5),'PRIVATE PEER BLOCK')
        with fixture.database.transaction() as session:
            roles={r.name:r.id for r in session.scalars(select(Role))}
            session.add_all([User(id=9,source_order=9,name='Synthetic Teaching Assistant',primary_role_id=roles['TeachingAssistant']),
                User(id=12,source_order=12,name='Synthetic New Professor',primary_role_id=roles['Instructor'])])
        actors=(1,2,3,6,7,9,12);password='Synthetic-professor-portal-only-password'
        with fixture.database.transaction(read_only=True) as session:existing=set(session.scalars(select(LoginAccount.user_id)))
        users={actor:'portal-review-'+str(actor) for actor in actors}
        for actor in actors:AccountService(fixture.database).provision(actor,users[actor],password,administrator=actor==6,reset=actor in existing)
        def state():return dict(workflow=original_state(fixture),academic=academic_state(fixture.database))
        def before():
            if request.method=='POST':g.portal_before=state()
        def after(response):
            if request.method=='POST':posts.append(dict(path=request.path,status=response.status_code,
                form={k:v for k,v in request.form.items() if k not in ('username','password','csrf_token')},
                before=g.portal_before,after=state()))
            return response
        web_app.app.before_request_funcs[None].insert(0,before);fixture.addCleanup(web_app.app.before_request_funcs[None].remove,before)
        web_app.app.after_request_funcs[None].append(after);fixture.addCleanup(web_app.app.after_request_funcs[None].remove,after)
        web_app.app.config.update(TESTING=False,PROPAGATE_EXCEPTIONS=False)
        server=make_server('127.0.0.1',0,web_app.app,threaded=True);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        build=ROOT/'build/professor-portal';build.mkdir(parents=True,exist_ok=True)
        info=build/(phase+'.json');info.write_text(json.dumps(dict(url=f'http://127.0.0.1:{server.server_port}',users=users,password=password,
            ids=dict(confirmed=confirmed,multi=multi,decline=decline,roomAccept=rooms[0],roomDecline=rooms[1],
                academic=academic,rejected=rejected,pending=pending,foreign=foreign))),encoding='utf-8')
        output.mkdir(parents=True,exist_ok=True)
        env=dict(os.environ,PROFESSOR_INFO_FILE=str(info),PROFESSOR_OUTPUT_DIR=str(output))
        result=subprocess.run(['node',str(ROOT/'tests/professor/portal_browser.cjs')],cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',timeout=1200)
        (output/'browser-output.txt').write_text((result.stdout+'\n'+result.stderr).rstrip()+'\n',encoding='utf-8')
        (output/'post-states.json').write_text(json.dumps(posts,indent=2,default=str)+'\n',encoding='utf-8')
        if result.returncode:raise RuntimeError('Browser phase failed: '+phase)
        if phase=='PROF-UI-03':
            assert len([p for p in posts if p['path']=='/appointments/availability'
                and p['form'].get('action')=='hours' and p['status']<400])==1, 'Duplicate native submission reached Flask'
            overlap=next(p for p in posts if p['form'].get('reason')=='Personal preference during academic allocation')
            assert overlap['before']['academic']['allocations']==overlap['after']['academic']['allocations']
            assert overlap['before']['academic']['state'][0]['active_run_id']==overlap['after']['academic']['state'][0]['active_run_id']
        original=[];academic_posts=[]
        for post in posts:
            if post['status']>=400:assert post['before']==post['after'],post['path']
            is_academic=post['path'].startswith(('/professor/requests','/academic-eligibility')) or post['path']=='/run-allocation'
            key='academic' if is_academic else 'workflow'
            value=dict(post,before=post['before'][key],after=post['after'][key])
            (academic_posts if is_academic else original).append(value)
        checked=verify_original(original)+verify_academic(academic_posts)
        (output/'persistence-verification.json').write_text(json.dumps(dict(posts=len(posts),outcomes=checked),indent=2)+'\n',encoding='utf-8')
        print(json.dumps(dict(phase=phase,exitCode=0,posts=len(posts),verifiedOutcomes=len(checked))))
    finally:
        if server:server.shutdown();server.server_close();thread.join(timeout=10)
        if not fixture.doCleanups():raise RuntimeError('Fixture cleanup failed.')
        if thread and thread.is_alive():raise RuntimeError('Server failed to stop.')
        if hasattr(fixture,'schema'):
            owner=create_engine(os.environ['TEST_DATABASE_URL'])
            try:
                with owner.connect() as connection:assert not connection.scalar(text('SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=:s)'),dict(s=fixture.schema))
            finally:owner.dispose()
        output.mkdir(parents=True,exist_ok=True);(output/'cleanup.json').write_text(json.dumps(dict(schema=getattr(fixture,'schema',None),absent=True,serverStopped=True))+'\n',encoding='utf-8')


if __name__=='__main__':main()
