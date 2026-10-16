"""Private configuration and fictional inputs for the local demonstration launcher."""

import argparse
from datetime import date, datetime, time, timedelta
import json
import os
from pathlib import Path
import secrets
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import select
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError

from web.account_service import AccountService
from web.allocation_workflow import execute_allocation
from web.engine_gateway import EngineGateway, EngineIntegrationError
from web.persistence.database import Database
from web.persistence.demo import demo_snapshot
from web.persistence.importer import populate_empty_database
from web.persistence.models import (AcademicPeriod, BusySlot, CalendarBlock, LegacyCalendarBinding,
                                    LoginAccount, OrganizationUnit, ProfessorAvailability, ResourceRequest)
from web.persistence.repository import PersistenceError, Repository, state_row
from web.room_request_service import RoomRequestService
from web.persistence.equipment_demo import seed_equipment_demo


def demo_inputs(seed):
    snapshot, units = demo_snapshot(seed)
    professors = [item for item in snapshot["users"] if item["role"] == "Instructor"]
    # A predictable pair in one faculty makes the multi-professor walkthrough easy.
    for professor in professors[:2]:
        professor["primaryUnit"] = "Computing Department"
    return snapshot, units


def validate_period(start, end):
    if not date(1970, 1, 1) <= start <= end < date(2100, 1, 1) or end - start > timedelta(days=730):
        raise ValueError("Use an explicit fictional academic period of at most two years, between 1970 and 2099.")


def seed_local_demo(database, password, start, end, seed=42):
    validate_period(start, end)
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise ValueError("The generated demo password must contain 12-256 characters.")
    snapshot, units = demo_inputs(seed)
    populate_empty_database(database, snapshot, units, event_kind="seeded")
    accounts, counters = [], {}
    service = AccountService(database)
    for person in snapshot["users"]:
        prefix = {"Student": "student", "Instructor": "professor", "Administrator": "admin"}.get(person["role"])
        if prefix is None:
            continue
        counters[prefix] = counters.get(prefix, 0) + 1
        username = prefix if prefix == "admin" and counters[prefix] == 1 else prefix + str(counters[prefix])
        service.provision(person["id"], username, password, administrator=prefix == "admin")
        accounts.append({"username": username, "userId": person["id"], "name": person["name"],
                         "role": person["role"]})
    zone = ZoneInfo("Europe/Istanbul")
    week = start - timedelta(days=start.weekday())
    with database.transaction() as session:
        period = AcademicPeriod(name=f"Fictional demo period {start} to {end}", start_date=start,
                                end_date=end, timezone=zone.key)
        session.add(period)
        session.flush()
        for busy in session.scalars(select(BusySlot)):
            session.add(LegacyCalendarBinding(period_id=period.id, busy_slot_id=busy.id, excluded_dates=[]))
        for request in session.scalars(select(ResourceRequest)):
            session.add(LegacyCalendarBinding(period_id=period.id, request_id=request.id, excluded_dates=[],
                week_start=None if request.type == "Recurring" else week))
        for professor in (item for item in snapshot["users"] if item["role"] == "Instructor"):
            for day in range(1, 6):
                session.add(ProfessorAvailability(user_id=professor["id"], day=day, start_minutes=540,
                    end_minutes=1020, valid_from=start, valid_until=end, timezone=zone.key, excluded_dates=[]))
        students = [item for item in snapshot["users"] if item["role"] == "Student"]
        optional_block = datetime.combine(start, time(13), zone)
        session.add(CalendarBlock(user_id=students[1]["id"], start_at=optional_block,
                    end_at=optional_block + timedelta(hours=2), reason="Fictional optional student conflict"))
        state_row(session, True).calendar_revision += 1
    result = execute_allocation(Repository(database), EngineGateway(ROOT))
    # Ownership is explicit fictional fixture configuration, never a legacy backfill.
    room_service = RoomRequestService(database, EngineGateway(ROOT))
    administrators = [row['id'] for row in snapshot['users'] if row['role'] == 'Administrator']
    with database.transaction(read_only=True) as session:
        faculties = list(session.scalars(select(OrganizationUnit.id).where(OrganizationUnit.unit_type == 'Faculty').order_by(OrganizationUnit.name)))
    for index, faculty_id in enumerate(faculties):
        room_service.configure_approver(administrators[0], faculty_id, administrators[index % len(administrators)])
    for index, room in enumerate(snapshot['spaces']):
        room_service.configure_room(administrators[0], room['id'], faculties[index % len(faculties)], True,
                                    ['study','meeting','lecture','club','other'])
    equipment = seed_equipment_demo(database, administrators[0], seed=seed)
    return {"seed": seed, "academicStart": start.isoformat(), "academicEnd": end.isoformat(),
            "counts": {key: len(snapshot[key]) for key in ("users", "spaces", "requests", "busySlots")},
            "accounts": accounts, "allocationCount": len(result["allocations"]), "configuredStudentRooms": len(snapshot['spaces']),
            "equipment": equipment}


def write_settings(path, settings):
    temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    try:
        temporary.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare_settings(path, seed=None, start=None, end=None, port=None):
    if path.exists():
        settings = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(settings, dict) or settings.get("kind") != "university-local-demo" or settings.get("version") != 1:
            raise ValueError("This directory is not an owned local demo. Its files were not changed.")
        if (settings.get("postgresUser") != "ras_demo" or settings.get("databaseName") != "ras_university_demo" or
                type(settings.get("postgresPort")) is not int or not 1 <= settings["postgresPort"] <= 65535 or
                type(settings.get("seeded")) is not bool or type(settings.get("seed")) is not int or
                any(not isinstance(settings.get(key), str) or len(settings[key]) < minimum for key, minimum in
                    (("profileId", 32), ("postgresPassword", 12), ("demoPassword", 12), ("sessionSecret", 32)))):
            raise ValueError("Invalid saved demo configuration. Files were preserved; do not reset an existing database.")
        validate_period(date.fromisoformat(settings["academicStart"]), date.fromisoformat(settings["academicEnd"]))
        for key, value in (("seed", seed), ("academicStart", start), ("academicEnd", end), ("postgresPort", port)):
            if value is not None and settings[key] != value:
                raise ValueError("Saved demo settings differ. Reuse them or choose a new -Profile; existing data is never reset.")
        return settings
    first, last = date.fromisoformat(start or "2030-01-07"), date.fromisoformat(end or "2030-01-31")
    validate_period(first, last)
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("PostgreSQL port must be between 1 and 65535.")
    settings = {"kind": "university-local-demo", "version": 1, "profileId": secrets.token_hex(16),
                "seed": seed if seed is not None else 42, "academicStart": first.isoformat(), "academicEnd": last.isoformat(),
                "postgresPort": port if port is not None else 55443, "postgresUser": "ras_demo",
                "databaseName": "ras_university_demo", "postgresPassword": secrets.token_hex(24),
                "demoPassword": secrets.token_urlsafe(18), "sessionSecret": secrets.token_hex(32), "seeded": False}
    write_settings(path, settings)
    return settings


def connection_url(settings):
    return URL.create("postgresql+psycopg", username=settings["postgresUser"], password=settings["postgresPassword"],
                      host="127.0.0.1", port=settings["postgresPort"], database=settings["databaseName"]).render_as_string(hide_password=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True)
    commands = parser.add_subparsers(dest="action", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--seed", type=int)
    prepare.add_argument("--start")
    prepare.add_argument("--end")
    prepare.add_argument("--port", type=int)
    commands.add_parser("seed")
    commands.add_parser("show")
    args = parser.parse_args()
    path = Path(args.state_dir).resolve() / "settings.json"
    database = None
    try:
        if args.action == "prepare":
            prepare_settings(path, args.seed, args.start, args.end, args.port)
            print("Private local demo configuration is ready.")
            return 0
        settings = prepare_settings(path)
        if args.action == "show":
            print("LOCAL FICTIONAL DEMO ONLY - never reuse these accounts in production.")
            print(f"Calendar: {settings['academicStart']} through {settings['academicEnd']} (Europe/Istanbul)")
            print("Demo password: " + settings["demoPassword"])
            for username in ("admin", "student1", "student2", "professor1", "professor2"):
                account = next(item for item in settings["summary"]["accounts"] if item["username"] == username)
                print(f"  {username}: {account['name']} ({account['role']}, user {account['userId']})")
            print("All student1..student80 and professor1..professor12 accounts use the displayed demo password.")
            return 0
        database = Database(connection_url(settings))
        if settings["seeded"]:
            with database.transaction(read_only=True) as session:
                if session.scalar(select(LoginAccount.user_id).where(LoginAccount.username == "admin")) is None:
                    raise ValueError("The saved demo database is incomplete. Data was preserved; use a new profile or inspect recovery.")
            print("Existing demo reused; no people, passwords, requests or calendars were overwritten.")
        else:
            settings["summary"] = seed_local_demo(database, settings["demoPassword"], date.fromisoformat(settings["academicStart"]),
                                                   date.fromisoformat(settings["academicEnd"]), settings["seed"])
            settings["seeded"] = True
            write_settings(path, settings)
            print(json.dumps({key: value for key, value in settings["summary"].items() if key != "accounts"}, indent=2))
        return 0
    except (ValueError, PersistenceError, EngineIntegrationError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, SQLAlchemyError):
        print("Local demo setup failed. Existing data was preserved; check tools, database/migrations and private settings. No reset was performed.", file=sys.stderr)
        return 1
    finally:
        if database is not None:
            database.dispose()


if __name__ == "__main__":
    sys.exit(main())
