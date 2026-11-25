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

from sqlalchemy import func, select, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError

from web.account_service import AccountService, is_research_assistant
from web.allocation_workflow import execute_allocation
from web.engine_gateway import EngineGateway, EngineIntegrationError
from web.persistence.database import Database, DatabaseBusy
from web.persistence.demo import demo_snapshot
from web.persistence.itu_demo import DATA as ITU_DATA, FACULTY as ITU_FACULTY, load_itu_schedule, seed_itu_demo
from web.persistence.itu_courses import COURSE_SEED, install_itu_courses
from web.persistence.itu_resources import catalog_manifest, replace_legacy_resources
from web.persistence.importer import populate_empty_database
from web.persistence.models import (AcademicPeriod, BusySlot, CalendarBlock, LegacyCalendarBinding,
                                    LoginAccount, OrganizationUnit, ProfessorAvailability, Resource, ResourceRequest)
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


def seed_local_demo(database, password, start, end, seed=42, *, review_academics=False):
    validate_period(start, end)
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise ValueError("The generated demo password must contain 12-256 characters.")
    snapshot, units = demo_inputs(seed)
    populate_empty_database(database, snapshot, units, event_kind="seeded")
    accounts, counters = [], {}
    service = AccountService(database)
    for person in snapshot["users"]:
        prefix = {"Student": "student", "Instructor": "professor", "Administrator": "admin"}.get(person["role"])
        if is_research_assistant(person["role"], person.get("assistantType")):
            prefix = "assistant"
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
    result = {'allocations':[]}
    if review_academics:
        # Explicit opt-in applies only to these newly generated fictional declarations.
        from web.academic_eligibility import EligibilityService
        from web.persistence.models import RequestEligibility
        administrators=[person['id'] for person in snapshot['users'] if person['role']=='Administrator']
        with database.transaction(read_only=True) as session:
            pending=[(r.id,r.requester_id,r.revision,e.version) for r,e in session.execute(select(ResourceRequest,RequestEligibility)
                .join(RequestEligibility,RequestEligibility.request_id==ResourceRequest.id))]
        for key,owner,revision,version in pending:
            reviewer=next((actor for actor in administrators if actor!=owner),None)
            if reviewer is None:raise PersistenceError('Another administrator must review this fictional declaration.')
            EligibilityService(database).decide(reviewer,key,revision,version,True,'Explicit operator-approved review of newly generated fictional demo input.')
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
            "equipment": equipment,"academicReviewRequired":not review_academics}


def write_settings(path, settings):
    temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    try:
        temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare_settings(path, seed=None, start=None, end=None, port=None, dataset=None):
    if path.exists():
        settings = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(settings, dict) or settings.get("kind") != "university-local-demo" or settings.get("version") != 1:
            raise ValueError("This directory is not an owned local demo. Its files were not changed.")
        saved_dataset = settings.get("dataset", "fictional")
        database_names = {"itu": {"ras_itu_demo"}, "fictional": {"resource_allocation", "ras_university_demo"}}
        if dataset is not None and dataset != saved_dataset:
            raise ValueError("This profile already has a different dataset. Choose a new profile name.")
        if (settings.get("postgresUser") != "ras_demo" or settings.get("databaseName") not in database_names.get(saved_dataset, ()) or
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
    dataset = dataset or "fictional"
    if dataset not in {"itu", "fictional"}:
        raise ValueError("Choose a supported demonstration dataset.")
    if dataset == "itu":
        period = load_itu_schedule()["academicPeriod"]
        official = period["startDate"], period["endDate"]
        if seed not in (None, 42) or start not in (None, official[0]) or end not in (None, official[1]):
            raise ValueError("The ITU demo uses seed 42 and the published Fall class dates.")
        start, end = official
    first, last = date.fromisoformat(start or "2030-01-07"), date.fromisoformat(end or "2030-01-31")
    validate_period(first, last)
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("PostgreSQL port must be between 1 and 65535.")
    settings = {"kind": "university-local-demo", "version": 1, "profileId": secrets.token_hex(16),
                "seed": seed if seed is not None else 42, "academicStart": first.isoformat(), "academicEnd": last.isoformat(),
                "postgresPort": port if port is not None else (55546 if dataset == "itu" else 55443),
                "postgresUser": "ras_demo", "dataset": dataset,
                "databaseName": "ras_itu_demo" if dataset == "itu" else "resource_allocation",
                "postgresPassword": secrets.token_hex(24),
                "demoPassword": secrets.token_urlsafe(18), "sessionSecret": secrets.token_hex(32), "seeded": False}
    write_settings(path, settings)
    return settings


def connection_url(settings):
    return URL.create("postgresql+psycopg", username=settings["postgresUser"], password=settings["postgresPassword"],
                      host="127.0.0.1", port=settings["postgresPort"], database=settings["databaseName"]).render_as_string(hide_password=False)


def verify_itu_owner(database, path, settings):
    marker = path.parent / "postgres-data" / "local-demo-owner"
    if (settings.get("dataset") != "itu" or not settings["seeded"] or not marker.is_file()
            or marker.read_text(encoding="utf-8") != settings["profileId"]):
        raise ValueError("This operation requires an initialized ITU profile with its PostgreSQL owner marker.")
    with database.transaction(read_only=True) as session:
        if Path(session.scalar(text("SHOW data_directory"))).resolve() != marker.parent.resolve():
            raise ValueError("The connected PostgreSQL cluster does not belong to this ITU profile.")


def install_course_catalog(database, path, settings):
    verify_itu_owner(database, path, settings)
    report = install_itu_courses(database, seed=settings["seed"])
    write_settings(path.parent / "course-import-report.json", report)
    settings["summary"]["counts"]["spaces"] = report["resourceCount"]
    write_settings(path, settings)
    print(f"ITU course catalog ready: {report['sectionCount']} sections and {report['weeklySessions']} weekly sessions.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True)
    commands = parser.add_subparsers(dest="action", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--seed", type=int)
    prepare.add_argument("--start")
    prepare.add_argument("--end")
    prepare.add_argument("--port", type=int)
    prepare.add_argument("--dataset", choices=("fictional", "itu"))
    seed_command=commands.add_parser("seed")
    seed_command.add_argument('--review-academics',action='store_true',help='Explicitly review newly generated fictional academic declarations before demo allocation.')
    commands.add_parser("show")
    commands.add_parser("update-itu-resources", help="Replace the untouched legacy room seed in an owned ITU demo.")
    commands.add_parser("install-itu-courses", help="Install the archived course dataset in an initialized ITU demo.")
    args = parser.parse_args()
    path = Path(args.state_dir).resolve() / "settings.json"
    database = None
    try:
        if args.action == "prepare":
            prepare_settings(path, args.seed, args.start, args.end, args.port, args.dataset)
            print("Private local demo configuration is ready.")
            return 0
        if args.action in {"update-itu-resources", "install-itu-courses"} and not path.is_file():
            raise ValueError("Select an existing owned ITU demo profile.")
        settings = prepare_settings(path)
        if args.action == "install-itu-courses":
            database = Database(connection_url(settings))
            install_course_catalog(database, path, settings)
            return 0
        if args.action == "update-itu-resources":
            database = Database(connection_url(settings))
            verify_itu_owner(database, path, settings)
            manifest = catalog_manifest(ITU_DATA, load_itu_schedule())
            changed = replace_legacy_resources(database, manifest, ITU_FACULTY)
            resource_report = path.parent / "resource-manifest.json"
            if changed or not resource_report.exists():
                write_settings(resource_report, manifest)
            with database.transaction(read_only=True) as session:
                resource_count = session.scalar(select(func.count()).select_from(Resource))
            if settings["summary"]["counts"]["spaces"] != resource_count:
                settings["summary"]["counts"]["spaces"] = resource_count
                write_settings(path, settings)
            print("ITU building inventory installed." if changed else "ITU building inventory already installed.")
            return 0
        if args.action == "show" and settings.get("dataset") == "itu":
            if not settings["seeded"]:
                raise ValueError("Start the isolated ITU demo once to initialize its private accounts.")
            print("ITU BBF LOCAL DEMO · Public directory and facilities with simulated accounts and capacities.")
            print(f"Fall classes: {settings['academicStart']} through {settings['academicEnd']} (Europe/Istanbul)")
            roles = {account["role"] for account in settings["summary"]["accounts"]}
            for role in sorted(roles):
                account = next(item for item in settings["summary"]["accounts"] if item["role"] == role)
                print(f"  {role}: {account['username']}")
            print(f"Read a single local password from the private profile file {path.parent / 'credentials.json'}.")
            return 0
        if args.action == "show":
            print("LOCAL FICTIONAL DEMO ONLY - never reuse these accounts in production.")
            print(f"Calendar: {settings['academicStart']} through {settings['academicEnd']} (Europe/Istanbul)")
            print("Demo password: " + settings["demoPassword"])
            accounts = {item["username"]: item for item in settings["summary"]["accounts"]}
            for username in ("admin", "student1", "student2", "professor1", "professor2", "assistant1"):
                if username in accounts:
                    account = accounts[username]
                    role = "Research Assistant" if username == "assistant1" else account["role"]
                    print(f"  {username}: {account['name']} ({role}, user {account['userId']})")
            print("The seeded demo accounts use the displayed demo password.")
            return 0
        database = Database(connection_url(settings))
        if settings["seeded"]:
            with database.transaction(read_only=True) as session:
                if session.scalar(select(LoginAccount.user_id).where(LoginAccount.username == "admin")) is None:
                    raise ValueError("The saved demo database is incomplete. Data was preserved; use a new profile or inspect recovery.")
            print("Existing demo reused; no people, passwords, requests or calendars were overwritten.")
        else:
            if settings.get("dataset") == "itu":
                if args.review_academics:
                    raise ValueError("The ITU demo begins without academic requests or decisions.")
                summary, manifest, credentials = seed_itu_demo(database, seed=settings["seed"])
                write_settings(path.parent / "resource-manifest.json", manifest.pop("resources"))
                write_settings(path.parent / "directory-manifest.json", manifest)
                write_settings(path.parent / "credentials.json", credentials)
                settings["summary"] = summary
            else:
                settings["summary"] = seed_local_demo(database, settings["demoPassword"], date.fromisoformat(settings["academicStart"]),
                                                       date.fromisoformat(settings["academicEnd"]), settings["seed"],review_academics=args.review_academics)
            settings["seeded"] = True
            write_settings(path, settings)
            if settings.get("dataset") == "itu" and (ITU_DATA / COURSE_SEED).is_file():
                install_course_catalog(database, path, settings)
            print(json.dumps({key: value for key, value in settings["summary"].items() if key != "accounts"}, indent=2))
        return 0
    except (ValueError, PersistenceError, DatabaseBusy, EngineIntegrationError) as error:
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
