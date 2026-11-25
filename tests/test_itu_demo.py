"""ITU demo isolation and deterministic enrollment without requiring the local roster."""

from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock
import json

from scripts.setup_local_demo import prepare_settings
from web.persistence.itu_demo import DATA, DEPARTMENTS, FACULTY, itu_inputs
from web.persistence.itu_resources import catalog_manifest, resource_spaces


class ItuDemoTests(TestCase):
    def test_catalog_matches_only_explicit_bbb_codes_and_same_term_supplement(self):
        term = {"startDate": "2026-09-28", "endDate": "2026-12-31"}
        meeting = dict(section="12345", courseCode="TEST", courseTitle="Fixture",
                       day=1, startMinutes=600, endMinutes=660, buildingCode="BBB",
                       roomCode="KON1", sourceUrl="https://example.invalid/obs")
        schedule = {"academicPeriod": term, "sections": [meeting, dict(meeting, buildingCode="OTHER"),
                                                        dict(meeting, roomCode="Z-23")]}
        with TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "resources.json").write_bytes((DATA / "resources.json").read_bytes())
            additional = directory / "room_schedule.json"
            more = dict(meeting, section="12346", roomCode="Z-17", validUntil="2026-12-19")
            additional.write_text(json.dumps({"academicPeriod": term, "sections": [meeting, more]}), encoding="utf-8")
            catalog = catalog_manifest(directory, schedule)
            by_id = {space["id"]: space for space in resource_spaces(catalog)}
            self.assertEqual([by_id[row["resourceId"]]["name"] for row in catalog["weeklyOccupancy"]],
                             ["BBB Konferans Salonu", "BBB Z-17"])
            self.assertEqual(catalog["weeklyOccupancy"][-1]["validUntil"], "2026-12-19")
            self.assertEqual(len(catalog["unmappedMeetings"]), 2)
            additional.write_text(json.dumps({"academicPeriod": {}, "sections": []}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "different academic period"):
                catalog_manifest(directory, schedule)

    def test_dataset_selection_preserves_existing_profile_and_fixes_itu_dates(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            old = root / "fictional" / "settings.json"
            old.parent.mkdir()
            old_settings = prepare_settings(old)
            with self.assertRaisesRegex(ValueError, "different dataset"):
                prepare_settings(old, dataset="itu")
            self.assertEqual(prepare_settings(old), old_settings)

            target = root / "itu" / "settings.json"
            target.parent.mkdir()
            calendar = {"academicPeriod": {"startDate": "2026-09-28", "endDate": "2026-12-31"}}
            with mock.patch("scripts.setup_local_demo.load_itu_schedule", return_value=calendar):
                with self.assertRaisesRegex(ValueError, "seed 42"):
                    prepare_settings(target, dataset="itu", seed=41)
                settings = prepare_settings(target, dataset="itu")
            self.assertEqual((settings["databaseName"], settings["seed"]), ("ras_itu_demo", 42))
            self.assertEqual((settings["academicStart"], settings["academicEnd"]), ("2026-09-28", "2026-12-31"))
            self.assertEqual(prepare_settings(target), settings)

    def test_deterministic_roster_mapping_and_whole_sections_with_no_duplicate_times(self):
        with TemporaryDirectory() as temp:
            directory = Path(temp)
            people = [dict(name=f"Fixture {department} {i}", title="Fixture title", department=department,
                           category="research_assistant" if i == 0 else "academic",
                           verification="officially_listed", sourceKeys=["fixture"], responsibilities=[])
                      for department, count in {"BLG": 61, "YZV": 30, "SGM": 8}.items()
                      for i in range(count)]
            people.extend(dict(name=f"Fixture {kind} {i}", title="Fixture title", department=None,
                               category=kind, verification="provisional", sourceKeys=["fixture"], responsibilities=[])
                          for kind, count in {"visiting": 2, "affiliated_coordinator": 2, "administrative": 15}.items()
                          for i in range(count))
            source_url = "https://example.invalid/test-itu-data"
            roster = dict(people=people, rosterDate="2026-11-25", sources={"fixture": source_url}, discrepancies=[])
            section = dict(department="BLG", courseCode="BLG101", courseTitle="Test course", section="12345",
                           instructorName=people[1]["name"], instructorNames=[people[1]["name"]], capacity=35,
                           startMinutes=540, endMinutes=600, sourceUrl=source_url, recommendedYears={"BLG": [1]})
            schedule = dict(academicPeriod={}, departments={d: {"availableYears": [1, 2, 3] if d == "SGM"
                            else [1, 2, 3, 4]} for d in DEPARTMENTS}, sections=[dict(section, day=d) for d in (1, 3)])
            (directory / "roster.json").write_text(json.dumps(roster), encoding="utf-8")
            (directory / "schedule.json").write_text(json.dumps(schedule), encoding="utf-8")
            (directory / "resources.json").write_bytes((DATA / "resources.json").read_bytes())
            result = itu_inputs(directory, 42)
            self.assertEqual(itu_inputs(directory, 42), result)
            snapshot, units, accounts, _, manifest = result
        self.assertEqual(len(snapshot["users"]), 239)
        self.assertEqual(snapshot["requests"], [])
        self.assertEqual(manifest["instructorSlots"], 2)
        self.assertEqual(Counter(s["department"] for s in manifest["students"]),
                         {"BLG": 100, "YZV": 10, "SGM": 10})
        self.assertEqual({s["year"] for s in manifest["students"] if s["department"] == "SGM"}, {1, 2, 3})
        self.assertTrue(all(units[name]["parent"] == FACULTY for name in DEPARTMENTS.values()))
        self.assertEqual({a["role"] for a in accounts}, {"Student", "Instructor", "TeachingAssistant", "Administrator"})
        self.assertTrue(all(u["email"].endswith("@example.invalid") for u in snapshot["users"] if u["email"]))
        enrolled = [student["schedule"] for student in manifest["students"]
                    if any("section" in row for row in student["schedule"])]
        self.assertEqual(len(enrolled), 25)
        for meetings in enrolled:
            self.assertEqual([(row["section"], row["slot"]["day"]) for row in meetings],
                             [("12345", 1), ("12345", 3)])
