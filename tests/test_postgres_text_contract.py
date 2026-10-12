"""PostgreSQL/Python/C++ preserve user text without CSV execution dependencies."""

from pathlib import Path
from unittest import mock
import os

from postgres_fixtures import PostgresTestCase
from postgres_web_fixtures import seed_web_database
from runtime_file_guard import forbid_runtime_files
from web import app as web_app
from web.backend_executable import resolve_backend_executable
from web.database_result_adapter import DatabaseResultAdapter
from web.persistence.repository import Repository


class PostgresTextContractTests(PostgresTestCase):
    def test_flask_submit_and_run_preserves_comma_quote_and_unicode_title(self):
        self.backend = resolve_backend_executable(Path(__file__).resolve().parent.parent)
        seed_web_database(self.database, with_request=False)
        repository = Repository(self.database)
        title = 'Advanced Algorithms, "Part II" \u00c7a\u011fr\u0131'
        client = self.configure_web()
        with forbid_runtime_files(), mock.patch.dict(os.environ, {"RESOURCE_ALLOCATION_BACKEND": str(self.backend.path)}):
            response = client.post("/add-request", data={
                "requestType": "OneTime", "userId": "2", "spaceId": "301", "participantCount": "4",
                "day": "1", "startTime": "10:00", "endTime": "11:00", "title": title,
                "purpose": "Meeting", "requiredFeature": "None", "requiredBuilding": "Main",
                "submitAction": "save_run",
            })
            self.assertEqual(response.status_code, 302)
            self.assertEqual(client.get(response.location).status_code, 200)
            self.assertIsNotNone(repository.read_view()[1])
            row = DatabaseResultAdapter(repository, web_app.RAW_DATA_FILES).get_table("request_results")["rows"][0]
            self.assertEqual(row["status"], "Approved")
            self.assertEqual(row["title"], title)
