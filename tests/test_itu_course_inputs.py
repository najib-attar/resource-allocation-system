"""Exercise archive normalization without relying on the private local seed files."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from web.persistence.itu_course_inputs import course_inputs


class ItuCourseInputTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.archive = Path(directory.name) / "courses.json"
        self.supplement = Path(directory.name) / "classroom_schedule.json"
        first = dict(session_index=1, weekday_iso=1, day_published="Pazartesi",
                     start_time="09:30", end_time_published="11:29", building="BBB", room="KON1",
                     building_published="BBB", room_published="KON1")
        second = dict(first, session_index=2, weekday_iso=3, day_published="Çarşamba", room=None,
                      room_published="--")
        third = dict(first, session_index=3, weekday_iso=5, day_published="Cuma", building="MDB", room="A102",
                     building_published="MDB", room_published="A102")
        section = dict(crn="12345", course_code="BLG 505", course_name="Doğal Dil İşleme", section_quota=60,
                       branch="BLG", academic_level="LU", instruction_method="Fiziksel (Yüz yüze)",
                       instructor_names=["Gülşen Eryiğit", "Outside Instructor"],
                       instructor_published="Gülşen Eryiğit, Outside Instructor",
                       published_schedule={"times": ["09:30/11:29"]}, sessions=[first, second, third])
        other = dict(section, crn="54321", instruction_method="Ek Sınav", instructor_names=[],
                     instructor_published="-", published_schedule={"times": ["-/-"]}, sessions=[])
        self.source = dict(term="2026-2027-guz", timezone="Europe/Istanbul",
            provenance={"files":{"BLG":{"url":"https://example.invalid/blg.json"}}},
            summary=dict(sections=2, unique_course_codes=1, sections_by_branch={"BLG":2}, scheduled_sections=1,
                         sections_without_published_time=1, weekly_session_rows=3,
                         sessions_with_known_building_and_room=2, sessions_without_known_room=1),
            sections=[section, other])
        self.staff = [{"id": 42, "name": "Gülşen Cebiroğlu Eryiğit"}]
        self.rooms = {"KON1": 2012, "102": 2009, "A102": 2300}

    def _load(self, supplemental=None):
        self.archive.write_text(json.dumps(self.source, ensure_ascii=False), encoding="utf-8")
        return course_inputs(self.archive, self.staff, self.rooms, supplemental)

    def test_multiple_assignments_and_sessions_keep_the_archive_evidence(self):
        loaded = self._load()
        section, untimed = loaded["sections"]
        self.assertEqual(section["instructors"], [{"name": "Gülşen Eryiğit", "user_id": 42},
                                                  {"name": "Outside Instructor", "user_id": None}])
        self.assertEqual(section["published_schedule"]["instructor"], "Gülşen Eryiğit, Outside Instructor")
        hall, unknown, external = section["sessions"]
        self.assertEqual((hall["start_minutes"], hall["end_minutes"], hall["end_time_published"]), (570, 690, "11:29"))
        self.assertEqual(hall["resource_id"], 2012)
        self.assertIsNone(unknown["resource_id"])
        self.assertEqual(unknown["room_published"], "--")
        self.assertIsNone(external["resource_id"])
        self.assertEqual((external["building"], external["room"]), ("MDB", "A102"))
        self.assertEqual(untimed["sessions"], [])
        self.assertEqual(loaded["instructorAliases"]["Gülşen Eryiğit"]["directoryName"], self.staff[0]["name"])

    def test_supplement_preserves_original_crn_rows_and_reports_disagreements(self):
        row = dict(section="12345", courseCode="BLG 505", courseTitle="Doğal Dil İşleme", buildingCode="BBB",
                   roomCode="KON1", day=1, startMinutes=570, endMinutes=690,
                   sourceUrl="https://obs.itu.edu.tr/public/DersProgram")
        conflict = dict(row, roomCode="102")
        new = dict(conflict, section="10001", courseCode="ISE 333", courseTitle="Supplemental course",
                   instructorNames=["Gülşen Cebiroğlu Eryiğit"], instructorPublished="Gülşen Cebiroğlu Eryiğit",
                   quota=30, academicLevel="LS", dayPublished="Pazartesi", startTimePublished="09:30",
                   endTimePublished="11:29")
        snapshot = dict(academicPeriod={"startDate":"2026-09-28", "endDate":"2026-12-31",
                                        "timezone":"Europe/Istanbul"}, sections=[row, conflict, new])
        self.supplement.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        loaded = self._load(self.supplement)
        self.assertEqual(loaded["supplementalCount"], 1)
        self.assertEqual(len(loaded["sections"][0]["sessions"]), 3)
        self.assertEqual(loaded["sections"][-1]["instructors"][0]["user_id"], 42)
        self.assertEqual(loaded["sections"][-1]["sessions"][0]["resource_id"], 2009)
        issue, = loaded["supplementalConflicts"]
        self.assertEqual(issue["roomCode"], "102")
        self.assertEqual(issue["archiveSessions"][0]["room"], "KON1")

    def test_rejects_inconsistent_source_totals(self):
        self.source["summary"]["weekly_session_rows"] = 200
        with self.assertRaisesRegex(ValueError, "do not reconcile"):
            self._load()
