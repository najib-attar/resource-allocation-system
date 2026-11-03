"""Actual Flask/browser/committed-state professor review in one disposable schema."""
from datetime import date, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tests'), str(ROOT)]
from flask import g, request
from sqlalchemy import select, text
from werkzeug.serving import make_server
from auth_fixtures import TEST_SECRET
from test_professor_services import ProfessorFixture
from test_appointments import START
from web import app as web_app
from web.account_service import AccountService
from web.persistence.models import LoginAccount, ProfessorAvailability, Role, User

OUTPUT = ROOT / 'docs/professor-services/browser'
BUILD = ROOT / 'build/professor-review'


def persisted(fixture):
    queries = {
        'hours': 'SELECT id,user_id,day,start_minutes,end_minutes,valid_from,valid_until,excluded_dates FROM professor_availability ORDER BY id',
        'appointments': 'SELECT id,status,revision,start_at,end_at FROM appointment ORDER BY id',
        'approvals': 'SELECT appointment_id,user_id,revision,decision FROM appointment_professor ORDER BY appointment_id,user_id',
        'commitments': 'SELECT appointment_id,user_id FROM appointment_commitment ORDER BY appointment_id,user_id',
        'blocks': 'SELECT id,user_id,reason FROM calendar_block ORDER BY id',
        'rooms': 'SELECT id,status,approved_by,approved_revision FROM student_room_request ORDER BY id',
        'invitations': 'SELECT request_id,user_id,status FROM room_invitation ORDER BY request_id,user_id',
        'roomReservations': 'SELECT request_id FROM room_reservation ORDER BY request_id',
        'notifications': 'SELECT id,recipient_id,read_at FROM notification ORDER BY id',
        'academic': 'SELECT id,requester_id,type,revision FROM resource_request ORDER BY id',
        'state': 'SELECT input_revision,active_run_id,calendar_revision FROM application_state',
    }
    with fixture.database.transaction(read_only=True) as session:
        return {key:[dict(row) for row in session.execute(text(sql)).mappings()]
                for key, sql in queries.items()}


def verify(operations):
    """Assert persistence independently of browser text or redirect responses."""
    checked = []
    for record in operations:
        before, after, path, form = record['before'], record['after'], record['path'], record['form']
        action = form.get('action')
        def one(kind, key, value):
            return next(row for row in after[kind] if row[key] == value)
        if record['status'] >= 400:
            assert before == after, ('Rejected mutation changed persisted state', path)
            checked.append(dict(path=path, result='rejected; state unchanged'))
        elif path == '/appointments/availability':
            if action == 'hours':
                added = [r for r in after['hours'] if r['id'] not in {x['id'] for x in before['hours']}]
                assert len(added) == 1 and added[0]['user_id'] == 2
                assert added[0]['excluded_dates'] == ['2030-01-15']
            else:
                assert not any(r['id'] == int(form['id']) for r in after['hours'])
            checked.append(dict(path=path, result='own availability mutation persisted'))
        elif path == '/appointments/calendar':
            if action == 'block':
                assert any(r['reason'] == 'Professor review private block' and r['user_id'] == 2 for r in after['blocks'])
            else:
                assert not any(r['id'] == int(form['id']) for r in after['blocks'])
            checked.append(dict(path=path, result='own block mutation persisted'))
        elif path.startswith('/appointments/') and path.rsplit('/', 1)[-1] in ('decision','reschedule','cancel'):
            key = int(path.split('/')[2])
            row = one('appointments', 'id', key)
            current = [r for r in after['approvals'] if r['appointment_id'] == key]
            commitments = [r for r in after['commitments'] if r['appointment_id'] == key]
            if path.endswith('/reschedule'):
                assert row['revision'] == int(form['revision']) + 1
                assert row['status'] == 'Pending Approval' and not commitments
                assert all(r['decision'] == 'Pending' and r['revision'] == row['revision'] for r in current)
            elif path.endswith('/cancel'):
                assert row['status'] == 'Cancelled' and not commitments
            elif form['decision'] == 'decline':
                assert row['status'] == 'Declined' and not commitments
            elif row['status'] == 'Confirmed':
                assert all(r['decision'] == 'Approved' for r in current)
                assert {r['user_id'] for r in commitments} == {1, *[r['user_id'] for r in current]}
            else:
                assert row['status'] == 'Pending Approval' and not commitments
            checked.append(dict(path=path, result='appointment revision/approvals/commitments persisted'))
        elif path.startswith('/rooms/') and path.endswith('/invitation'):
            key = int(path.split('/')[2])
            invitation = next(r for r in after['invitations'] if r['request_id'] == key and r['user_id'] == 2)
            assert invitation['status'] == ('Accepted' if form['response'] == 'accept' else 'Declined')
            assert one('rooms', 'id', key)['status'] == 'Pending Faculty Approval'
            assert not any(r['request_id'] == key for r in after['roomReservations'])
            checked.append(dict(path=path, result='optional response persisted; no approval or reservation'))
        elif path == '/notifications/read':
            assert any(r['recipient_id'] == 2 and r['read_at'] is not None for r in after['notifications'])
            checked.append(dict(path=path, result='recipient read state persisted'))
        elif path not in ('/login', '/logout'):
            raise AssertionError(('Unaccounted successful POST', path))
    return checked


def main():
    if not os.environ.get('TEST_DATABASE_URL'):
        raise RuntimeError('A disposable PostgreSQL TEST_DATABASE_URL is required.')
    fixture, server, thread = ProfessorFixture(), None, None
    operations = []
    try:
        fixture.setUp()
        confirmed = fixture.submit()
        fixture.service.decide(confirmed, 2, 1, True)
        multi = fixture.submit(professors=(2,3), start=START + timedelta(hours=1))
        decline = fixture.submit(start=START + timedelta(hours=2))
        accept_room = fixture.request_room(invitees=(2,), start=START + timedelta(days=3))
        decline_room = fixture.request_room(invitees=(2,), start=START + timedelta(days=4))
        fixture.service.block(3, START + timedelta(days=2, hours=4), START + timedelta(days=2, hours=5), 'PRIVATE PEER BLOCK')
        own = fixture.academic_request(day=2)
        rejected = fixture.academic_request('Exam', day=3, participantCount=999)
        other = fixture.academic_request(actor=3, day=6, title='PRIVATE OTHER PROFESSOR REQUEST')
        for key in (own, other):
            fixture.service.bind_legacy('Fictional professor academic week', date(2030,1,7), date(2030,1,31),
                                       request_id=key, week_start=date(2030,1,7))
        fixture.publish()
        pending = fixture.academic_request('CommitteeMeeting', day=5)
        with fixture.database.transaction() as session:
            role_id = session.scalar(select(Role.id).where(Role.name == 'TeachingAssistant'))
            session.add(User(id=9, source_order=9, name='Fictional professor review TA', primary_role_id=role_id))
        users = {1:'prof-review-student',2:'prof-review-instructor',3:'prof-review-peer',
                 6:'prof-review-admin',7:'prof-review-staff',9:'prof-review-ta'}
        password = 'Synthetic-professor-review-password'
        with fixture.database.transaction(read_only=True) as session:
            existing = set(session.scalars(select(LoginAccount.user_id)))
            foreign_hours = session.scalar(select(ProfessorAvailability.id).where(ProfessorAvailability.user_id == 3))
        for actor, username in users.items():
            AccountService(fixture.database).provision(actor, username, password,
                                                       administrator=actor == 6, reset=actor in existing)
        ids = dict(confirmed=confirmed,multi=multi,decline=decline,roomAccept=accept_room,roomDecline=decline_room,
                   own=own,rejected=rejected,other=other,pending=pending,foreignHours=foreign_hours)

        def before():
            if request.method == 'POST':
                g.professor_before = persisted(fixture)
        def after(response):
            if request.method == 'POST':
                # No credentials, cookies or CSRF tokens in tracked evidence.
                form = {k:v for k,v in request.form.items() if k not in ('password','csrf_token','username')}
                operations.append(dict(path=request.path,status=response.status_code,form=form,
                    before=g.professor_before,after=persisted(fixture)))
            return response
        web_app.app.before_request_funcs[None].insert(0, before)
        web_app.app.after_request_funcs[None].append(after)
        fixture.addCleanup(web_app.app.before_request_funcs[None].remove, before)
        fixture.addCleanup(web_app.app.after_request_funcs[None].remove, after)
        web_app.app.config.update(SECRET_KEY=TEST_SECRET, TESTING=False, PROPAGATE_EXCEPTIONS=False)
        server = make_server('127.0.0.1', 0, web_app.app, threaded=True)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        OUTPUT.mkdir(parents=True, exist_ok=True)
        BUILD.mkdir(parents=True, exist_ok=True)
        info = BUILD / 'fixture.json'
        info.write_text(json.dumps(dict(url=f'http://127.0.0.1:{server.server_port}',users=users,
                                       password=password,ids=ids)), encoding='utf-8')
        env = dict(os.environ, PROFESSOR_INFO_FILE=str(info), PROFESSOR_OUTPUT_DIR=str(OUTPUT))
        result = subprocess.run(['node', str(ROOT/'tests/professor/browser_review.cjs')],
                                cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',timeout=900)
        (OUTPUT/'browser-output.txt').write_text((result.stdout+'\n'+result.stderr).rstrip()+'\n',encoding='utf-8')
        (OUTPUT/'post-states.json').write_text(json.dumps(operations,default=str,indent=2)+'\n',encoding='utf-8')
        if result.returncode:
            raise RuntimeError('Browser review failed; see browser-output.txt')
        checked = verify(operations)
        (OUTPUT/'persistence-verification.json').write_text(json.dumps(dict(postCount=len(operations),
            verifiedMutations=checked,passCount=len(checked)),indent=2)+'\n',encoding='utf-8')
        print(json.dumps(dict(browserExit=result.returncode,posts=len(operations),verifiedDomainPosts=len(checked))))
    finally:
        if server:
            server.shutdown()
            server.server_close()
            thread.join(timeout=10)
            if thread.is_alive():
                raise RuntimeError('Review server did not stop.')
        if not fixture.doCleanups():
            raise RuntimeError('Review fixture cleanup failed.')
        if hasattr(fixture,'schema'):
            from sqlalchemy import create_engine
            owner = create_engine(os.environ['TEST_DATABASE_URL'])
            try:
                with owner.connect() as connection:
                    exists = connection.scalar(text('SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=:schema)'),
                                               dict(schema=fixture.schema))
                assert not exists
                OUTPUT.mkdir(parents=True,exist_ok=True)
                (OUTPUT/'cleanup.json').write_text(json.dumps(dict(schema=fixture.schema,absent=True,
                    serverStopped=not thread or not thread.is_alive()))+'\n',encoding='utf-8')
            finally:
                owner.dispose()


if __name__ == '__main__':
    main()
