"""Explicit, non-destructive CSV import. Never used as operational persistence."""

import csv
from pathlib import Path

from sqlalchemy import func, select

try:
    from ..engine_gateway import EngineIntegrationError, execution_snapshot
except ImportError:
    from engine_gateway import EngineIntegrationError, execution_snapshot
from .models import Base, BusySlot, OrganizationUnit, REQUEST_TYPES, RequestHistory, Resource, ResourceRequest, Role, ROLES, SPACE_TYPES, STRATEGIES, User, UserRole
from .repository import PROFILE_FIELDS, PersistenceError, advance_identity, insert_request, state_row, validate_unit_hierarchy


class ImportValidationError(PersistenceError):
    pass


def require(condition, message):
    if not condition:
        raise ImportValidationError(message)


def validate_slot(slot):
    require(isinstance(slot, dict), "Time slot must be an object.")
    require(all(type(slot.get(key)) is int for key in ("day", "startMinutes", "endMinutes")), "Time values must be integers.")
    require(1 <= slot["day"] <= 7 and 0 <= slot["startMinutes"] < slot["endMinutes"] <= 1440, "Invalid weekly time range.")


def validate_request(item, users, resources):
    require(isinstance(item, dict), "Request must be an object.")
    label = f"Request {item.get('id', '(new)')}"
    require(item.get("type") in REQUEST_TYPES, label + ": unknown request type.")
    require(type(item.get("requesterId")) is int and item["requesterId"] in users, label + ": missing user reference.")
    require(type(item.get("spaceId")) is int and item["spaceId"] in resources, label + ": missing space reference.")
    require(type(item.get("participantCount")) is int and 0 < item["participantCount"] <= 2147483647, label + ": invalid participant count.")
    require(isinstance(item.get("slots"), list) and 0 < len(item["slots"]) <= 10000, label + ": missing occurrence slots.")
    require(item["type"] == "Recurring" or len(item["slots"]) == 1, label + ": request requires exactly one slot.")
    for key in ("title", "purpose", "requiredFeature", "requiredBuilding"):
        require(isinstance(item.get(key, ""), str), label + f": {key} must be text.")
    for slot in item["slots"]:
        validate_slot(slot)
    if item["type"] == "CommitteeMeeting":
        participants = item.get("participants", [])
        require(isinstance(participants, list), label + ": malformed participants.")
        require(all(isinstance(participant, dict) and isinstance(participant.get("role", ""), str) for participant in participants),
                label + ": malformed participant metadata.")
        ids = [participant.get("userId") for participant in participants]
        require(all(type(uid) is int and uid in users for uid in ids), label + ": missing participant reference.")
        require(len(ids) == len(set(ids)), label + ": duplicate participant IDs.")
    if item["type"] == "Exam":
        require(isinstance(item.get("exam"), dict) and type(item["exam"].get("canSplitAcrossRooms")) is bool,
                label + ": invalid exam metadata.")
        require(all(isinstance(item["exam"].get(key, ""), str) for key in ("courseCode", "courseName", "examType")),
                label + ": examination metadata must be text.")
    else:
        require("exam" not in item, label + ": exam metadata belongs only to Exam requests.")
    if item["type"] != "CommitteeMeeting":
        require(not item.get("participants"), label + ": participants belong only to CommitteeMeeting requests.")


def validate_snapshot(snapshot):
    for key in ("users", "spaces", "requests"):
        require(len(snapshot[key]) <= 10000, key + ": exceeds protocol v1 item limit.")
        ids = [item["id"] for item in snapshot[key]]
        require(all(type(uid) is int and 0 < uid <= 2147483647 for uid in ids), key + ": invalid IDs.")
        require(len(ids) == len(set(ids)), key + ": duplicate IDs; import refused rather than skipping data.")
    users = {item["id"] for item in snapshot["users"]}
    resources = {item["id"] for item in snapshot["spaces"]}
    for item in snapshot["users"]:
        require(item["role"] in ROLES, f"User {item['id']}: unknown primary role.")
        require(len(item["assignedRoles"]) == len(set(item["assignedRoles"])), f"User {item['id']}: duplicate assigned role labels.")
    for item in snapshot["spaces"]:
        require(item["type"] in SPACE_TYPES, f"Space {item['id']}: unknown space type.")
    for item in snapshot["requests"]:
        validate_request(item, users, resources)
    for item in snapshot["busySlots"]:
        require(item["userId"] in users, "Busy slot: missing user reference.")
        validate_slot(item["slot"])


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

    def read_csv_table(self, filename):
        return self.tables[filename]

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
            snapshot = execution_snapshot(self, strategy)
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
