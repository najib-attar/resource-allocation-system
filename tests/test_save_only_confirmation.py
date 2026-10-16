"""Save Only regressions against isolated PostgreSQL schemas; CSV is import only."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import main, mock
import csv
import subprocess
import sys

from web.result_table_schema import INPUT_HEADERS
from web import app as web_app
from web.backend_result_adapter import build_committee_participant_display
from web.database_result_adapter import DatabaseResultAdapter
from web.persistence.importer import import_csv
from web.persistence.repository import Repository
from postgres_fixtures import PostgresTestCase


class SaveOnlyConfirmationTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        temporary = TemporaryDirectory(prefix="save-only-confirmation-")
        self.addCleanup(temporary.cleanup)
        self.data = Path(temporary.name)
        self.write_csv("users.csv", ["userId", "name", "role"], [
            {"userId": "1", "name": "Student Requester", "role": "Student"},
            {"userId": "2", "name": "Professor Ada", "role": "Instructor"},
            {"userId": "3", "name": "Professor Grace", "role": "Instructor"},
        ])
        self.write_csv("spaces.csv", ["spaceId", "type", "name", "capacity", "building"], [
            {"spaceId": "301", "type": "MeetingRoom", "name": "M301",
             "capacity": "20", "building": "Main"},
        ])
        self.write_csv("requests.csv", INPUT_HEADERS["requests"].split(","), [
            {"requestId": "1", "requestType": "OneTime", "userId": "1", "spaceId": "301",
             "participantCount": "5", "timeData": "1-09:00-10:00",
             "title": "Existing normal request", "purpose": "Meeting"},
            {"requestId": "40", "requestType": "CommitteeMeeting", "userId": "2", "spaceId": "301",
             "participantCount": "5", "timeData": "1-10:00-11:00",
             "title": "Existing committee request", "purpose": "Committee Meeting"},
        ])
        self.write_csv("request_participants.csv", INPUT_HEADERS["request_participants"].split(","), [
            {"requestId": "40", "userId": "2", "participantRole": "Supervisor"},
            {"requestId": "40", "userId": "3", "participantRole": "Participant"},
        ])

        import_csv(self.database, self.data)
        self.repository = Repository(self.database)
        for patch in (
            mock.patch.object(web_app, "get_repository", return_value=self.repository),
            mock.patch.dict(web_app.app.config, {"TESTING": True, "PROPAGATE_EXCEPTIONS": True}),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(web_app, "run_backend_allocation", return_value={
            "status": "success", "message": "Backend explicitly requested.",
        })
        self.run_backend = patch.start()
        self.addCleanup(patch.stop)
        self.client = self.configure_web()

    def write_csv(self, filename, headers, rows):
        with (self.data / filename).open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)

    def read_rows(self, filename):
        return DatabaseResultAdapter(self.repository, web_app.RAW_DATA_FILES).get_table(filename.removesuffix(".csv"))["rows"]

    def save_form(self, request_type="OneTime"):
        return {
            "requestType": request_type, "userId": "1", "spaceId": "301",
            "participantCount": "5", "day": "1", "startTime": "10:00", "endTime": "11:00",
            "title": "Saved normal request", "purpose": "Meeting",
            "requiredFeature": "None", "requiredBuilding": "Main", "submitAction": "save",
        }

    def test_normal_save_only_writes_one_request_and_renders_confirmation(self):
        response = self.client.post("/add-request", data=self.save_form())
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/request-added/41"))
        rows = self.read_rows("requests.csv")
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[-1]["requestId"], "41")
        self.assertEqual(rows[-1]["requestType"], "OneTime")
        self.assertEqual(len(self.read_rows("request_participants.csv")), 2)

        confirmation = self.client.get(response.location)
        self.assertEqual(confirmation.status_code, 200)
        page = confirmation.get_data(as_text=True)
        for text in ("Request 41 was added successfully", "Saved normal request", "Student Requester",
                     "Monday 10:00-11:00", "M301", "pending until allocation is run"):
            self.assertIn(text, page)
        self.assertNotIn("Required Participants", page)
        self.assertIn('/request/41', page)
        self.run_backend.assert_not_called()
        self.assertFalse((self.data / "request_results.csv").exists())

    def test_committee_save_only_preserves_participants_and_renders_confirmation(self):
        form = self.save_form("CommitteeMeeting")
        form.update({
            "userId": "2", "title": "Saved committee request", "purpose": "Committee Meeting",
            "requiredParticipantIds": ["2", "3"], "participantRole_2": "Supervisor", "participantRole_3": "",
        })
        response = self.client.post("/add-request", data=form)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/request-added/41"))
        rows = self.read_rows("requests.csv")
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[-1]["requestType"], "CommitteeMeeting")
        participants = [row for row in self.read_rows("request_participants.csv") if row["requestId"] == "41"]
        self.assertEqual(participants, [
            {"requestId": "41", "userId": "2", "participantRole": "Supervisor"},
            {"requestId": "41", "userId": "3", "participantRole": "Participant"},
        ])

        confirmation = self.client.get(response.location)
        self.assertEqual(confirmation.status_code, 200)
        page = confirmation.get_data(as_text=True)
        for text in ("Saved committee request", "Professor Ada", "Professor Grace", "Supervisor",
                     "Participant", "Required Participants", "Monday 10:00-11:00", "M301"):
            self.assertIn(text, page)
        self.run_backend.assert_not_called()
        self.assertFalse((self.data / "allocations.csv").exists())

    def test_exam_save_only_uses_shared_validation_and_preserves_course_fields(self):
        form = self.save_form("Exam")
        form.update({"userId": "2", "title": "Saved exam", "purpose": "Exam",
                     "courseCode": "CS401", "courseName": "Algorithms, Part II",
                     "examType": "Final", "canSplitAcrossRooms": "true"})
        response = self.client.post("/add-request", data=form)
        self.assertEqual(response.status_code, 302)
        saved = self.read_rows("requests.csv")[-1]
        for key in ("requestType", "courseCode", "courseName", "examType", "canSplitAcrossRooms"):
            self.assertEqual(saved[key], form[key])
        self.assertEqual(saved["timeData"], "1-10:00-11:00")
        self.assertEqual(self.client.get(response.location).status_code, 200)
        self.assertEqual(self.client.get("/request/41").status_code, 200)
        self.run_backend.assert_not_called()

    def test_recurring_save_preserves_ordered_occurrences_and_runs_through_real_engine(self):
        from web.allocation_workflow import execute_allocation
        from web.engine_gateway import EngineGateway
        from postgres_fixtures import ROOT
        form = self.save_form("Recurring")
        form.update(title='Seminar, "Part II" \u00d6', timeData="2-13:15-14:00;4-09:00-10:00")
        response = self.client.post("/add-request", data=form)
        self.assertTrue(response.location.endswith("/request-added/41"))
        saved = self.repository.snapshot()["requests"][-1]
        self.assertEqual(saved["title"], form["title"])
        self.assertEqual(saved["slots"], [{"day": 2, "startMinutes": 795, "endMinutes": 840},
                                           {"day": 4, "startMinutes": 540, "endMinutes": 600}])
        self.run_backend.assert_not_called()
        result = execute_allocation(self.repository, EngineGateway(ROOT))
        decision = next(item for item in result["requestResults"] if item["requestId"] == 41)
        self.assertEqual(decision["status"], "Approved")
        self.assertEqual(decision["allocationCount"], 2)
        self.assertEqual(self.client.get("/request/41").status_code, 200)

    def test_invalid_normal_and_exam_forms_do_not_persist_or_execute(self):
        before = {name: self.read_rows(name) for name in ("requests.csv", "request_participants.csv")}
        for request_type in ("OneTime", "Exam"):
            with self.subTest(request_type=request_type):
                form = self.save_form(request_type)
                form["endTime"] = form["startTime"]
                response = self.client.post("/add-request", data=form)
                self.assertEqual(response.status_code, 200)
                page = response.get_data(as_text=True)
                self.assertIn("Start time must be earlier than end time.", page)
                if request_type == "Exam":
                    self.assertIn("Course code is required for exam requests.", page)
                self.assertEqual(before, {name: self.read_rows(name) for name in before})
        self.run_backend.assert_not_called()

    def test_legacy_result_urls_redirect_to_working_raw_data_views(self):
        for route, filename in (("/allocations", "allocations.csv"), ("/results", "request_results.csv")):
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.location, f"/raw-data?file={filename}")
                self.assertEqual(self.client.get(response.location).status_code, 200)

    def test_existing_normal_confirmation_and_detail_routes_render(self):
        for route in ("/request-added/1", "/request/1"):
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200)
                self.assertIn("Existing normal request", response.get_data(as_text=True))
        self.run_backend.assert_not_called()

    def test_existing_committee_confirmation_and_detail_routes_render(self):
        for route in ("/request-added/40", "/request/40"):
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200)
                page = response.get_data(as_text=True)
                for text in ("Existing committee request", "Professor Ada", "Professor Grace", "Supervisor"):
                    self.assertIn(text, page)
        self.run_backend.assert_not_called()

    def test_confirmation_run_button_keeps_explicit_run_and_detail_navigation(self):
        confirmation = self.client.get("/request-added/40")
        self.assertIn('action="/run-allocation-now/40"', confirmation.get_data(as_text=True))
        self.run_backend.assert_not_called()
        response = self.client.post("/run-allocation-now/40")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.startswith("/request/40?"))
        self.run_backend.assert_called_once_with()
        self.assertEqual(self.client.get(response.location).status_code, 200)

    def test_helper_is_available_for_package_and_standalone_imports(self):
        self.assertIs(web_app.build_committee_participant_display, build_committee_participant_display)
        web_directory = Path(__file__).resolve().parent.parent / "web"
        completed = subprocess.run([
            sys.executable, "-B", "-c",
            "import app; from web.backend_result_adapter import build_committee_participant_display; "
            "assert app.build_committee_participant_display is build_committee_participant_display",
        ], cwd=web_directory, capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    main()
