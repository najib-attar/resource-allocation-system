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
from web import app as web_app
from web.account_service import AccountService
from web.equipment_service import EquipmentService
from web.persistence.models import LoginAccount, Role, User


def state(database):
    queries = {
        'rooms': 'SELECT id,status,revision,approved_by FROM student_room_request ORDER BY id',
        'roomReservations': 'SELECT request_id,resource_id,start_at,end_at FROM room_reservation ORDER BY request_id,start_at',
        'loans': 'SELECT id,status,due_at FROM borrow_request ORDER BY id',
        'assets': 'SELECT id,unit_id,handed_at,returned_at,released FROM equipment_reservation ORDER BY id',
        'waiting': 'SELECT id,status,approved_by FROM waiting_list_entry ORDER BY id',
        'feedback': 'SELECT id,status,revision,response FROM resource_feedback ORDER BY id',
        'notifications': 'SELECT id,recipient_id,read_at FROM notification ORDER BY id',
        'publication': 'SELECT id,calendar_public,academic_instructor_id FROM resource_request ORDER BY id',
        'bindings': 'SELECT id,request_id,period_id FROM legacy_calendar_binding ORDER BY id',
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
        if post['status'] >= 400:
            assert post['before'] == post['after'], ('Rejected mutation changed domain data', post['path'])
            outcomes.append(dict(path=post['path'], result='rejected; committed domain state unchanged'))
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
        empty = os.environ.get('ADMIN_EMPTY') == '1'
        ids = dict(faculty=fixture.faculty, otherFaculty=fixture.other_faculty)
        if not empty:
            ids['room'] = fixture.request_room(room=301, purpose='Synthetic student study room')
            ids['foreignRoom'] = fixture.request_room(room=302, start=START+timedelta(days=1), purpose='Other faculty room')
            ids['academic'] = fixture.academic_request(day=3, title='Synthetic teaching declaration')
        with fixture.database.transaction() as session:
            session.get(User, 6).name = 'Synthetic Administrator'
            role = session.scalar(select(Role.id).where(Role.name == 'TeachingAssistant'))
            session.add(User(id=9, source_order=9, name='Synthetic Teaching Assistant', primary_role_id=role))
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
