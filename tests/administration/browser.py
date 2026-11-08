"""Live Flask/Edge acceptance with owned PostgreSQL fixtures and committed reads."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread
from unittest import mock
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'tests'), str(ROOT/'tests/professor'), str(ROOT)]
from flask import g, request
from sqlalchemy import select, text
from werkzeug.serving import make_server
from test_professor_services import ProfessorFixture
from test_appointments import START
from eligibility_browser import persisted as academic_state
from eligibility_browser import verify as verify_academic
from web import app as web_app
from web.account_service import AccountService
from web.equipment_service import EquipmentService
from web.feedback_service import FeedbackService
from web.waiting_list_service import WaitingListService, POLICY_VERSION
from web.academic_eligibility import EligibilityService
from web.allocation_workflow import execute_allocation
from web.persistence.models import LoginAccount, Notification, Role, User


def state(database):
    queries = {
        'rooms': 'SELECT id,status,revision,approved_by FROM student_room_request ORDER BY id',
        'roomReservations': 'SELECT request_id,resource_id,start_at,end_at FROM room_reservation ORDER BY request_id,start_at',
        'loans': 'SELECT id,status,due_at FROM borrow_request ORDER BY id',
        'assets': 'SELECT r.id,i.request_id,r.unit_id,r.handed_at,r.returned_at,r.released FROM equipment_reservation r JOIN borrow_item i ON i.id=r.item_id ORDER BY r.id',
        'waiting': 'SELECT id,status,approved_by FROM waiting_list_entry ORDER BY id',
        'feedback': 'SELECT id,status,revision,response FROM resource_feedback ORDER BY id',
        'notifications': 'SELECT id,recipient_id,read_at FROM notification ORDER BY id',
        'publication': 'SELECT id,calendar_public,academic_instructor_id FROM resource_request ORDER BY id',
        'bindings': 'SELECT id,request_id,period_id FROM legacy_calendar_binding ORDER BY id',
        'configuration': 'SELECT strategy,waiting_notice_minutes,recurring_limits,reservation_priorities FROM application_state',
        'units': 'SELECT id,type_id,asset_tag,condition,notes FROM equipment_unit ORDER BY id',
        'custodians': 'SELECT faculty_id,user_id FROM equipment_custodian ORDER BY faculty_id',
        'equipmentEvents': 'SELECT id,request_id,faculty_id,actor_id,message FROM equipment_event ORDER BY id',
        'periods': 'SELECT id,name,start_date,end_date FROM academic_period ORDER BY id',
        'feedbackEvents': 'SELECT id,report_id,revision,actor_id,message FROM feedback_event ORDER BY id',
    }
    with database.transaction(read_only=True) as session:
        result = {key: [dict(r) for r in session.execute(text(sql)).mappings()] for key, sql in queries.items()}
    result['academic'] = academic_state(database)
    return result


def verify(posts):
    outcomes = []
    for post in posts:
        if post['path'] in ('/login', '/logout'):
            continue
        if post['path'].startswith(('/academic-eligibility/', '/professor/requests')) or post['path'] == '/run-allocation':
            entry = dict(post, before=post['before']['academic'], after=post['after']['academic'])
            outcomes.extend(verify_academic([entry]))
            continue
        if post['status'] >= 400:
            assert post['before'] == post['after'], ('Rejected mutation changed domain data', post['path'])
            outcomes.append(dict(path=post['path'], result='rejected; committed domain state unchanged'))
        elif post['path'] == '/set-strategy':
            assert post['after']['academic']['state'][0]['input_revision'] > post['before']['academic']['state'][0]['input_revision']
            assert post['after']['configuration'][0]['strategy'] == post['form']['strategy']
            outcomes.append(dict(path=post['path'], result='strategy input revision committed'))
        elif post['path'].startswith('/rooms/') and post['path'].endswith('/decision'):
            key = int(post['path'].split('/')[2])
            assert next(r for r in post['after']['rooms'] if r['id']==key)['status'] == 'Confirmed'
            assert any(r['request_id']==key for r in post['after']['roomReservations'])
            outcomes.append(dict(path=post['path'], result='faculty decision and reservation committed'))
        elif post['path'].startswith('/equipment/inventory/'):
            assert post['form']['action']=='unit'
            assert len(post['after']['units'])==len(post['before']['units'])+1
            assert any(r['asset_tag']==post['form']['asset_tag'] for r in post['after']['units'])
            outcomes.append(dict(path=post['path'], result='unique physical asset registered in owning faculty'))
        elif post['path'].startswith('/equipment/') and post['path'].split('/')[-1] in ('approve','handover','return'):
            key = int(post['path'].split('/')[2]); action=post['path'].split('/')[-1]
            expected={'approve':'Approved','handover':'Borrowed','return':'Partially Returned'}[action]
            assert next(r for r in post['after']['loans'] if r['id']==key)['status']==expected
            assets=[r for r in post['after']['assets'] if r['request_id']==key]
            if action=='approve': assert assets and all(r['handed_at'] is None for r in assets)
            elif action=='handover': assert assets and all(r['handed_at'] is not None for r in assets)
            else: assert sum(r['returned_at'] is not None for r in assets)==1 and len(assets)==2
            outcomes.append(dict(path=post['path'], result=expected+' persisted with physical asset checks'))
        elif post['path']=='/appointments/calendar-setup':
            assert len(post['after']['bindings'])==len(post['before']['bindings'])+1
            assert any(r['request_id']==int(post['form']['requestId']) for r in post['after']['bindings'])
            assert post['before']['academic']['allocations']==post['after']['academic']['allocations']
            outcomes.append(dict(path=post['path'], result='explicit applicability committed; allocation unchanged'))
        elif post['path']=='/calendar/publications':
            row=next(r for r in post['after']['publication'] if r['id']==int(post['form']['id']))
            assert row['calendar_public'] is True and row['academic_instructor_id']==2
            assert post['before']['academic']['allocations']==post['after']['academic']['allocations']
            outcomes.append(dict(path=post['path'], result='calendar visibility and explicit attribution persisted'))
        elif post['path']=='/waiting-lists/configuration':
            if post['form'].get('action')=='semester':
                assert any(r['name']==post['form']['name'] and str(r['start_date'])==post['form']['start']
                    and str(r['end_date'])==post['form']['end'] for r in post['after']['periods'])
            else: assert post['after']['configuration'][0]['waiting_notice_minutes']==int(post['form']['noticeMinutes'])
            outcomes.append(dict(path=post['path'], result='explicit policy configuration committed'))
        elif post['path'].startswith('/waiting-lists/') and post['path'].endswith('/review'):
            key=int(post['path'].split('/')[2]); row=next(r for r in post['after']['waiting'] if r['id']==key)
            assert row['status']=='Preapproved' and row['approved_by']==6
            assert post['before']['assets']==post['after']['assets']
            outcomes.append(dict(path=post['path'], result='preapproval persisted without reservation'))
        elif post['path'].startswith('/equipment/') and post['path'].endswith('/cancel'):
            key=int(post['path'].split('/')[2])
            assert next(r for r in post['after']['loans'] if r['id']==key)['status']=='Cancelled'
            assert any(r['status']=='Assigned' for r in post['after']['waiting'])
            assert all(r['released'] for r in post['after']['assets'] if r['request_id']==key)
            outcomes.append(dict(path=post['path'], result='stock release and automatic waiting assignment committed'))
        elif post['path']=='/waiting-lists/refresh':
            assert post['before']['assets']==post['after']['assets']
            outcomes.append(dict(path=post['path'], result='repeat recheck created no duplicate reservation'))
        elif post['path'].startswith('/feedback/') and post['path'].endswith('/update'):
            key=int(post['path'].split('/')[2]); row=next(r for r in post['after']['feedback'] if r['id']==key)
            assert row['revision']==int(post['form']['revision'])+1
            assert len(post['after']['feedbackEvents'])==len(post['before']['feedbackEvents'])+1
            if post['form']['action']=='review': assert row['status']==post['form']['status'] and row['response']==post['form']['response']
            assert post['before']['assets']==post['after']['assets']
            outcomes.append(dict(path=post['path'], result='private response/clarification and audit committed without inventory mutation'))
        elif post['path']=='/notifications/read':
            key=int(post['form'].get('id',post['form'].get('throughId')))
            targets=[r for r in post['after']['notifications'] if r['recipient_id']==6 and
                (r['id']==key if 'id' in post['form'] else r['id']<=key)]
            assert targets and all(r['read_at'] is not None for r in targets)
            assert [r for r in post['before']['notifications'] if r['recipient_id']!=6]==[
                r for r in post['after']['notifications'] if r['recipient_id']!=6]
            outcomes.append(dict(path=post['path'], result='recipient read state committed; other recipients unchanged'))
        else:
            raise AssertionError(('Unverified successful domain mutation', post['path']))
    return outcomes


def main():
    if not os.environ.get('TEST_DATABASE_URL'):
        raise RuntimeError('Disposable PostgreSQL required.')
    phase = os.environ.get('ADMIN_PHASE', 'ADM-UI-01')
    output = ROOT/'build/administration/browser'/os.environ.get('ADMIN_OUTPUT_NAME', phase)
    output.mkdir(parents=True, exist_ok=True)
    fixture = ProfessorFixture(); server = thread = None; posts = []
    try:
        fixture.setUp()
        with fixture.database.transaction() as session:
            session.get(User, 6).name = 'Synthetic Administrator'
            role = session.scalar(select(Role.id).where(Role.name == 'TeachingAssistant'))
            session.add(User(id=9, source_order=9, name='Synthetic Teaching Assistant', primary_role_id=role))
        empty = os.environ.get('ADMIN_EMPTY') == '1'
        ids = dict(faculty=fixture.faculty, otherFaculty=fixture.other_faculty)
        if not empty:
            ids['room'] = fixture.request_room(room=301, purpose='Synthetic student study room')
            ids['foreignRoom'] = fixture.request_room(room=302, start=START+timedelta(days=1), purpose='Other faculty room')
            ids['academic'] = fixture.academic_request(day=3, title='Synthetic teaching declaration')
        if phase=='ADM-UI-05':
            fixture.request_room(room=301,start=START+timedelta(days=2),purpose='Synthetic second faculty decision')
            with fixture.database.transaction(read_only=True) as session:
                ids['foreignNotification']=session.scalar(select(Notification.id).where(Notification.recipient_id==7).order_by(Notification.id))
        if phase in ('ADM-UI-03','ADM-UI-04','ADM-UI-06'):
            equipment = EquipmentService(fixture.database, fixture.rooms.gateway)
            equipment.assign_custodian(6, fixture.faculty, 6)
            equipment.assign_custodian(6, fixture.other_faculty, 7)
            ids['equipmentType'] = equipment.create_type(6, fixture.faculty, 'Teaching kits',
                'Synthetic teaching kit', 'Synthetic university equipment', {'architecture':'arm'}, 14, 'Faculty equipment desk')
            ids['units'] = [equipment.add_unit(6, ids['equipmentType'], 'SYN-ADMIN-'+str(n)) for n in (1,2)]
            ids['equipment'] = equipment.submit(1, fixture.faculty, [dict(typeId=ids['equipmentType'],quantity=1)],
                START, START+timedelta(days=2), 'Synthetic future borrowing request', '', uuid.uuid4().hex)
            now=datetime.now(timezone.utc).replace(second=0,microsecond=0)
            with mock.patch('web.equipment_service.datetime', wraps=datetime) as clock:
                clock.now.return_value=now-timedelta(hours=2)
                ids['collection']=equipment.submit(1,fixture.faculty,[dict(typeId=ids['equipmentType'],quantity=2)],
                    now-timedelta(hours=1),now+timedelta(days=2),'Synthetic physical collection','',uuid.uuid4().hex)
                equipment.decide(6,ids['collection'],True)
            if phase in ('ADM-UI-04','ADM-UI-06'):
                equipment.handover(6,ids['collection'],'Synthetic inspected collection fixture')
                feedback=FeedbackService(fixture.database)
                resource=feedback.context('equipment',ids['collection'],1)['resources'][0]['id']
                ids['feedback']=feedback.submit(1,'equipment',ids['collection'],resource,'problem',
                    'Synthetic cable inspection needed',False,uuid.uuid4().hex)
                waiting=WaitingListService(fixture.database,fixture.rooms.gateway)
                waiting.configure_notice(6,60)
                kind=equipment.create_type(6,fixture.faculty,'Teaching kits','Synthetic queue kit','Queue fixture',{},14,'Faculty desk')
                equipment.add_unit(6,kind,'SYN-QUEUE-1')
                start=START+timedelta(days=7); end=start+timedelta(days=1)
                ids['occupied']=equipment.submit(4,fixture.faculty,[dict(typeId=kind,quantity=1)],start,end,'Synthetic occupied stock','',uuid.uuid4().hex)
                equipment.decide(6,ids['occupied'],True)
                ids['waiting']=waiting.join_equipment(1,fixture.faculty,[dict(typeId=kind,quantity=1)],start,end,
                    'Synthetic waiting activity','',POLICY_VERSION,True,uuid.uuid4().hex)
                EligibilityService(fixture.database).decide(6,ids['academic'],1,0,True,'Synthetic verified eligibility')
                execute_allocation(fixture.repository,fixture.rooms.gateway)
        users = {key: 'admin-browser-'+str(key) for key in (1, 2, 3, 4, 6, 7, 9)}
        password = uuid.uuid4().hex
        with fixture.database.transaction(read_only=True) as session:
            existing = set(session.scalars(select(LoginAccount.user_id)))
        for key, username in users.items():
            AccountService(fixture.database).provision(key, username, password,
                administrator=key == 6, reset=key in existing)
        def before():
            if request.method == 'POST': g.admin_before = state(fixture.database)
        def after(response):
            if request.method == 'POST':
                posts.append(dict(path=request.path, status=response.status_code,
                    form={key: request.form.getlist(key) if len(request.form.getlist(key)) > 1 else value
                          for key, value in request.form.items() if key not in ('password','username','csrf_token')},
                    before=g.admin_before, after=state(fixture.database)))
            return response
        web_app.app.before_request_funcs[None].insert(0, before)
        web_app.app.after_request_funcs[None].append(after)
        fixture.addCleanup(web_app.app.before_request_funcs[None].remove, before)
        fixture.addCleanup(web_app.app.after_request_funcs[None].remove, after)
        web_app.app.config.update(TESTING=False, PROPAGATE_EXCEPTIONS=False)
        server = make_server('127.0.0.1', 0, web_app.app, threaded=True)
        thread = Thread(target=server.serve_forever, daemon=True); thread.start()
        info = output/'fixture.json'
        info.write_text(json.dumps(dict(url=f'http://127.0.0.1:{server.server_port}', users=users,
            roles={1:'Student',2:'Instructor',3:'Instructor',4:'Student',6:'Administrator',7:'Staff',9:'TeachingAssistant'},
            password=password, ids=ids)), encoding='utf-8')
        env = dict(os.environ, PROFESSOR_INFO_FILE=str(info), PROFESSOR_OUTPUT_DIR=str(output),
            PROFESSOR_INDEPENDENT_AUDIT='1')
        result = subprocess.run(['node', str(ROOT/'tests/administration/browser.cjs')], env=env, cwd=ROOT,
            capture_output=True, text=True, encoding='utf-8', timeout=900)
        (output/'browser-output.txt').write_text(result.stdout+'\n'+result.stderr, encoding='utf-8')
        (output/'post-states.json').write_text(json.dumps(posts, default=str, indent=2), encoding='utf-8')
        if result.returncode:
            raise RuntimeError('Browser failed: '+result.stderr[-1800:])
        outcomes = verify(posts)
        (output/'persistence-verification.json').write_text(json.dumps(dict(posts=len(posts), outcomes=outcomes), indent=2), encoding='utf-8')
        print(json.dumps(dict(phase=phase, exitCode=0, posts=len(posts), verifiedOutcomes=len(outcomes))))
    finally:
        if server: server.shutdown(); server.server_close(); thread.join(timeout=10)
        if not fixture.doCleanups(): raise RuntimeError('Fixture cleanup failed.')
        if thread and thread.is_alive(): raise RuntimeError('Server did not stop.')
        if hasattr(fixture, 'schema'):
            with fixture.owner.connect() as connection:
                # cleanup_schema has disposed the engine, but a new read can prove absence.
                assert not connection.scalar(text('SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=:s)'), dict(s=fixture.schema))
            fixture.owner.dispose()
        (output/'cleanup.json').write_text(json.dumps(dict(schema=getattr(fixture,'schema',None), absent=True, serverStopped=True)), encoding='utf-8')


if __name__ == '__main__': main()
