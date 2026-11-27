"""Run the real application against a new, fictional ITU rehearsal cluster."""

import argparse
from contextlib import contextmanager
from datetime import datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
from time import monotonic, sleep
import traceback
from zoneinfo import ZoneInfo

import psycopg
from sqlalchemy import select
from sqlalchemy.engine import URL
from werkzeug.serving import make_server


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.account_service import AccountService
from web.appointment_service import AppointmentService
from web.backend_executable import file_sha256, resolve_backend_executable
from web.engine_gateway import EngineGateway
from web.persistence.importer import populate_empty_database
from web.persistence.itu_course_inputs import TERM_END, TERM_START, course_inputs
from web.persistence.models import (
    AcademicPeriod, CalendarBlock, Course, CourseSection, CourseSession, Enrollment, GroupMeetingAvailability,
    OrganizationUnit, ProfessorAvailability, SchedulingPreferenceRevision, TeachingAssignment,
)
from web.preference_values import parse_values
from web.room_request_service import RoomRequestService
from web.teaching_calendar import assert_teaching_commitments_compatible


DB_NAME = "ras_cdmcs_rehearsal"
DB_USER = "cdmcs_rehearsal"
ZONE = ZoneInfo("Europe/Istanbul")
COURSE_ARCHIVE_SHA = "cd32c1628bca856d70609f79b98afbe589884c9e6f4049bda9b36a3f845cc0b5"
PEOPLE = (
    (1, "Student", "Aylin · Demo Student", "student-aylin"),
    (2, "Student", "Deniz · Demo Student", "student-deniz"),
    (3, "Instructor", "Selin · Demo Instructor", "instructor-selin"),
    (4, "Instructor", "Cem · Demo Instructor", "instructor-cem"),
    (5, "TeachingAssistant", "Ekin · Demo Research Assistant", "assistant-ekin"),
    (6, "Staff", "Nil · Demo Staff", "staff-nil"),
    (7, "Administrator", "ITÜ · Demo Administrator", "demo-admin"),
)


def postgres_tool(directory, name):
    return str(directory / (name + ".exe" if os.name == "nt" else name))


def loopback_port(requested):
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", requested))
        return reserved.getsockname()[1]


@contextmanager
def disposable_postgres(profile, tools, requested_port):
    """Create a new cluster and never accept an external connection URL."""
    data = profile / "postgres-data"
    port = loopback_port(requested_port)
    password = secrets.token_urlsafe(36)
    marker = profile / "rehearsal-owner"
    owner = secrets.token_hex(32)
    marker.write_text(owner, encoding="ascii")
    password_path = profile / "init-password"
    password_path.write_text(password + "\n", encoding="ascii")
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("PG")}
    log_path = profile / "postgres.log"
    with log_path.open("wb") as log:
        try:
            subprocess.run(
                [postgres_tool(tools, "initdb"), "-D", str(data), "-U", DB_USER, "--auth=scram-sha-256",
                 "--encoding=UTF8", "--no-locale", "--no-instructions", f"--pwfile={password_path}"],
                check=True, env=environment, cwd=profile, stdout=log, stderr=subprocess.STDOUT, timeout=90,
            )
        finally:
            password_path.unlink(missing_ok=True)
        child = subprocess.Popen(
            [postgres_tool(tools, "postgres"), "-D", str(data), "-h", "127.0.0.1", "-p", str(port)],
            env=environment, cwd=profile, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
        )
        process_record = data / "postmaster.pid"

        def owned_process():
            return (marker.read_text(encoding="ascii") == owner and process_record.is_file()
                    and process_record.read_text(encoding="utf-8").splitlines()[:1] == [str(child.pid)])

        try:
            deadline = monotonic() + 40
            while True:
                if child.poll() is not None or monotonic() >= deadline:
                    raise RuntimeError("The owned PostgreSQL cluster did not start.")
                try:
                    connection = psycopg.connect(host="127.0.0.1", hostaddr="127.0.0.1", port=port,
                                                 user=DB_USER, password=password, dbname="postgres",
                                                 connect_timeout=2, autocommit=True)
                except psycopg.OperationalError:
                    sleep(0.2)
                    continue
                break
            with connection:
                (directory,) = connection.execute("SHOW data_directory").fetchone()
                (server_port,) = connection.execute("SELECT inet_server_port()").fetchone()
                if Path(directory).resolve() != data or server_port != port or not owned_process():
                    raise RuntimeError("The PostgreSQL listener does not belong to the rehearsal.")
                connection.execute("CREATE DATABASE ras_cdmcs_rehearsal")
            yield URL.create("postgresql+psycopg", username=DB_USER, password=password,
                             host="127.0.0.1", port=port, database=DB_NAME)
        finally:
            if child.poll() is None:
                if owned_process():
                    subprocess.run(
                        [postgres_tool(tools, "pg_ctl"), "-D", str(data), "-m", "fast", "-w", "-t", "15", "stop"],
                        check=False, env=environment, cwd=profile, stdout=log, stderr=subprocess.STDOUT, timeout=20,
                    )
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(5)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait()


def _public_slot(path, first, last):
    if file_sha256(path) != COURSE_ARCHIVE_SHA:
        raise ValueError("Use the reviewed 2026–2027 Fall İTÜ archive for the public schedule mirror.")
    archive = course_inputs(path, [], {})
    for offset in (1, 2, 0):
        day = first + timedelta(days=offset)
        if not TERM_START <= day <= min(last, TERM_END):
            continue
        floor = 540 if offset else 840
        for section in archive["sections"]:
            for slot in section["sessions"]:
                if (slot["day"] == day.isoweekday() and slot["building"] == "BBB" and slot["room"]
                        and floor <= slot["start_minutes"] < slot["end_minutes"] <= 1020
                        and slot["start_minutes"] % 15 == slot["end_minutes"] % 15 == 0):
                    return section, slot, day
    raise ValueError("No aligned published BBB session fits the fixture dates and protected intervals.")


def _mirror_public_slot(session, period, first, last, path):
    section, slot, day = _public_slot(path, first, last)
    title = "Public timetable mirror · " + section["course_code"]
    course = Course(code=section["course_code"], title=title)
    session.add(course)
    session.flush()
    mirror = CourseSection(course_id=course.id, academic_period_id=period.id,
        crn=section["crn"], quota=section["quota"], published_title=title, branch=section["branch"],
        academic_level=section["academic_level"], instruction_method=section["instruction_method"],
        source_kind="archive", source_url=section["source_url"], publication_status="scheduled",
        published_schedule={"mirror": "Public meeting time only; synthetic assignment"},
        excluded_dates=[])
    session.add(mirror)
    session.flush()
    session.add_all((
        TeachingAssignment(section_id=mirror.id, ordinal=1, user_id=3, published_name=PEOPLE[2][2]),
        Enrollment(section_id=mirror.id, user_id=1),
        CourseSession(section_id=mirror.id, ordinal=1, day=slot["day"], building_code="BBB",
            room_code=slot["room"], start_minutes=slot["start_minutes"], end_minutes=slot["end_minutes"],
            published_day=slot["day_published"], published_start=slot["start_time_published"],
            published_end=slot["end_time_published"], published_building=slot["building_published"],
            published_room=slot["room_published"]),
    ))
    midnight = datetime.combine(day, time(), ZONE)
    return {"crn": section["crn"], "sourceSha256": COURSE_ARCHIVE_SHA,
            "start": (midnight + timedelta(minutes=slot["start_minutes"])).isoformat(),
            "end": (midnight + timedelta(minutes=slot["end_minutes"])).isoformat()}


def seed_rehearsal(database, course_archive=None):
    """Install fictional accounts and commitments using the application's real tables."""
    faculty, department = "Fictional ITÜ Engineering Faculty", "Fictional ITÜ Computing"
    snapshot = {
        "protocolVersion": 1, "runId": "cdmcs-fictional-rehearsal", "strategy": "greedy",
        "requests": [], "busySlots": [],
        "users": [
            {
                "id": user_id, "role": role, "name": name, "primaryUnit": department, "status": "active",
                "assistantType": "Research Assistant" if role == "TeachingAssistant" else "",
                "assignedRoles": [], "email": "", "yearLevel": 0,
                **dict.fromkeys(("studentNo", "program", "title", "officeRoom", "jobTitle", "adminLevel"), ""),
            }
            for user_id, role, name, _ in PEOPLE
        ],
        "spaces": [
            {"id": 301, "type": "Classroom", "name": "Rehearsal teaching room", "capacity": 30,
             "building": "Demo BBB", "available": True,
             "features": {"projector": True, "whiteboard": True, "computers": False}},
        ],
    }
    units = {faculty: {"type": "Faculty"}, department: {"type": "Department", "parent": faculty}}
    populate_empty_database(database, snapshot, units, event_kind="seeded")
    account = AccountService(database)
    credentials = []
    for user_id, role, name, username in PEOPLE:
        password = secrets.token_urlsafe(18)
        account.provision(user_id, username, password, administrator=role == "Administrator")
        credentials.append(dict(id=user_id, name=name, role=role, username=username, password=password))
    first = datetime.now(ZONE).date() + timedelta(days=1)
    last = first + timedelta(days=2)
    mirror = None

    def at(day, hour):
        return datetime.combine(first + timedelta(days=day), time(hour), ZONE).astimezone(timezone.utc)

    with database.transaction() as session:
        faculty_id = session.scalar(select(OrganizationUnit.id).where(OrganizationUnit.name == faculty))
        weekdays = sorted((first + timedelta(days=day)).isoweekday() for day in range(3))
        session.add_all(GroupMeetingAvailability(owner_id=uid, revision=1, valid_from=first, valid_until=last,
            windows=[{"weekday": day, "start": "09:00", "end": "17:00"} for day in weekdays],
            allow_relocation=False) for uid, _, _, _ in PEOPLE)
        session.add_all(
            ProfessorAvailability(user_id=person, day=weekday, start_minutes=9 * 60, end_minutes=17 * 60,
                                  valid_from=first, valid_until=last, timezone=ZONE.key, excluded_dates=[])
            for person in (3, 4) for weekday in weekdays
        )
        for user_id, role, _, _ in PEOPLE:
            if role == "Administrator":
                continue
            values = parse_values({
                "timezone": ZONE.key, "effective": {"from": first.isoformat(), "until": last.isoformat()},
                "preferred_weekdays": weekdays,
                "preferred_windows": [
                    {"weekday": day, "start": "10:00" if user_id % 2 == 0 else "11:00", "end": "15:00"}
                    for day in weekdays
                ],
                "desired_gap_minutes": 15 + 5 * (user_id % 3),
            })
            document = values.document()
            session.add(SchedulingPreferenceRevision(
                owner_id=user_id, revision=1, contract_version=1, status="configured", timezone=values.timezone,
                effective_from=values.first, effective_until=values.last, preferred_weekdays=document["preferred_weekdays"],
                preferred_windows=document["preferred_windows"], gap_indifferent=False,
                desired_gap_minutes=values.desired_gap,
            ))
        session.add(CalendarBlock(user_id=5, start_at=at(0, 15), end_at=at(0, 16), reason="Fictional protected lab work"))
        period = AcademicPeriod(name="ITÜ-style synthetic rehearsal term", start_date=first, end_date=last,
                                timezone=ZONE.key, is_semester=True)
        course = Course(code="BLG DEMO", title="Synthetic application integration seminar")
        session.add_all((period, course))
        session.flush()
        section = CourseSection(
            course_id=course.id, academic_period_id=period.id, crn="90001", quota=30, published_title=course.title,
            branch="BLG", academic_level="LS", instruction_method="In person", source_kind="archive",
            source_url="https://example.invalid/cdmcs-rehearsal", publication_status="scheduled",
            published_schedule={}, excluded_dates=[],
        )
        session.add(section)
        session.flush()
        session.add_all((
            TeachingAssignment(section_id=section.id, ordinal=1, user_id=3, published_name=PEOPLE[2][2]),
            Enrollment(section_id=section.id, user_id=1),
            CourseSession(section_id=section.id, ordinal=1, resource_id=301, building_code="BBB", room_code="CDMCS",
                          day=first.isoweekday(), start_minutes=13 * 60, end_minutes=14 * 60,
                          published_day=first.strftime("%A"), published_start="13:00", published_end="13:59",
                          published_building="Rehearsal BBB", published_room="CDMCS"),
        ))
        if course_archive is not None:
            mirror = _mirror_public_slot(session, period, first, last, course_archive)
        session.flush()
        assert_teaching_commitments_compatible(session)
    appointments = AppointmentService(database, EngineGateway(ROOT))
    appointment = appointments.submit(2, [4], [], "Fictional protected advising", 30, at(0, 14), faculty_id)
    appointments.decide(appointment, 4, 1, True)
    rooms = RoomRequestService(database, EngineGateway(ROOT))
    rooms.configure_approver(7, faculty_id, 6)
    rooms.configure_room(7, 301, faculty_id, True, ["meeting"])
    return credentials, at, mirror


@contextmanager
def rehearsal_server(args):
    if not 0 <= args.port <= 65535 or not 0 <= args.postgres_port <= 65535:
        raise ValueError("Ports must be between 0 and 65535.")
    engine = args.engine.resolve()
    if not engine.is_file() or file_sha256(engine) != args.engine_sha256.lower():
        raise ValueError("The CDMCS executable does not match the expected SHA-256.")
    backend = resolve_backend_executable(ROOT, str(args.backend.resolve()) if args.backend else None)
    profile = Path(tempfile.mkdtemp(prefix="cdmcs-rehearsal-", dir=args.output)).resolve()
    print(f"Private rehearsal folder: {profile}", flush=True)
    bootstrap_path = profile / "bootstrap.log"
    try:
        with disposable_postgres(profile, args.postgres_bin.resolve(), args.postgres_port) as url:
            encoded_url = url.render_as_string(hide_password=False)
            os.environ.update(
                DATABASE_URL=encoded_url, RESOURCE_ALLOCATION_BACKEND=str(backend.path),
                RESOURCE_ALLOCATION_TIMEZONE=ZONE.key, RESOURCE_ALLOCATION_DEBUG="0", FLASK_DEBUG="0",
            )
            with bootstrap_path.open("wb") as output:
                subprocess.run([sys.executable, "-B", "-m", "alembic", "-c", str(ROOT / "alembic.ini"), "upgrade", "head"],
                               check=True, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, timeout=90)

            from web.app import app, get_repository
            from web.cdmcs_rehearsal import FlexibleMeeting, RehearsalFixture, register_rehearsal
            from web.group_meeting_routes import register_group_meetings

            app.config.update(DATABASE_URL=encoded_url, SECRET_KEY=secrets.token_hex(32), DEBUG=False,
                              SESSION_COOKIE_SECURE=False, LOCAL_DEMO_DATASET="cdmcs-rehearsal")
            database = get_repository().database
            try:
                credentials, at, mirror = seed_rehearsal(database, args.course_archive)
                flexible = FlexibleMeeting(
                    people=(1, 4), start=at(0, 9), end=at(0, 12),
                    replacements=(at(0, 11), at(0, 12), at(1, 9), at(1, 10)),
                )
                fixture = RehearsalFixture(
                    database=database, engine=engine, engine_sha256=args.engine_sha256.lower(),
                    people=tuple(user_id for user_id, _, _, _ in PEOPLE),
                    start=at(0, 0), end=at(3, 0), flexible=(flexible,),
                )
                register_rehearsal(app, fixture)
                register_group_meetings(app, fixture)
                with make_server("127.0.0.1", args.port, app, threaded=True) as server:
                    address = f"http://127.0.0.1:{server.server_port}"
                    info = {"url": address, "accounts": credentials, "starts": at(0, 0).isoformat(),
                            "ends": at(3, 0).isoformat(), "teachingStarts": at(0, 13).isoformat(),
                            "flexibleStarts": at(0, 9).isoformat(), "publicSlot": mirror}
                    credentials_path = profile / "fictional-logins.json"
                    credentials_path.write_text(json.dumps(info, indent=2), encoding="utf-8")
                    print(f"Ready at {address}. Fictional logins are in {credentials_path}.", flush=True)
                    yield server, credentials_path
            finally:
                database.dispose()
    except KeyboardInterrupt:
        pass
    except Exception:
        with bootstrap_path.open("a", encoding="utf-8") as output:
            traceback.print_exc(file=output)
        raise RuntimeError(f"Rehearsal failed. See {bootstrap_path} and {profile / 'postgres.log'}.") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres-bin", required=True, type=Path)
    parser.add_argument("--engine", required=True, type=Path, help="Standalone CDMCS executable")
    parser.add_argument("--engine-sha256", required=True, help="Expected SHA-256 of the reviewed CDMCS executable")
    parser.add_argument("--backend", type=Path, help="Optional matching production executable for the original workflows")
    parser.add_argument("--port", type=int, default=0, help="Web port; zero chooses a free loopback port")
    parser.add_argument("--postgres-port", type=int, default=0, help="PostgreSQL port; zero chooses a free loopback port")
    parser.add_argument("--output", type=Path, help="Parent directory for a new private rehearsal folder")
    parser.add_argument("--course-archive", type=Path,
                        help="Mirror one verified public timetable interval using fictional people")
    try:
        with rehearsal_server(parser.parse_args()) as (server, _):
            server.serve_forever()
    except (ValueError, RuntimeError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
