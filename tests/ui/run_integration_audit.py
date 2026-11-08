"""UI-10: owned PostgreSQL schemas, live Flask/browser and independent DB checks.

Each invocation seeds a fresh schema. Servers shut down before fixture cleanup,
including failed browser assertions. No operational URL or records are used.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
import subprocess
import sys
from threading import Thread
import time
import uuid
from unittest import mock
from flask import g, request

from portal_preview import ROOT, RoomFixture, seed, web_app
from sqlalchemy import select, text
from werkzeug.serving import make_server
from web.account_service import AccountService
from web.engine_gateway import EngineGateway
from web.equipment_service import EquipmentService
from web.persistence.models import LoginAccount, Role, User

OUTPUT = Path(os.environ.get('PORTAL_REVIEW_OUTPUT', str(ROOT / 'docs/ui/student-portal/UI-10')))
BUILD = ROOT / os.environ.get('PORTAL_BUILD_DIR', 'build/ui10')
POST_STATES = []
ACTIVE_FIXTURE = None


def record_before_post():
    if ACTIVE_FIXTURE is not None and request.method == 'POST':
        g.ui10_before = persisted(ACTIVE_FIXTURE)


# Capture before existing CSRF/auth guards, including rejected requests. This is
# confined to this review executable; importing the production app adds no hook.
web_app.app.before_request_funcs[None].insert(0, record_before_post)


@web_app.app.after_request
def record_committed_post(response):
    # Review-process instrumentation only: never installed by application code.
    if ACTIVE_FIXTURE is not None and request.method == 'POST':
        POST_STATES.append(dict(path=request.path, status=response.status_code,
            before=getattr(g, 'ui10_before', None), persisted=persisted(ACTIVE_FIXTURE)))
    return response


@contextmanager
def review(fault=False):
    if not os.environ.get('TEST_DATABASE_URL'):
        raise RuntimeError('An isolated TEST_DATABASE_URL is required.')
    fixture = RoomFixture()
    server = None
    try:
        fixture.setUp()
        ids = seed(fixture)
        with fixture.database.transaction() as session:
            role = session.scalar(select(Role.id).where(Role.name == 'TeachingAssistant'))
            if role is None:
                role_row = Role(name='TeachingAssistant')
                session.add(role_row)
                session.flush()
                role = role_row.id
            session.add(User(id=9, source_order=9, name='Fictional UI10 Teaching Assistant', primary_role_id=role))
        equipment = EquipmentService(fixture.database, EngineGateway(ROOT))
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        with mock.patch('web.equipment_service.datetime', wraps=datetime) as clock:
            clock.now.return_value = now - timedelta(hours=2)
            ids['collection'] = equipment.submit(1, fixture.faculty,
                [dict(typeId=ids['equipmentType'], quantity=2)], now - timedelta(hours=1),
                now + timedelta(days=2), 'Fictional UI10 physical collection', '', uuid.uuid4().hex)
            equipment.decide(7, ids['collection'], True)
        accounts = AccountService(fixture.database)
        users = {1:'ui10-student', 2:'ui10-professor', 3:'ui10-second-professor', 4:'ui10-peer',
                 5:'ui10-empty', 6:'ui10-admin', 7:'ui10-staff', 8:'ui10-warning', 9:'ui10-ta'}
        password = 'Fictional-UI10-disposable-password'
        with fixture.database.transaction(read_only=True) as session:
            existing = set(session.scalars(select(LoginAccount.user_id)))
        for actor, username in users.items():
            accounts.provision(actor, username, password, administrator=actor == 6, reset=actor in existing)
        web_app.app.config.update(DATABASE_URL=fixture.url, SECRET_KEY='fictional-ui10-isolated-session-key',
            TESTING=False, PROPAGATE_EXCEPTIONS=False, BACKEND_TIMEOUT=0.000001 if fault else 30)
        web_app.app.jinja_env.auto_reload = True
        server = make_server('127.0.0.1', 0, web_app.app, threaded=True)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        info = dict(url=f'http://127.0.0.1:{server.server_port}', users=users, password=password,
                    ids=ids, week='2030-01-07', schema=fixture.schema,
                    routes=[dict(rule=str(rule), endpoint=rule.endpoint, methods=sorted(rule.methods))
                            for rule in web_app.app.url_map.iter_rules()])
        info_file = BUILD / ('fault.json' if fault else 'preview.json')
        info_file.parent.mkdir(parents=True, exist_ok=True)
        info_file.write_text(json.dumps(info, indent=2) + '\n', encoding='utf-8')
        yield fixture, info_file
    finally:
        if server:
            server.shutdown()
            server.server_close()
            thread.join(timeout=10)
        fixture.dispose_web_database()
        if not fixture.doCleanups():
            raise RuntimeError('An owned review fixture failed to clean up.')


def persisted(fixture):
    """Read committed rows over a new transaction, independently of browser HTML."""
    queries = {
        'appointments': 'SELECT id,organizer_id,purpose,status,revision,start_at,end_at FROM appointment ORDER BY id',
        'professors': 'SELECT appointment_id, user_id, revision, decision FROM appointment_professor ORDER BY appointment_id,user_id',
        'invitations': 'SELECT appointment_id,user_id,status FROM appointment_invitation ORDER BY appointment_id,user_id',
        'commitments': 'SELECT appointment_id,user_id FROM appointment_commitment ORDER BY appointment_id,user_id',
        'rooms': 'SELECT id,purpose,status,revision,resource_id,approved_revision,approved_by FROM student_room_request ORDER BY id',
        'roomInvitations': 'SELECT request_id,user_id,revision,status FROM room_invitation ORDER BY request_id,user_id',
        'roomReservations': 'SELECT request_id,occurrence_id FROM room_reservation ORDER BY request_id,occurrence_id',
        'equipment': 'SELECT id,purpose,status,due_at FROM borrow_request ORDER BY id',
        'assets': 'SELECT r.id,i.request_id,r.unit_id,r.handed_at,r.returned_at,r.released,r.due_at FROM equipment_reservation r JOIN borrow_item i ON i.id=r.item_id ORDER BY r.id',
        'extensions': 'SELECT id,request_id,status,due_at FROM borrow_extension ORDER BY id',
        'waiting': 'SELECT id,status,room_request_id,borrow_request_id,approved_by FROM waiting_list_entry ORDER BY id',
        'feedback': 'SELECT id,status,description,revision,response FROM resource_feedback ORDER BY id',
        'feedbackEvents': 'SELECT report_id,revision,message FROM feedback_event ORDER BY id',
        'series': 'SELECT id,room_request_id,borrow_request_id,approval_mode FROM reservation_series ORDER BY id',
        'occurrences': 'SELECT id,series_id,status,decided_by FROM reservation_occurrence ORDER BY id',
        'blocks': 'SELECT id,user_id,reason FROM calendar_block ORDER BY id',
        'notifications': 'SELECT recipient_id,count(*) AS total,count(read_at) AS read FROM notification GROUP BY recipient_id ORDER BY recipient_id',
        'notificationReadStates': 'SELECT id,recipient_id,read_at FROM notification ORDER BY id',
    }
    with fixture.database.transaction(read_only=True) as session:
        return {name:[dict(row) for row in session.execute(text(sql)).mappings()] for name,sql in queries.items()}


def main():
    global ACTIVE_FIXTURE
    mode = sys.argv[1]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if mode == 'serve-fault':
        with review(True):
            print('ready', flush=True)
            sys.stdin.readline()
        return
    fault = None
    try:
        if mode == 'browser':
            fault_info = BUILD / 'fault.json'
            if fault_info.exists():
                fault_info.unlink()  # This invocation's fixed metadata file, never a schema.
            fault_log = (BUILD / 'fault.log').open('w', encoding='utf-8')
            fault = subprocess.Popen([sys.executable, '-B', __file__, 'serve-fault'], cwd=ROOT,
                stdin=subprocess.PIPE, stdout=fault_log, stderr=subprocess.STDOUT, text=True)
            deadline = time.monotonic() + 240
            while not fault_info.exists():
                if fault.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('Fault fixture did not become ready; inspect build/ui10/fault.log.')
                time.sleep(.2)
        with review() as (fixture, info_file):
            ACTIVE_FIXTURE = fixture
            output = OUTPUT / ('browser' if mode == 'browser' else mode)
            output.mkdir(parents=True, exist_ok=True)
            before = persisted(fixture)
            env = {**os.environ, 'PORTAL_INFO_FILE':str(info_file), 'PORTAL_OUTPUT_DIR':str(output),
                   'PORTAL_FAULT_INFO_FILE':str(BUILD / 'fault.json')}
            script = ('audit_portal_browser.cjs' if mode == 'browser' else
                      'exercise_portal.cjs' if mode.startswith('UI-0') else
                      'check_loading_states.cjs' if mode == 'loading' else
                      'audit_equipment_lifecycles.cjs' if mode == 'equipment-lifecycles' else
                      'audit_authorization.cjs' if mode == 'authorization' else 'audit_integrations.cjs')
            result = subprocess.run(['node', str(ROOT / 'tests/ui' / script), mode], cwd=ROOT, env=env)
            after = persisted(fixture)
            (output / 'persistence.json').write_text(json.dumps(dict(before=before, after=after),
                indent=2, default=str) + '\n', encoding='utf-8')
            (output / 'post-states.json').write_text(json.dumps(POST_STATES, indent=2, default=str)+'\n', encoding='utf-8')
            if result.returncode:
                raise RuntimeError(f'{mode} browser assertions failed ({result.returncode}).')
            if mode.startswith('UI-0'):
                assert before != after, 'Workflow must persist actual mutations.'
            print(f'{mode}: browser assertions passed; committed rows recorded; owned schema {fixture.schema} will be removed.', flush=True)
            ACTIVE_FIXTURE = None
        (output / 'cleanup.json').write_text(json.dumps(dict(schema=fixture.schema, removed=True))+'\n', encoding='utf-8')
    finally:
        if fault:
            fault.communicate('stop\n', timeout=60)
            fault_log.close()
            if fault.returncode:
                raise RuntimeError('Fault review process failed to clean up.')
            (OUTPUT/'browser/fault-cleanup.json').write_text(json.dumps(dict(
                schema=json.loads((BUILD/'fault.json').read_text(encoding='utf-8'))['schema'],
                removed=True))+'\n',encoding='utf-8')


if __name__ == '__main__':
    main()
