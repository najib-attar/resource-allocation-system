"""Serve the real application against an owned, fictional PostgreSQL test schema.

Requires TEST_DATABASE_URL and the regular backend build. Never seeds or resets an
application schema. Stop with Ctrl+C to dispose connections and remove this schema.
"""

import json
import os
from pathlib import Path
import sys
from datetime import timedelta

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

from sqlalchemy import select
from werkzeug.serving import make_server

from test_room_requests import RoomFixture, START
from web import app as web_app
from web.account_service import AccountService
from web.persistence.models import LoginAccount


def main():
    if not os.environ.get("TEST_DATABASE_URL"):
        raise SystemExit("Set TEST_DATABASE_URL to a disposable PostgreSQL database.")
    fixture = RoomFixture()
    try:
        fixture.setUp()
        appointments = fixture.service
        confirmed = appointments.submit(1, [2], [], "Fictional capstone consultation", 60, START, fixture.faculty)
        appointments.decide(confirmed, 2, 1, True)
        pending = appointments.submit(1, [2, 3], [], "Fictional research proposal review", 60,
                                      START + timedelta(hours=2), fixture.faculty)
        appointments.decide(pending, 2, 1, True)
        invitation = appointments.submit(4, [3], [1], "Fictional peer project invitation", 60,
                                         START + timedelta(hours=4), fixture.faculty)
        appointments.decide(invitation, 3, 1, True)
        appointments.submit(4, [3], [], "PRIVATE unrelated student meeting", 60,
                            START + timedelta(hours=5), fixture.faculty)
        room = fixture.request_room(start=START + timedelta(days=1), purpose="Fictional design team workspace")
        fixture.rooms.decide(room, 7, 1, True)
        fixture.service.block(1, START + timedelta(days=2), START + timedelta(days=2, hours=1),
                              "Fictional independent study")
        accounts = AccountService(fixture.database)
        password = "Fictional-UI01-review-password"
        users = {1: "ui01-student", 5: "ui01-empty", 2: "ui01-professor", 6: "ui01-admin", 7: "ui01-staff"}
        with fixture.database.transaction(read_only=True) as session:
            existing = set(session.scalars(select(LoginAccount.user_id)))
        for actor, username in users.items():
            accounts.provision(actor, username, password, administrator=actor == 6, reset=actor in existing)
        web_app.app.config.update(DATABASE_URL=fixture.url, SECRET_KEY="fictional-ui01-local-review-session-key-2030",
                                  TESTING=False, PROPAGATE_EXCEPTIONS=True)
        assert web_app.app.test_client().get('/login').status_code == 200, 'Preview login must be available.'
        port = int(os.environ.get('UI01_PORT', '5051'))
        url = f'http://127.0.0.1:{port}'
        output = ROOT / "build" / "ui01" / "preview.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"url": url, "password": password,
                                      "users": users, "week": "2030-01-07", "schema": fixture.schema}, indent=2))
        print('Fictional review application: ' + url, flush=True)
        print("Accounts and selected calendar week: build/ui01/preview.json", flush=True)
        with make_server("127.0.0.1", port, web_app.app, threaded=True) as server:
            server.serve_forever()
    finally:
        fixture.dispose_web_database()
        fixture.doCleanups()


if __name__ == "__main__":
    main()
