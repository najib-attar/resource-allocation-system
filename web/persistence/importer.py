"""Explicit, non-destructive CSV import. Never used as operational persistence."""

import csv
import uuid
from pathlib import Path

from sqlalchemy import func, select

try:
    from ..engine_gateway import EngineIntegrationError, PROTOCOL_VERSION
    from ..input_validation import integer, minutes, parse_time_slots
except ImportError:
    from engine_gateway import EngineIntegrationError, PROTOCOL_VERSION
    from input_validation import integer, minutes, parse_time_slots
from .models import Base, BusySlot, OrganizationUnit, RequestHistory, Resource, ResourceRequest, Role, ROLES, STRATEGIES, User, UserRole
from .validation import DataValidationError as ImportValidationError, require, validate_snapshot
from .repository import PROFILE_FIELDS, PersistenceError, advance_identity, insert_request, state_row, validate_unit_hierarchy


def csv_bool(value, default=False):
    value = (value or "").strip().lower()
    if not value:
        return default
    if value in ("1", "true"):
        return True
    if value in ("0", "false"):
        return False
    raise EngineIntegrationError("Invalid persisted boolean")


def _execution_snapshot(tables, strategy):
    """Translate explicit offline CSV inputs into DTOs; normal runs snapshot PostgreSQL."""
    def rows(name):
        return tables[name]["rows"]
    def optional(row, key):
        value = row.get(key) or ""
        return "" if value == "None" else value
    users = []
    for row in rows("users.csv"):
        item = {"id": integer(row.get("userId"), "userId"), "name": row.get("name", ""), "role": row.get("role", "")}
        for key in ("email", "primaryUnit", "studentNo", "program", "title", "officeRoom", "assistantType", "jobTitle", "adminLevel"):
            item[key] = optional(row, key)
        item["status"] = row.get("status") or "active"
        item["yearLevel"] = integer(row.get("yearLevel") or "0", "yearLevel")
        item["assignedRoles"] = [part.strip() for part in optional(row, "assignedRoles").split("|") if part.strip()]
        users.append(item)
    spaces = [{"id": integer(row.get("spaceId"), "spaceId"), "name": row.get("name", ""),
               "type": row.get("type", ""), "capacity": integer(row.get("capacity"), "capacity", 1),
               "building": optional(row, "building"), "available": csv_bool(row.get("isAvailable"), True),
               "features": {key: csv_bool(row.get(column)) for key, column in
                            (("projector", "hasProjector"), ("whiteboard", "hasWhiteboard"), ("computers", "hasComputers"))}}
              for row in rows("spaces.csv")]
    participants = {}
    for row in rows("request_participants.csv"):
        participants.setdefault(integer(row.get("requestId"), "participant requestId"), []).append(
            {"userId": integer(row.get("userId"), "participant userId"), "role": optional(row, "participantRole")})
    requests = []
    for row in rows("requests.csv"):
        item = {"id": integer(row.get("requestId"), "requestId"), "type": row.get("requestType", ""),
                "requesterId": integer(row.get("userId"), "requesterId"), "spaceId": integer(row.get("spaceId"), "spaceId"),
                "participantCount": integer(row.get("participantCount"), "participantCount", 1),
                "slots": parse_time_slots(row.get("timeData") or "")}
        for key in ("title", "purpose", "requiredFeature", "requiredBuilding"):
            item[key] = optional(row, key)
        if item["type"] == "Exam":
            item["exam"] = {key: optional(row, key) for key in ("courseCode", "courseName", "examType")}
            item["exam"]["canSplitAcrossRooms"] = csv_bool(row.get("canSplitAcrossRooms"))
        if item["type"] == "CommitteeMeeting":
            item["participants"] = participants.get(item["id"], [])
        requests.append(item)
    known_requests = {item["id"]: item["type"] for item in requests}
    if any(known_requests.get(rid) != "CommitteeMeeting" for rid in participants):
        raise EngineIntegrationError("Participant rows must reference a CommitteeMeeting request")
    busy = [{"userId": integer(row.get("userId"), "busy userId"), "reason": optional(row, "reason"),
             "slot": {"day": integer(row.get("day"), "busy day"), "startMinutes": minutes(row.get("startTime")),
                      "endMinutes": minutes(row.get("endTime"))}} for row in rows("user_busy_slots.csv")]
    return {"protocolVersion": PROTOCOL_VERSION, "runId": uuid.uuid4().hex, "strategy": strategy,
            "users": users, "spaces": spaces, "busySlots": busy, "requests": requests}


class CsvInputs:
    REQUIRED = {"users.csv": {"userId", "name", "role"},
                "spaces.csv": {"spaceId", "name", "type", "capacity"},
                "requests.csv": {"requestId", "requestType", "userId", "spaceId", "participantCount", "timeData"},
                "user_busy_slots.csv": {"userId", "day", "startTime", "endTime"},
                "request_participants.csv": {"requestId", "userId"}}
    KNOWN = {"users.csv": REQUIRED["users.csv"] | {"email", "status", "primaryUnit", "assignedRoles", "studentNo", "program", "yearLevel", "title", "officeRoom", "assistantType", "jobTitle", "adminLevel"},
             "spaces.csv": REQUIRED["spaces.csv"] | {"hasProjector", "hasWhiteboard", "hasComputers", "isAvailable", "building"},
             "requests.csv": REQUIRED["requests.csv"] | {"requiredFeature", "requiredBuilding", "title", "purpose", "courseCode", "courseName", "examType", "canSplitAcrossRooms"},
             "user_busy_slots.csv": REQUIRED["user_busy_slots.csv"] | {"reason"},
             "request_participants.csv": REQUIRED["request_participants.csv"] | {"participantRole"}}

    def __init__(self, directory):
        self.directory = Path(directory)
        self.tables = {}
        self.warnings = []
        if any((self.directory / name).exists() for name in
               ("allocations.csv", "request_results.csv", "request_summaries.csv", "allocation_summaries.csv", ".runtime/engine-result.json")):
            self.warnings.append("Generated results are retained untouched, not imported; run the verified engine after migration to publish database results.")
        for filename, required in self.REQUIRED.items():
            path = self.directory / filename
            if not path.exists() and filename in {"user_busy_slots.csv", "request_participants.csv"}:
                self.tables[filename] = {"rows": []}
                self.warnings.append(f"Optional {filename} missing; imported no rows.")
                continue
            require(path.is_file(), f"Missing input file: {filename}")
            try:
                with path.open(encoding="utf-8-sig", newline="") as file:
                    reader = csv.DictReader(file, strict=True)
                    require(required <= set(reader.fieldnames or []), f"{filename}: missing required columns.")
                    require(len(reader.fieldnames) == len(set(reader.fieldnames)), f"{filename}: duplicate headers.")
                    require(set(reader.fieldnames) <= self.KNOWN[filename], f"{filename}: unmapped columns; review before import.")
                    rows = []
                    for row in reader:
                        require(None not in row and all(value is not None for value in row.values()),
                                f"{filename}: row {reader.line_num} has incorrect column count.")
                        rows.append(row)
                    self.tables[filename] = {"rows": rows}
            except (csv.Error, UnicodeError) as error:
                raise ImportValidationError(f"{filename}: malformed UTF-8 CSV: {error}") from error

    def snapshot(self):
        strategy = "greedy"
        config = self.directory / "config.txt"
        if config.exists():
            for line in config.read_text(encoding="utf-8-sig").splitlines():
                if "=" in line and line.split("=", 1)[0].strip() == "allocation_strategy":
                    strategy = line.split("=", 1)[1].strip() or "greedy"
        if strategy not in STRATEGIES:
            self.warnings.append("Unknown strategy config; using the existing greedy fallback.")
            strategy = "greedy"
        try:
            snapshot = _execution_snapshot(self.tables, strategy)
        except EngineIntegrationError as error:
            raise ImportValidationError("CSV validation failed: " + str(error)) from error
        validate_snapshot(snapshot)
        return snapshot


def import_csv(database, directory, dry_run=False):
    inputs = CsvInputs(directory)
    snapshot = inputs.snapshot()
    report = {"dryRun": dry_run, "counts": {key: len(snapshot[key]) for key in ("users", "spaces", "requests", "busySlots")},
              "participants": sum(len(item.get("participants", [])) for item in snapshot["requests"]),
              "strategy": snapshot["strategy"], "warnings": inputs.warnings}
    if dry_run:
        return report
    populate_empty_database(database, snapshot)
    return report


def populate_empty_database(database, snapshot, unit_definitions=None, event_kind="imported"):
    """One-time validated initialization only; never reset or merge a populated target."""
    validate_snapshot(snapshot)
    unit_definitions = unit_definitions or {}
    unit_names = list(dict.fromkeys(item["primaryUnit"] for item in snapshot["users"] if item["primaryUnit"]))
    unit_names += [name for name in unit_definitions if name not in unit_names]
    require(all(isinstance(name, str) and name and isinstance(definition, dict)
                and (definition.get("type") is None or isinstance(definition["type"], str))
                and (definition.get("parent") is None or isinstance(definition["parent"], str))
                for name, definition in unit_definitions.items()), "Malformed organization metadata.")
    try:
        validate_unit_hierarchy({name: unit_definitions.get(name, {}).get("parent") for name in unit_names})
    except PersistenceError as error:
        raise ImportValidationError(str(error)) from error
    with database.transaction() as session:
        state = state_row(session, lock=True)
        for table in Base.metadata.sorted_tables:
            if table.name != "application_state":
                require(session.scalar(select(func.count()).select_from(table)) == 0, "Database already contains application data; import refused.")
        require(state.input_revision == 0 and state.active_run_id is None, "Database is not an empty migration target.")
        names = list(ROLES)
        for user in snapshot["users"]:
            for name in user["assignedRoles"]:
                if name not in names:
                    names.append(name)
        roles = {name: Role(name=name) for name in names}
        session.add_all(roles.values())
        units = {name: OrganizationUnit(name=name, unit_type=unit_definitions.get(name, {}).get("type")) for name in unit_names}
        session.add_all(units.values())
        session.flush()
        for name, definition in unit_definitions.items():
            parent = definition.get("parent")
            require(parent is None or parent in units, f"Unit {name}: unknown parent.")
            require(parent != name, f"Unit {name}: self-parent is invalid.")
            units[name].parent_id = units[parent].id if parent else None
        for ordinal, item in enumerate(snapshot["users"], 1):
            session.add(User(id=item["id"], source_order=ordinal, name=item["name"], primary_role_id=roles[item["role"]].id,
                             primary_unit_id=units[item["primaryUnit"]].id if item["primaryUnit"] else None,
                             **{column: item[key] for key, column in PROFILE_FIELDS.items()}))
        for ordinal, item in enumerate(snapshot["spaces"], 1):
            session.add(Resource(id=item["id"], source_order=ordinal, type=item["type"], name=item["name"], capacity=item["capacity"],
                                 building=item["building"], available=item["available"], **item["features"]))
        session.flush()
        for item in snapshot["users"]:
            for ordinal, name in enumerate(item["assignedRoles"], 1):
                session.add(UserRole(user_id=item["id"], role_id=roles[name].id, ordinal=ordinal))
        for ordinal, item in enumerate(snapshot["requests"], 1):
            record = insert_request(session, item, ordinal)
            session.add(RequestHistory(request_id=record.id, kind=event_kind, message="Imported from validated CSV input." if event_kind == "imported" else "Created from fictional development demo data."))
        for ordinal, item in enumerate(snapshot["busySlots"], 1):
            slot = item["slot"]
            session.add(BusySlot(user_id=item["userId"], source_order=ordinal, day=slot["day"],
                                 start_minutes=slot["startMinutes"], end_minutes=slot["endMinutes"], reason=item["reason"]))
        state.strategy = snapshot["strategy"]
        state.input_revision += 1
        session.flush()
        for model in (Role, OrganizationUnit, User, Resource, ResourceRequest, BusySlot):
            advance_identity(session, model)
        advance_identity(session, ResourceRequest, "submission_order")
