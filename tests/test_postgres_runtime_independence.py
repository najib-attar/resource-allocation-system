"""Cold-start and operational workflows need PostgreSQL, never runtime CSV files."""

import json
import os
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import mock

from sqlalchemy.engine import make_url

from postgres_fixtures import PostgresTestCase, ROOT
from postgres_web_fixtures import form, seed_web_database
from runtime_file_guard import forbid_runtime_files
from web import app as web_app
from web.allocation_workflow import execute_allocation
from web.engine_gateway import EngineGateway
from web.persistence.repository import Repository


class PostgresRuntimeIndependenceTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        seed_web_database(self.database)
        self.repository = Repository(self.database)
        self.client = self.configure_web()

    def test_save_run_strategy_and_all_views_work_with_runtime_file_io_forbidden(self):
        with forbid_runtime_files():
            with mock.patch("web.engine_gateway.subprocess.run") as engine:
                saved = self.client.post("/add-request", data=form("Save only"))
                self.assertEqual(saved.status_code, 302)
                engine.assert_not_called()
            self.assertEqual(self.client.get(saved.location).status_code, 200)
            self.assertIsNone(self.repository.read_view()[1])
            self.assertEqual(self.client.post("/set-strategy", data={"strategy": "priority"}).status_code, 302)
            data = form("Submit and run", "save_run") | {"day": "2"}
            submitted = self.client.post("/add-request", data=data)
            self.assertEqual(submitted.status_code, 302)
            self.assertIn("run_status=success", submitted.location)
            self.assertEqual(self.client.get(submitted.location).status_code, 200)
            self.assertEqual(self.repository.read_view()[1]["result"]["strategy"], "priority")
            routes = ["/", "/users", "/spaces", "/requests", "/request/1", "/request/2", "/request/3",
                      "/request/999999", "/allocation-summary", "/schedules?type=user&id=2",
                      "/schedules?type=space&id=301", "/add-request?type=CommitteeMeeting"]
            routes += ["/raw-data?file=" + item["filename"] for item in web_app.RAW_DATA_FILES]
            routes += ["/raw-data?file=not_allowed.csv", "/raw-data?file=../../users.csv"]
            for route in routes:
                with self.subTest(route=route):
                    self.assertEqual(self.client.get(route).status_code, 200)

    def test_new_application_process_reloads_database_results_from_an_empty_working_directory(self):
        result = execute_allocation(self.repository, EngineGateway(ROOT))
        script = """
import json, sys
from runtime_file_guard import forbid_runtime_files
with forbid_runtime_files():
    from web import app as web_app
    web_app.app.config['TESTING'] = True
    from auth_fixtures import authorized_client
    client = authorized_client(web_app.app)
    for route in ('/', '/request/1', '/allocation-summary', '/schedules?type=space&id=301'):
        assert client.get(route).status_code == 200, route
    response = client.post('/add-request', data={'requestType': 'OneTime', 'userId': '2', 'spaceId': '301',
        'participantCount': '4', 'day': '3', 'startTime': '10:00', 'endTime': '11:00', 'title': 'Cold start save',
        'purpose': 'Meeting', 'requiredFeature': 'None', 'requiredBuilding': 'Main', 'submitAction': 'save'})
    assert response.status_code == 302
    assert client.get(response.location).status_code == 200
    assert not {'web.persistence.importer', 'persistence.importer'} & set(sys.modules), 'Operational code loaded CSV import machinery'
    print(json.dumps(web_app.get_repository().read_view()[1]['result']))
"""
        environment = os.environ | {"DATABASE_URL": self.url,
                                    "PYTHONPATH": os.pathsep.join((str(ROOT), str(ROOT / "tests"), str(ROOT / "web")))}
        for import_statement in ("from web import app as web_app", "import app as web_app"):
            with self.subTest(import_statement=import_statement), TemporaryDirectory(prefix="postgres-cold-start-") as directory:
                completed = subprocess.run([sys.executable, "-c", script.replace("from web import app as web_app", import_statement)],
                                           cwd=directory, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(json.loads(completed.stdout), result)
        self.assertEqual(len(self.repository.snapshot()["requests"]), 3)

    def test_unreachable_postgresql_returns_503_without_csv_fallback(self):
        # Own an unlistening port rather than stopping any existing PostgreSQL server.
        with socket.socket() as unused_port:
            unused_port.bind(("127.0.0.1", 0))
            url = make_url(self.url).set(host="127.0.0.1", port=unused_port.getsockname()[1])
            with mock.patch.dict(web_app.app.config, {"DATABASE_URL": url.render_as_string(hide_password=False)}), \
                    forbid_runtime_files(), self.assertLogs(web_app.app.logger):
                response = self.client.get("/")
            cached = web_app.app.extensions.pop("allocation_database", None)
            if cached:
                cached[1].dispose()
        self.assertEqual(response.status_code, 503)
        self.assertIn("Database operation failed", response.get_data(as_text=True))
        self.assertEqual(len(self.repository.snapshot()["requests"]), 1)
