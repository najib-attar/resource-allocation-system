"""Initialize a local ITU demonstration from verified public and synthetic inputs."""

from collections import Counter
from datetime import date, timedelta
import json
import random
from pathlib import Path
import secrets
import unicodedata

from sqlalchemy import select

from ..account_service import AccountService
from ..engine_gateway import EngineGateway, PROTOCOL_VERSION
from ..room_request_service import RoomRequestService
from .equipment_demo import seed_equipment_demo
from .importer import populate_empty_database
from .itu_resources import catalog_manifest, install_resource_policies, resource_spaces
from .models import AcademicPeriod, BusySlot, LegacyCalendarBinding, OrganizationUnit, ProfessorAvailability
from .repository import PROFILE_FIELDS, state_row
from .validation import validate_snapshot


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "itu_demo"
UNIVERSITY = "İstanbul Teknik Üniversitesi"
FACULTY = "Bilgisayar ve Bilişim Fakültesi"
DEPARTMENTS = {"BLG": "Bilgisayar Mühendisliği", "YZV": "Yapay Zeka ve Veri Mühendisliği",
               "SGM": "Siber Güvenlik Mühendisliği"}
STUDENT_COUNTS = {"BLG": 100, "YZV": 10, "SGM": 10}
ROLE = {"academic": "Instructor", "research_assistant": "TeachingAssistant",
        "visiting": "Instructor", "affiliated_coordinator": "Instructor", "administrative": "Staff"}
GIVEN = ("Ada", "Aras", "Aylin", "Baran", "Beril", "Deniz", "Duru", "Elif", "Eren", "Eylül",
         "Işıl", "Kaan", "Lale", "Nehir", "Öykü", "Selin", "Yaren", "Amina", "Elias",
         "Haruto", "Leila", "Maya", "Nora", "Samir")
SURNAMES = ("Acar", "Akın", "Alp", "Aslan", "Aydın", "Çelik", "Demir", "Doğan", "Erdem",
            "Güneş", "Kaya", "Koç", "Özer", "Şahin", "Tekin", "Yalçın", "Yıldız",
            "Haddad", "Khan", "Kim", "Morales", "Nguyen", "Patel", "Rossi")


def _key(name):
    return " ".join(unicodedata.normalize("NFC", name).casefold().split())


def _slug(name):
    normalized = unicodedata.normalize("NFKD", name.lower().replace("ı", "i"))
    ascii_name = normalized.encode("ascii", "ignore").decode()
    return ".".join(part for part in ascii_name.split() if part.isalnum())


def _read(directory, name):
    try:
        return json.loads((directory / name).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise ValueError(f"Read the required local ITU data file {name} as UTF-8 JSON.") from error


def load_itu_schedule(directory=DATA):
    return _read(directory, "schedule.json")


def _person(user_id, name, role, unit, username, **values):
    record = dict.fromkeys(PROFILE_FIELDS, "")
    record.update(id=user_id, name=name, role=role, primaryUnit=unit, assignedRoles=[role],
                  status="active" if username else "directory-only",
                  email=f"{username}@example.invalid" if username else "", yearLevel=0)
    record.update(values)
    return record


def _slot(day, start, end):
    return dict(day=day, startMinutes=start, endMinutes=end)


def _overlap(left, right):
    return (left["day"] == right["day"] and left["startMinutes"] < right["endMinutes"]
            and right["startMinutes"] < left["endMinutes"])


def _section_slot(section):
    return {key: section[key] for key in ("day", "startMinutes", "endMinutes")}


def _student_slots(sections, enrollments, department, year, rng):
    candidates = [rows for rows in sections.values()
                  if all(year in row["recommendedYears"].get(department, []) for row in rows)]
    rng.shuffle(candidates)
    slots, used = [], set()
    for rows in candidates:
        first = rows[0]
        code, crn = first["courseCode"], first["section"]
        if code in used or enrollments[crn] >= min(row["capacity"] for row in rows):
            continue
        times = [_section_slot(row) for row in rows]
        if any(_overlap(slot, saved["slot"]) for slot in times for saved in slots):
            continue
        if any(_overlap(slot, other) for i, slot in enumerate(times) for other in times[:i]):
            continue
        used.add(code)
        enrollments[crn] += 1
        for row, slot in zip(rows, times):
            slots.append(dict(slot=slot, reason=f"Simulated enrollment: {code} · {first['courseTitle']}",
                              section=crn, sourceUrl=row["sourceUrl"]))
        if len(used) == 4:
            break
    if slots:
        return slots
    return [dict(slot=_slot(day, 540 + shift, 630 + shift),
                 reason=f"Simulated {department} year {year} study session")
            for day, shift in zip(sorted(rng.sample(range(1, 6), 3)), (0, 120, 240))]


def itu_inputs(directory=DATA, seed=42):
    roster = _read(directory, "roster.json")
    schedule = load_itu_schedule(directory)
    people = roster["people"]
    department_counts = Counter(person["department"] for person in people
                                if person["category"] in {"academic", "research_assistant"})
    category_counts = Counter(person["category"] for person in people)
    if department_counts != {"BLG": 61, "YZV": 30, "SGM": 8} or any(
            category_counts[c] != n for c, n in {"visiting": 2, "administrative": 15,
                                               "affiliated_coordinator": 2}.items()):
        raise ValueError("The ITU personnel manifest does not match the supplied candidate counts.")
    seen_names = {_key(person["name"]) for person in people}
    if len(seen_names) != len(people):
        raise ValueError("Duplicate personnel name in the ITU manifest.")
    units = {UNIVERSITY: {"type": "University"}, FACULTY: {"type": "Faculty", "parent": UNIVERSITY}}
    units.update({name: {"type": "Department", "parent": FACULTY} for name in DEPARTMENTS.values()})

    users, accounts, directory_rows = [], [], []
    seen_logins = set()
    instructors = {}
    for person in people:
        user_id = len(users) + 1
        name, category = person["name"], person["category"]
        enabled = person["verification"] == "officially_listed" and category in {
            "academic", "research_assistant", "administrative"}
        username = f"demo.{_slug(name)}" if enabled else None
        if username in seen_logins:
            username = f"{username}.{user_id}"
        if username:
            seen_logins.add(username)
            accounts.append(dict(username=username, userId=user_id, name=name, role=ROLE[category]))
        unit = "" if category == "affiliated_coordinator" else DEPARTMENTS.get(person["department"], FACULTY)
        record = _person(user_id, name, ROLE[category], unit, username,
                         title=person["title"] if category != "administrative" else "",
                         jobTitle=person["title"] if category == "administrative" else "",
                         assistantType="Research Assistant" if category == "research_assistant" else "")
        users.append(record)
        if record["role"] == "Instructor" and category == "academic":
            instructors[_key(name)] = user_id
        directory_rows.append(dict(person, userId=user_id, role=ROLE[category], username=username))

    busy, student_rows = [], []
    sections = schedule["sections"]
    staff_slots = Counter()
    seen_slots = set()
    unresolved = []
    section_groups = {}
    simulated_enrollments = Counter()
    for section in sections:
        section_groups.setdefault(section["section"], []).append(section)
        name = section.get("instructorName")
        instructor = instructors.get(_key(name)) if name else None
        if not instructor:
            unresolved.append(dict(section=section["section"], courseCode=section["courseCode"],
                instructorNames=section["instructorNames"], sourceUrl=section["sourceUrl"]))
            continue
        slot = _section_slot(section)
        key = (instructor, section["section"], *slot.values())
        if key in seen_slots:
            continue
        seen_slots.add(key)
        busy.append(dict(userId=instructor, slot=slot,
                         reason=f"Published teaching: {section['courseCode']} · {section['courseTitle']}"))
        staff_slots[instructor] += 1

    rng = random.Random(seed)
    names = [f"{first} {last}" for first in GIVEN for last in SURNAMES
             if _key(f"{first} {last}") not in seen_names]
    numbers = iter(rng.sample(names, sum(STUDENT_COUNTS.values())))
    for department, count in STUDENT_COUNTS.items():
        years = schedule["departments"][department]["availableYears"]
        choices = [years[i % len(years)] for i in range(count)]
        rng.shuffle(choices)
        for year in choices:
            number = len(student_rows) + 1
            username = f"student{number:03d}"
            user_id = len(users) + 1
            name = next(numbers)
            users.append(_person(user_id, name, "Student", DEPARTMENTS[department], username,
                         studentNo=f"ITU-DEMO-26-{number:03d}", program=DEPARTMENTS[department], yearLevel=year))
            accounts.append(dict(username=username, userId=user_id, name=name, role="Student"))
            enrollments = _student_slots(section_groups, simulated_enrollments, department, year, rng)
            busy.extend(dict(userId=user_id, slot=row["slot"], reason=row["reason"]) for row in enrollments)
            student_rows.append(dict(userId=user_id, username=username, department=department, year=year,
                                     enrollmentYear=2027 - year, schedule=enrollments))

    admin = len(users) + 1
    users.append(_person(admin, "ITU Demo Administrator", "Administrator", FACULTY, "admin"))
    accounts.append(dict(username="admin", userId=admin, name="ITU Demo Administrator", role="Administrator"))
    resources = catalog_manifest(directory, schedule)
    snapshot = dict(protocolVersion=PROTOCOL_VERSION, runId=f"itu-demo-{seed}", strategy="greedy",
                    users=users, spaces=resource_spaces(resources), requests=[], busySlots=busy)
    validate_snapshot(snapshot)
    return snapshot, units, accounts, admin, dict(academicPeriod=schedule["academicPeriod"],
        rosterDate=roster["rosterDate"], sources=roster["sources"], discrepancies=roster["discrepancies"],
        directory=directory_rows, students=student_rows, instructorSlots=sum(staff_slots.values()),
        unmatchedSectionRows=unresolved, simulatedEnrollmentCounts=dict(simulated_enrollments),
        simulatedResources=True, resources=resources)


def seed_itu_demo(database, directory=DATA, seed=42):
    snapshot, units, accounts, admin, manifest = itu_inputs(directory, seed)
    period = manifest["academicPeriod"]
    starts, ends = date.fromisoformat(period["startDate"]), date.fromisoformat(period["endDate"])
    excluded = period["recessDates"]
    populate_empty_database(database, snapshot, units, event_kind="seeded")
    service = AccountService(database)
    credentials = {}
    for account in accounts:
        username = account["username"]
        password = credentials[username] = secrets.token_urlsafe(18)
        service.provision(account["userId"], username, password, administrator=account["userId"] == admin)
    with database.transaction() as session:
        term = AcademicPeriod(name=period["name"], start_date=starts, end_date=ends,
                              timezone="Europe/Istanbul", is_semester=True)
        session.add(term)
        session.flush()
        for row in session.scalars(select(BusySlot)):
            session.add(LegacyCalendarBinding(period_id=term.id, busy_slot_id=row.id, excluded_dates=excluded))

        busy = {(row["userId"], row["slot"]["day"]) for row in snapshot["busySlots"]
                if row["slot"]["startMinutes"] < 1020 and row["slot"]["endMinutes"] > 960}
        for account in accounts:
            if account["role"] == "Instructor":
                for day in range(1, 6):
                    if (account["userId"], day) not in busy:
                        session.add(ProfessorAvailability(user_id=account["userId"], day=day,
                            start_minutes=960, end_minutes=1020, valid_from=starts, valid_until=ends,
                            timezone="Europe/Istanbul", excluded_dates=excluded))
        faculty_id = session.scalar(select(OrganizationUnit.id).where(OrganizationUnit.name == FACULTY))
        resources = manifest["resources"]
        resources["datedOccupancyBlocks"] = install_resource_policies(session, resources, faculty_id)
        state_row(session, True).calendar_revision += 1

    rooms = RoomRequestService(database, EngineGateway(ROOT))
    rooms.configure_approver(admin, faculty_id, admin)
    equipment = seed_equipment_demo(database, admin, seed=seed)
    summary = dict(seed=seed, counts={key: len(snapshot[key]) for key in ("users", "spaces", "requests", "busySlots")},
                   accounts=accounts, equipment=equipment, officeHours="simulated")
    return summary, manifest, credentials
