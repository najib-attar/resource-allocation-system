"""Live migration -> review -> professor intake -> real C++ replacement publication."""
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread
from unittest import mock

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT)]
from flask import g,request
from sqlalchemy import select,text
from werkzeug.serving import make_server
from test_eligibility_migration import LegacyEligibilityMigrationTests
from web import app as web_app
from web.account_service import AccountService
from web.engine_gateway import EngineGateway
from web.persistence.models import LoginAccount,RequestEligibility,Resource,ResourceRequest,Role,User
from web.persistence.repository import advance_identity

OUTPUT=ROOT/'docs/professor-services/eligibility-browser'


def persisted(database):
    queries={
        'requests':'SELECT id,requester_id,type,title,purpose,revision,faculty_declaration FROM resource_request ORDER BY id',
        'slots':'SELECT request_id,ordinal,day,start_minutes,end_minutes FROM request_slot ORDER BY request_id,ordinal',
        'eligibility':'SELECT request_id,origin,submitted_by,status,version,reviewed_revision,reviewer_id,reason FROM request_eligibility ORDER BY request_id',
        'events':'SELECT request_id,version,request_revision,status,actor_id,reason FROM eligibility_event ORDER BY id',
        'runs':'SELECT id,status,input_revision FROM allocation_run ORDER BY id',
        'decisions':'SELECT run_id,request_id,status FROM request_decision ORDER BY run_id,request_id',
        'allocations':'SELECT run_id,request_id,resource_id,day,start_minutes,end_minutes FROM allocation ORDER BY id',
        'state':'SELECT active_run_id,input_revision,calendar_revision FROM application_state',
    }
    with database.transaction(read_only=True) as session:
        return {kind:[dict(row) for row in session.execute(text(sql)).mappings()] for kind,sql in queries.items()}


def verify(posts):
    outcomes=[]
    for post in posts:
        before,after,path,form=post['before'],post['after'],post['path'],post['form']
        if post['status']>=400:
            assert before==after,('Rejected operation changed state',path)
            outcomes.append(dict(path=path,result='rejected; persisted state unchanged'))
        elif path in ('/login','/logout'):
            continue
        elif path=='/professor/requests/new':
            new=[r for r in after['requests'] if r['id'] not in {r['id'] for r in before['requests']}]
            assert len(new)==1
            row=new[0];meta=next(e for e in after['eligibility'] if e['request_id']==row['id'])
            assert row['requester_id']==2 and meta['submitted_by']==2 and meta['status']=='Pending Eligibility Review'
            assert before['allocations']==after['allocations'] and before['state'][0]['active_run_id']==after['state'][0]['active_run_id']
            outcomes.append(dict(path=path,result='self-owned pending submission; no allocation',id=row['id']))
        elif path.startswith('/academic-eligibility/'):
            key=int(path.rstrip('/').rsplit('/',1)[-1]);meta=next(e for e in after['eligibility'] if e['request_id']==key)
            assert meta['status']==('Eligible' if form['decision']=='approve' else 'Eligibility Rejected')
            assert meta['reviewer_id']==6 and meta['reviewed_revision']==int(form['revision'])
            assert before['allocations']==after['allocations'] and before['state'][0]['active_run_id']==after['state'][0]['active_run_id']
            outcomes.append(dict(path=path,result='review persisted; current reservation unchanged',id=key))
        elif path.endswith('/revise'):
            key=int(path.split('/')[3]);row=next(r for r in after['requests'] if r['id']==key)
            meta=next(e for e in after['eligibility'] if e['request_id']==key)
            assert row['revision']==int(form['revision'])+1 and meta['status']=='Pending Eligibility Review'
            assert meta['reviewer_id'] is None
            outcomes.append(dict(path=path,result='material revision invalidated eligibility',id=key))
        elif path=='/run-allocation':
            if before['state'][0]['active_run_id']==after['state'][0]['active_run_id']:
                assert before==after
                outcomes.append(dict(path=path,result='outstanding legacy review blocked replacement without mutation'))
            else:
                active=after['state'][0]['active_run_id']
                ids={d['request_id'] for d in after['decisions'] if d['run_id']==active}
                eligible={e['request_id'] for e in after['eligibility'] if e['status']=='Eligible'}
                assert ids==eligible
                assert all(a in after['allocations'] for a in before['allocations'])
                outcomes.append(dict(path=path,result='real engine replacement uses eligible requests only; history retained',ids=sorted(ids)))
        else:raise AssertionError(('Unaccounted POST',path))
    return outcomes


def main():
    if not os.environ.get('TEST_DATABASE_URL'):raise RuntimeError('Disposable PostgreSQL is required.')
    fixture=LegacyEligibilityMigrationTests();server=None;thread=None;posts=[];engines=[]
    try:
        fixture.setUp()
        with fixture.database.transaction() as session:
            advance_identity(session,Role)
            advance_identity(session,ResourceRequest)
            advance_identity(session,ResourceRequest,'submission_order')
            roles={r.name:r.id for r in session.scalars(select(Role))}
            for role in ('Student','Staff','TeachingAssistant'):
                value=Role(name=role);session.add(value);session.flush();roles[role]=value.id
            for key,role,name in ((1,'Student','Synthetic student'),(3,'Instructor','Synthetic peer professor'),
                                  (7,'Staff','Synthetic staff'),(9,'TeachingAssistant','Synthetic teaching assistant')):
                session.add(User(id=key,source_order=key+10,name=name,primary_role_id=roles[role]))
            session.add(Resource(id=302,source_order=2,type='MeetingRoom',name='Synthetic committee room',capacity=30,building='Main'))
        users={key:'eligibility-browser-'+str(key) for key in (1,2,3,6,7,9)}
        password='Synthetic-browser-gate-password'
        with fixture.database.transaction(read_only=True) as session:existing=set(session.scalars(select(LoginAccount.user_id)))
        for key,name in users.items():
            AccountService(fixture.database).provision(key,name,password,administrator=key==6,reset=key in existing)
        fixture.configure_web()
        web_app.app.config.update(TESTING=False,PROPAGATE_EXCEPTIONS=False)
        def before():
            if request.method=='POST':g.gate_before=persisted(fixture.database)
        def after(response):
            if request.method=='POST':
                posts.append(dict(path=request.path,status=response.status_code,
                    form={key:value for key,value in request.form.items() if key not in ('password','username','csrf_token')},
                    before=g.gate_before,after=persisted(fixture.database)))
            return response
        web_app.app.before_request_funcs[None].insert(0,before)
        web_app.app.after_request_funcs[None].append(after)
        fixture.addCleanup(web_app.app.before_request_funcs[None].remove,before)
        fixture.addCleanup(web_app.app.after_request_funcs[None].remove,after)
        original=EngineGateway._execute
        def trace(gateway,snapshot,mode,validator):
            if mode=='--json':
                keys=[r['id'] for r in snapshot['requests']]
                with fixture.database.transaction(read_only=True) as session:
                    eligible={r.id for r,e in session.execute(select(ResourceRequest,RequestEligibility).join(
                        RequestEligibility,RequestEligibility.request_id==ResourceRequest.id).where(
                        RequestEligibility.status=='Eligible',RequestEligibility.reviewed_revision==ResourceRequest.revision))}
                assert set(keys)<=eligible
                engines.append(dict(requestIds=keys,eligibleAtExecution=sorted(eligible),realEngine=True))
            return original(gateway,snapshot,mode,validator)
        with mock.patch.object(EngineGateway,'_execute',new=trace):
            server=make_server('127.0.0.1',0,web_app.app,threaded=True)
            thread=Thread(target=server.serve_forever,daemon=True);thread.start()
            output=ROOT/'build/eligibility-browser';output.mkdir(parents=True,exist_ok=True)
            info=output/'fixture.json'
            info.write_text(json.dumps(dict(url=f'http://127.0.0.1:{server.server_port}',users=users,password=password,ids=dict(legacy=1))),encoding='utf-8')
            OUTPUT.mkdir(parents=True,exist_ok=True)
            env=dict(os.environ,PROFESSOR_INFO_FILE=str(info),PROFESSOR_OUTPUT_DIR=str(OUTPUT))
            result=subprocess.run(['node',str(ROOT/'tests/professor/eligibility_browser.cjs')],cwd=ROOT,env=env,
                capture_output=True,text=True,encoding='utf-8',timeout=900)
            (OUTPUT/'browser-output.txt').write_text((result.stdout+'\n'+result.stderr).rstrip()+'\n',encoding='utf-8')
            (OUTPUT/'post-states.json').write_text(json.dumps(posts,indent=2,default=str)+'\n',encoding='utf-8')
            if result.returncode:raise RuntimeError('Eligibility browser failed; inspect browser-output.txt')
            verified=verify(posts)
            (OUTPUT/'persistence-verification.json').write_text(json.dumps(dict(posts=len(posts),verified=verified,engineInputs=engines),indent=2)+'\n',encoding='utf-8')
            print(json.dumps(dict(browserExit=0,posts=len(posts),verified=len(verified),engineRuns=len(engines))))
    finally:
        if server:server.shutdown();server.server_close();thread.join(timeout=10)
        if not fixture.doCleanups():raise RuntimeError('Owned browser fixture cleanup failed.')
        if thread and thread.is_alive():raise RuntimeError('Review server did not stop.')
        if hasattr(fixture,'schema'):
            from sqlalchemy import create_engine
            owner=create_engine(os.environ['TEST_DATABASE_URL'])
            try:
                with owner.connect() as connection:
                    assert not connection.scalar(text('SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=:schema)'),dict(schema=fixture.schema))
            finally:owner.dispose()
        OUTPUT.mkdir(parents=True,exist_ok=True)
        (OUTPUT/'cleanup.json').write_text(json.dumps(dict(schema=getattr(fixture,'schema',None),fixtureCleanup=True,schemaAbsent=True,serverStopped=True))+'\n',encoding='utf-8')


if __name__=='__main__':main()
