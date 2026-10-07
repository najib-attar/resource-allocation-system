"""Regression checks for Save Only confirmation, using isolated CSV files."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main, mock
import csv
import subprocess
import sys

from web import app as web_app
from web.backend_result_adapter import BackendResultAdapter, build_committee_participant_display


class SaveOnlyConfirmationTests(TestCase):
    def setUp(self):
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
        self.write_csv("requests.csv", web_app.REQUEST_HEADERS, [
            {"requestId": "1", "requestType": "OneTime", "userId": "1", "spaceId": "301",
             "participantCount": "5", "timeData": "1-09:00-10:00",
             "title": "Existing normal request", "purpose": "Meeting"},
            {"requestId": "40", "requestType": "CommitteeMeeting", "userId": "2", "spaceId": "301",
             "participantCount": "5", "timeData": "1-10:00-11:00",
             "title": "Existing committee request", "purpose": "Committee Meeting"},
        ])
        self.write_csv("request_participants.csv", web_app.REQUEST_PARTICIPANT_HEADERS, [
            {"requestId": "40", "userId": "2", "participantRole": "Supervisor"},
            {"requestId": "40", "userId": "3", "participantRole": "Participant"},
        ])

        adapter = BackendResultAdapter(self.data, web_app.RAW_DATA_FILES)
        for patch in (
            mock.patch.object(web_app, "DATA_DIR", self.data),
            mock.patch.object(web_app, "backend_results", adapter),
            mock.patch.dict(web_app.app.config, {"TESTING": True, "PROPAGATE_EXCEPTIONS": True}),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(web_app, "run_backend_allocation", return_value={
            "status": "success", "message": "Backend explicitly requested.", "stdout": "", "stderr": "",
        })
        self.run_backend = patch.start()
        self.addCleanup(patch.stop)
        self.client = web_app.app.test_client()

    def write_csv(self, filename, headers, rows):
        with (self.data / filename).open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)

    def read_rows(self, filename):
        with (self.data / filename).open(encoding="utf-8", newline="") as file:
            return list(csv.DictReader(file))

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
            "import app; from backend_result_adapter import build_committee_participant_display; "
            "assert app.build_committee_participant_display is build_committee_participant_display",
        ], cwd=web_directory, capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    main()
