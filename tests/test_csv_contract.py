"""Exercise Python's CSV writer through the freshly built C++ executable."""

import csv
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from unittest import TestCase, main

from web.backend_executable import resolve_backend_executable
from web.result_table_schema import INPUT_HEADERS

REQUEST_HEADERS = INPUT_HEADERS["requests"].split(",")
PARTICIPANT_HEADERS = INPUT_HEADERS["request_participants"].split(",")


class CsvContractTests(TestCase):
    def setUp(self):
        self.backend = resolve_backend_executable(Path(__file__).resolve().parent.parent)
        temporary = TemporaryDirectory(prefix="python-cpp-csv-")
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name)
        self.data = self.workspace / "data"
        self.data.mkdir()
        self.write_csv("users.csv", ["userId", "name", "role"], [[2, "Professor", "Instructor"]])
        self.write_csv("spaces.csv", ["spaceId", "type", "name", "capacity", "hasProjector",
                                     "hasWhiteboard", "hasComputers", "isAvailable", "building"], [
            [101, "Classroom", "C101", 50, 1, 1, 0, 1, "Main"],
            [301, "MeetingRoom", "M301", 20, 1, 1, 0, 1, "Main"],
        ])
        self.write_csv("user_busy_slots.csv", ["userId", "day", "startTime", "endTime", "reason"], [])
        self.write_csv("request_participants.csv", PARTICIPANT_HEADERS, [])
        (self.data / "config.txt").write_text("allocation_strategy=greedy\n", encoding="utf-8")

    def write_csv(self, name, headers, rows, quoting=csv.QUOTE_MINIMAL):
        with (self.data / name).open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file, quoting=quoting)
            writer.writerow(headers)
            writer.writerows(rows)

    def read_rows(self, name, data=None):
        with ((data or self.data) / name).open(encoding="utf-8", newline="") as file:
            return list(csv.DictReader(file, strict=True))

    def request_row(self, request_id=1, request_type="OneTime"):
        return dict.fromkeys(REQUEST_HEADERS, "") | {
            "requestId": str(request_id), "requestType": request_type, "userId": "2",
            "spaceId": "301", "participantCount": "4", "timeData": "1-10-11",
            "title": "Ordinary request", "purpose": "Meeting", "canSplitAcrossRooms": "false",
        }

    def run_backend(self):
        result = subprocess.run([str(self.backend.path)], cwd=self.workspace,
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        return result

    def test_python_written_requests_and_participants_roundtrip(self):
        title = 'Advanced Algorithms, Part II "Review" \u2014 \u00c7a\u011fr\u0131'
        purpose = 'Discuss "proofs", examples and next steps'
        rows = [self.request_row(1), self.request_row(2, "Exam"), self.request_row(3, "CommitteeMeeting")]
        rows[0].update(title=title, purpose=purpose)
        rows[1].update(spaceId="101", timeData="2-10-11", courseCode='CS, "301"',
                       courseName='Algorithms, "Part II"', examType="Final")
        rows[2].update(timeData="3-10-11", title='Committee, "Review"')
        self.write_csv("requests.csv", REQUEST_HEADERS, [[row[key] for key in REQUEST_HEADERS] for row in rows])
        self.write_csv("request_participants.csv", PARTICIPANT_HEADERS, [[3, 2, 'Supervisor, "Lead"']])
        self.run_backend()
        results = {row["requestId"]: row for row in self.read_rows("request_results.csv")}
        self.assertEqual(results["1"]["title"], title)
        self.assertEqual(results["1"]["purpose"], purpose)
        self.assertEqual(results["2"]["courseCode"], rows[1]["courseCode"])
        self.assertEqual(results["2"]["courseName"], rows[1]["courseName"])
        self.assertEqual(results["3"]["committeeParticipants"], '2:Supervisor, "Lead"')
        self.assertEqual({row["status"] for row in results.values()}, {"Approved"})
        self.assertEqual({row["requestId"] for row in self.read_rows("allocations.csv")}, {"1", "2", "3"})
        self.assertEqual(self.read_rows("request_summaries.csv")[0]["purpose"], purpose)

    def test_python_quote_all_inputs_roundtrip(self):
        name = 'Professor \u00d6z, "Ada"'
        building = 'Main, "North"'
        self.write_csv("users.csv", ["userId", "name", "role"], [[2, name, "Instructor"]], csv.QUOTE_ALL)
        self.write_csv("spaces.csv", ["spaceId", "type", "name", "capacity", "hasProjector",
                                     "hasWhiteboard", "hasComputers", "isAvailable", "building"],
                       [[301, "MeetingRoom", 'Room, "301"', 20, 1, 1, 0, 1, building]], csv.QUOTE_ALL)
        self.write_csv("user_busy_slots.csv", ["userId", "day", "startTime", "endTime", "reason"],
                       [[2, 2, "10:00", "11:00", 'Lecture, "Part I"']], csv.QUOTE_ALL)
        self.write_csv("request_participants.csv", PARTICIPANT_HEADERS,
                       [[1, 2, 'Supervisor, "Lead"']], csv.QUOTE_ALL)
        row = self.request_row(1, "CommitteeMeeting")
        row["requiredBuilding"] = building
        self.write_csv("requests.csv", REQUEST_HEADERS, [list(row.values())], csv.QUOTE_ALL)
        self.run_backend()
        result = self.read_rows("request_results.csv")[0]
        self.assertEqual(result["status"], "Approved")
        self.assertEqual(result["requesterName"], name)
        self.assertEqual(result["spaceName"], 'Room, "301"')
        self.assertEqual(result["spaceBuilding"], building)
        self.assertEqual(result["committeeParticipants"], '2:Supervisor, "Lead"')

    def test_malformed_quotes_reject_request_and_preserve_following_valid_record(self):
        (self.data / "requests.csv").write_text(
            ",".join(REQUEST_HEADERS) + "\n"
            '1,OneTime,2,301,4,,,1-10-11,"Closed"oops,Meeting,,,,false\n'
            '2,OneTime,2,301,4,,,1-11-12,Ordinary request,Meeting,,,,false\n', encoding="utf-8")
        result = self.run_backend()
        self.assertIn(b"Malformed CSV", result.stderr)
        rows = self.read_rows("request_results.csv")
        self.assertEqual(rows[0]["status"], "Rejected")
        self.assertIn("Malformed CSV", rows[0]["rejectionReason"])
        self.assertEqual(rows[1]["status"], "Approved")
        self.assertEqual([row["requestId"] for row in self.read_rows("allocations.csv")], ["2"])


if __name__ == "__main__":
    main()
