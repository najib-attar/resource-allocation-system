"""Real-browser logout race, using only a disposable PostgreSQL fixture."""

import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Event, Thread

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tests'), str(ROOT)]

from flask import request
from sqlalchemy import func, select
from werkzeug.serving import make_server

from auth_fixtures import TEST_SECRET
from test_professor_services import ProfessorFixture
from web import app as web_app
from web.account_service import AccountService
from web.persistence.models import CalendarBlock, LoggedOutSession, LoginAccount, Role, User


def main():
    if not os.environ.get('TEST_DATABASE_URL'):
        raise RuntimeError('An isolated TEST_DATABASE_URL is required.')
    output = Path(os.environ.get('LOGOUT_BROWSER_OUTPUT', ROOT / 'build/logout-browser'))
    output.mkdir(parents=True, exist_ok=True)
    fixture, server, thread = ProfessorFixture(), None, None
    entered, release = Event(), Event()

    def delay(response):
        if request.path == '/notifications/feed' and request.args.get('logoutRace') == 'held':
            entered.set()
            if not release.wait(30):
                raise RuntimeError('Delayed response was not released.')
        if request.endpoint == 'static':
            action = request.args.get('logoutRace')
            if action == 'reset':
                entered.clear()
                release.clear()
            elif action == 'release':
                release.set()
            response.headers['X-Logout-Race-Held'] = '1' if entered.is_set() else '0'
        return response

    try:
        fixture.setUp()
        with fixture.database.transaction() as session:
            role = session.scalar(select(Role.id).where(Role.name == 'TeachingAssistant'))
            session.add(User(id=9, source_order=9, name='Synthetic logout TA', primary_role_id=role))
        users = {1: 'Student', 2: 'Instructor', 9: 'TeachingAssistant', 7: 'Staff', 6: 'Administrator'}
        password = 'Synthetic-browser-logout-password'
        with fixture.database.transaction(read_only=True) as session:
            existing = set(session.scalars(select(LoginAccount.user_id)))
        for actor in users:
            AccountService(fixture.database).provision(actor, 'logout-browser-' + str(actor), password,
                                                       administrator=actor == 6, reset=actor in existing)
        with fixture.database.transaction(read_only=True) as session:
            versions = {a.user_id: a.session_version for a in session.scalars(select(LoginAccount))}
        web_app.app.config.update(SECRET_KEY=TEST_SECRET, TESTING=False, PROPAGATE_EXCEPTIONS=False)
        web_app.app.after_request_funcs[None].append(delay)
        fixture.addCleanup(web_app.app.after_request_funcs[None].remove, delay)
        server = make_server('127.0.0.1', 0, web_app.app, threaded=True)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        info = output / 'fixture.json'
        info.write_text(json.dumps(dict(url=f'http://127.0.0.1:{server.server_port}', users=users,
                                       password=password)), encoding='utf-8')
        env = dict(os.environ, LOGOUT_BROWSER_INFO=str(info), LOGOUT_BROWSER_OUTPUT=str(output))
        process = subprocess.run(['node', str(ROOT / 'tests/logout_browser.cjs')], cwd=ROOT, env=env,
                                 capture_output=True, text=True, encoding='utf-8', timeout=240)
        (output / 'browser-output.txt').write_text(process.stdout + '\n' + process.stderr, encoding='utf-8')
        if process.returncode:
            raise RuntimeError('Logout browser regression failed; inspect browser-output.txt.')
        with fixture.database.transaction(read_only=True) as session:
            denials = list(session.scalars(select(LoggedOutSession)))
            assert {row.user_id for row in denials} == set(users) and len(denials) == len(users)
            assert {a.user_id: a.session_version for a in session.scalars(select(LoginAccount))} == versions
            assert session.scalar(select(func.count()).select_from(CalendarBlock)) == 0
        (output / 'persistence-verification.json').write_text(json.dumps(dict(
            logoutDenialsPersisted=len(denials), allFiveActorsVerified=True, accountVersionsUnchanged=True,
            rejectedMutationsPersisted=0, responseTimingOnly=True), indent=2) + '\n', encoding='utf-8')
        print(f'PASS: five-role real-browser race and {len(denials)} committed session denials.')
    finally:
        release.set()
        if server:
            server.shutdown()
            server.server_close()
            thread.join(timeout=10)
        if not fixture.doCleanups():
            raise RuntimeError('Fixture cleanup failed.')
        if thread and thread.is_alive():
            raise RuntimeError('Browser server did not stop.')
        (output / 'cleanup.json').write_text(json.dumps(dict(schema=getattr(fixture, 'schema', None),
            fixtureCleaned=True, serverStopped=True)) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
