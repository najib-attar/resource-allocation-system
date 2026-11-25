"""Validate the published ITU course archive and reconcile it with the local directory."""

from collections import Counter, defaultdict
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import parse_qs, urlparse

from .validation import validate_slot


ACADEMIC_TERM = "2026-2027-guz"
TIMEZONE = "Europe/Istanbul"
TERM_START = date(2026, 9, 28)
TERM_END = date(2026, 12, 31)
ALIASES = {"Gülşen Eryiğit": ("Gülşen Cebiroğlu Eryiğit", "https://akademi.itu.edu.tr/gulsenc/")}
PUBLISHED_DAYS = ("Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar")


def _name_key(name):
    folded = unicodedata.normalize("NFC", name).casefold().replace("\u0307", "")
    return " ".join(folded.split())


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Expected published text for {label}.")
    return value


def _minutes(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        raise ValueError("A published teaching time must be in HH:MM format.")
    hour, minute = map(int, value.split(":"))
    return hour * 60 + minute


def _quota(value):
    if value is not None and (type(value) is not int or not 0 <= value <= 2147483647):
        raise ValueError("A published section quota must be a nonnegative integer.")
    return value


def _session(rooms, ordinal, day, start, end, building, room, *, day_published=None, start_time_published=None,
             end_time_published=None, building_published=None, room_published=None, valid_until=None):
    validate_slot(dict(day=day, startMinutes=start, endMinutes=end))
    return dict(ordinal=ordinal, day=day, start_minutes=start, end_minutes=end,
                day_published=day_published, start_time_published=start_time_published,
                end_time_published=end_time_published, building=building, room=room,
                building_published=building_published, room_published=room_published,
                resource_id=rooms.get(room) if building == "BBB" else None, valid_until=valid_until)


def _meeting_key(session):
    return tuple(session[key] for key in ("day", "start_minutes", "end_minutes", "building", "room"))


def _supplement(path, sections, rooms, instructors):
    conflicts, by_crn, seen = [], {}, set()
    if not path or not Path(path).is_file():
        return conflicts, [], {}
    snapshot = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    period = snapshot["academicPeriod"]
    if (period["startDate"], period["endDate"], period["timezone"]) != (
            TERM_START.isoformat(), TERM_END.isoformat(), TIMEZONE):
        raise ValueError("The supplemental OBS room schedule is from a different term.")

    archived = {item["crn"]: item for item in sections}
    for row in snapshot["sections"]:
        building, room = row["buildingCode"], row["roomCode"]
        if building != "BBB" or not room:
            continue
        crn = _text(row["section"], "supplemental CRN")
        if not re.fullmatch(r"[0-9]+", crn):
            raise ValueError(f"Invalid supplemental CRN {crn}.")
        marker = row.get("validUntil")
        if marker and not TERM_START <= date.fromisoformat(marker) <= TERM_END:
            raise ValueError("A supplemental teaching session ends outside the academic term.")
        session = _session(rooms, 0, row["day"], row["startMinutes"], row["endMinutes"], building, room,
            day_published=row.get("dayPublished"), start_time_published=row.get("startTimePublished"),
            end_time_published=row.get("endTimePublished"), building_published=building,
            room_published=room, valid_until=marker)
        meeting = _meeting_key(session)
        if (crn, meeting) in seen:
            continue
        seen.add((crn, meeting))
        if crn in archived:
            original = archived[crn]
            if meeting not in {_meeting_key(item) for item in original["sessions"]}:
                conflicts.append(dict(crn=crn, courseCode=row["courseCode"], day=row["day"],
                    startMinutes=row["startMinutes"], endMinutes=row["endMinutes"], buildingCode=building,
                    roomCode=room, sourceUrl=row["sourceUrl"], archiveSourceUrl=original["source_url"],
                    archiveSessions=original["sessions"]))
            continue
        course_code = _text(row["courseCode"], "supplemental course code")
        if crn not in by_crn:
            query = parse_qs(urlparse(row["sourceUrl"]).query)
            academic_level = row.get("academicLevel") or query.get("programSeviyeTipiAnahtari", [""])[0]
            by_crn[crn] = dict(crn=crn, course_code=course_code, course_name=row["courseTitle"],
                branch=course_code.split()[0], academic_level=academic_level, sessions=[],
                instruction_method=row.get("instructionMethod", ""), quota=_quota(row.get("quota")),
                source_url=row["sourceUrl"], source_kind="public_obs",
                published_schedule={"instructor": row.get("instructorPublished", "")},
                instructors=instructors(row.get("instructorNames", [])))
        section = by_crn[crn]
        if section["course_code"] != course_code:
            raise ValueError(f"Conflicting supplemental course codes for CRN {crn}.")
        section["sessions"].append(dict(session, ordinal=len(section["sessions"]) + 1))
    return conflicts, list(by_crn.values()), snapshot.get("sources", {})


def course_inputs(path, staff, rooms, supplemental_path=None):
    """Return primary archive sections plus separate OBS CRNs, with no inferred bookings."""
    payload = Path(path).read_bytes()
    source = json.loads(payload.decode("utf-8-sig"))
    if (source["term"], source["timezone"]) != (ACADEMIC_TERM, TIMEZONE):
        raise ValueError("The course seed must be the 2026–2027 Fall ITU archive.")

    candidates = defaultdict(set)
    for identity in staff:
        candidates[_name_key(identity["name"])].add(identity["id"])
    aliases = {_name_key(name): (canonical, url) for name, (canonical, url) in ALIASES.items()}
    alias_matches = {}

    def instructors(names):
        results = []
        seen = set()
        for name in names:
            key = _name_key(_text(name, "instructor name"))
            matching = candidates.get(key, set())
            if not matching and key in aliases:
                canonical, source_url = aliases[key]
                matching = candidates.get(_name_key(canonical), set())
                if len(matching) == 1:
                    alias_matches[name] = {"directoryName": canonical, "sourceUrl": source_url}
            user_id = next(iter(matching)) if len(matching) == 1 else None
            dedupe = (user_id, None) if user_id is not None else (None, key)
            if dedupe not in seen:
                results.append(dict(name=name, user_id=user_id))
                seen.add(dedupe)
        return results

    provenance = source["provenance"]
    sections, crns = [], set()
    branches = Counter()
    scheduled = weekly = known_rooms = 0
    for row in source["sections"]:
        crn = _text(row["crn"], "CRN")
        if not re.fullmatch(r"[0-9]+", crn) or crn in crns:
            raise ValueError(f"Invalid or duplicate archive CRN {crn}.")
        crns.add(crn)
        branch = _text(row["branch"], "course branch")
        branches[branch] += 1
        sessions = []
        for ordinal, published in enumerate(row["sessions"], 1):
            day = published["weekday_iso"]
            if (published["session_index"] != ordinal or type(day) is not int or not 1 <= day <= 7
                    or PUBLISHED_DAYS[day - 1] != published["day_published"]):
                raise ValueError(f"Invalid session sequence or weekday for CRN {crn}.")
            start = _minutes(published["start_time"])
            # Published end minutes are inclusive. Preserve the raw value and use [start, end) for scheduling.
            end = _minutes(published["end_time_published"]) + 1
            session = _session(rooms, ordinal, day, start, end, published["building"], published["room"],
                day_published=published["day_published"], start_time_published=published["start_time"],
                end_time_published=published["end_time_published"], building_published=published["building_published"],
                room_published=published["room_published"])
            known_rooms += bool(session["building"] and session["room"])
            sessions.append(session)
        scheduled += bool(sessions)
        weekly += len(sessions)
        sections.append(dict(crn=crn, course_code=_text(row["course_code"], "course code"),
            course_name=_text(row["course_name"], "course name"), branch=branch,
            academic_level=row["academic_level"], instruction_method=row["instruction_method"],
            quota=_quota(row["section_quota"]), source_url=provenance["files"][branch]["url"], source_kind="archive",
            published_schedule=dict(row["published_schedule"], instructor=row["instructor_published"]),
            instructors=instructors(row["instructor_names"]), sessions=sessions))

    counts = dict(sections=len(sections), unique_course_codes=len({row["course_code"] for row in sections}),
                  sections_by_branch=dict(branches), scheduled_sections=scheduled,
                  sections_without_published_time=len(sections) - scheduled, weekly_session_rows=weekly,
                  sessions_with_known_building_and_room=known_rooms, sessions_without_known_room=weekly - known_rooms)
    if any(source["summary"][key] != value for key, value in counts.items()):
        raise ValueError("The ITU archive records do not reconcile with the supplied summary.")
    conflicts, supplemental, supplemental_sources = _supplement(supplemental_path, sections, rooms, instructors)
    return dict(term=source["term"], timezone=source["timezone"], provenance=provenance,
                sourceSha256=hashlib.sha256(payload).hexdigest(), sections=sections + supplemental,
                primaryCounts=counts, supplementalCount=len(supplemental), supplementalSources=supplemental_sources,
                supplementalConflicts=conflicts, instructorAliases=alias_matches)
