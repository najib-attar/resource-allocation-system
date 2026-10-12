"""Versioned stdin/stdout boundary. No application persistence or allocation decisions."""

import json
import os
import subprocess
import uuid

try:
    from .backend_executable import resolve_backend_executable
except ImportError:
    from backend_executable import resolve_backend_executable


PROTOCOL_VERSION = 1


class EngineIntegrationError(RuntimeError):
    pass


def integer(value, label, minimum=0):
    if isinstance(value, bool):
        raise EngineIntegrationError(f"Invalid {label}")
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise EngineIntegrationError(f"Invalid {label}") from error
    if (not str(value).strip().isdigit() or not minimum <= number <= 2147483647):
        raise EngineIntegrationError(f"Invalid {label}")
    return number


def minutes(value):
    parts = str(value).split(":")
    if len(parts) not in (1, 2):
        raise EngineIntegrationError("Invalid time")
    hour = integer(parts[0], "hour")
    minute = integer(parts[1], "minute") if len(parts) == 2 else 0
    if hour > 24 or minute > 59 or (hour == 24 and minute):
        raise EngineIntegrationError("Invalid time")
    return hour * 60 + minute


def csv_slots(value):
    result = []
    for occurrence in value.split(";"):
        parts = occurrence.strip().split("-")
        if len(parts) != 3:
            raise EngineIntegrationError("Invalid persisted request timeData")
        day, start, end = integer(parts[0], "day"), minutes(parts[1]), minutes(parts[2])
        if not 1 <= day <= 7 or not 0 <= start < end <= 1440:
            raise EngineIntegrationError("Invalid persisted time range")
        result.append({"day": day, "startMinutes": start, "endMinutes": end})
    return result


def csv_bool(value, default=False):
    value = (value or "").strip().lower()
    if not value:
        return default
    if value in ("1", "true"):
        return True
    if value in ("0", "false"):
        return False
    raise EngineIntegrationError("Invalid persisted boolean")


def execution_snapshot(adapter, strategy):
    """Translate explicit offline CSV inputs into DTOs; normal runs snapshot PostgreSQL."""
    def rows(name):
        return adapter.read_csv_table(name)["rows"]
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
                "slots": csv_slots(row.get("timeData") or "")}
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


def validate_result(result, snapshot):
    def require(condition, message):
        if not condition:
            raise EngineIntegrationError("Invalid engine response: " + message)
    def number(value, minimum=0):
        return type(value) is int and minimum <= value <= 2147483647
    def valid_slot(slot):
        return (isinstance(slot, dict) and number(slot.get("day"), 1) and slot["day"] <= 7
                and number(slot.get("startMinutes")) and number(slot.get("endMinutes"), 1)
                and slot["startMinutes"] < slot["endMinutes"] <= 1440)
    require(isinstance(result, dict), "expected an object")
    require(type(result.get("protocolVersion")) is int and result["protocolVersion"] == PROTOCOL_VERSION, "protocolVersion")
    require(result.get("runId") == snapshot["runId"], "runId mismatch")
    require(result.get("strategy") == snapshot["strategy"], "strategy mismatch")
    require(isinstance(result.get("engineVersion"), str) and result["engineVersion"], "engineVersion")
    require(result.get("status") in ("success", "error"), "status")
    for key in ("requestResults", "allocations", "suggestions", "errors"):
        require(isinstance(result.get(key), list), key)
    for error in result["errors"]:
        require(isinstance(error, dict) and all(isinstance(error.get(key), str) for key in ("code", "message")), "error entry")
    if result["status"] == "error":
        require(bool(result["errors"]), "missing error details")
        return result
    require(not result["errors"], "success with errors")
    expected = {item["id"]: item for item in snapshot["requests"]}
    spaces = {item["id"]: item for item in snapshot["spaces"]}
    decisions = {}
    for item in result["requestResults"]:
        require(isinstance(item, dict), "request decision")
        rid = item.get("requestId")
        require(number(rid) and rid in expected and rid not in decisions, "requestId")
        require(item.get("status") in ("Approved", "Rejected"), "decision status")
        require(item.get("requestType") == expected[rid]["type"], "request type")
        for key in ("title", "purpose", "requesterName", "requesterRole", "reasonCode", "rejectionReason"):
            require(isinstance(item.get(key), str), key)
        require(number(item.get("priority")) and isinstance(item.get("history"), list)
                and all(isinstance(event, str) for event in item["history"]), "priority/history")
        for key in ("requesterId", "participantCount", "requestedSpaceId", "allocationCount"):
            require(number(item.get(key)), key)
        require(type(item.get("assignedParticipants")) is int and item["assignedParticipants"] >= 0, "assignedParticipants")
        for key in ("allocationIds", "allocatedSpaceIds"):
            require(isinstance(item.get(key), list) and all(number(value) for value in item[key]), key)
        require(isinstance(item.get("slots"), list) and all(valid_slot(value) for value in item["slots"]), "requested slots")
        require(isinstance(item.get("participants"), list) and isinstance(item.get("exam"), dict), "request-specific metadata")
        for participant in item["participants"]:
            require(isinstance(participant, dict) and number(participant.get("userId"))
                    and isinstance(participant.get("role", ""), str), "participant metadata")
        decisions[rid] = item
    require(set(decisions) == set(expected), "incomplete request decisions")
    allocation_ids = set()
    for item in result["allocations"]:
        require(isinstance(item, dict), "allocation")
        rid, sid, aid = item.get("requestId"), item.get("spaceId"), item.get("allocationId")
        require(number(rid) and rid in decisions and decisions[rid]["status"] == "Approved", "allocated request")
        require(number(sid) and sid in spaces and number(aid) and aid not in allocation_ids, "allocation identifiers")
        allocation_ids.add(aid)
        require(valid_slot(item.get("slot")) and number(item.get("assignedParticipants"), 1)
                and number(item.get("spaceCapacity"), 1), "allocation time/capacity")
        for key in ("spaceName", "spaceType", "building"):
            require(isinstance(item.get(key), str), key)
        require(isinstance(item.get("requiredParticipantIds"), list)
                and all(number(pid) for pid in item["requiredParticipantIds"]), "requiredParticipantIds")
    suggested = set()
    for group in result["suggestions"]:
        require(isinstance(group, dict), "suggestion group")
        rid = group.get("requestId")
        require(number(rid) and rid in expected and rid not in suggested and expected[rid]["type"] == "CommitteeMeeting"
                and decisions[rid]["status"] == "Rejected", "suggested request")
        suggested.add(rid)
        require(isinstance(group.get("items"), list), "suggestion items")
        for item in group["items"]:
            require(isinstance(item, dict) and number(item.get("spaceId")) and item["spaceId"] in spaces
                    and valid_slot(item.get("slot")) and isinstance(item.get("reason"), str), "suggestion")
            require(all(number(item.get(key)) for key in ("score", "timeDistanceMinutes", "dayDistance", "conflictCount")), "suggestion scores")
    return result


class EngineGateway:
    def __init__(self, project_root, timeout=30, logger=None):
        self.project_root, self.timeout, self.logger = project_root, timeout, logger

    def execute(self, snapshot):
        backend = resolve_backend_executable(self.project_root, os.environ.get("RESOURCE_ALLOCATION_BACKEND"))
        if self.logger:
            self.logger.info("Executing JSON backend %s (built=%s source=%s binary=%s compiler=%s run=%s)",
                             backend.path, backend.metadata["built_at"], backend.metadata["source_sha256"],
                             backend.metadata["binary_sha256"], backend.metadata["compiler"], snapshot["runId"])
        try:
            completed = subprocess.run([str(backend.path), "--json"], input=json.dumps(snapshot, ensure_ascii=False, allow_nan=False),
                                       encoding="utf-8", capture_output=True, timeout=self.timeout, cwd=self.project_root)
        except subprocess.TimeoutExpired as error:
            raise EngineIntegrationError(f"Backend execution timed out after {self.timeout} seconds. Previous results remain active.") from error
        except (OSError, UnicodeError, ValueError) as error:
            raise EngineIntegrationError(f"Configured backend could not start or communicate: {error}") from error
        if completed.stderr and self.logger:
            self.logger.info("Engine diagnostics run=%s: %s", snapshot["runId"], completed.stderr[:5000])
        try:
            result = json.loads(completed.stdout)
        except (ValueError, TypeError) as error:
            raise EngineIntegrationError(f"Backend exit {completed.returncode}: malformed JSON stdout") from error
        # Nonzero exits are never publication candidates, even with well-formed output.
        if completed.returncode != 0:
            detail = result.get("errors", []) if isinstance(result, dict) else []
            raise EngineIntegrationError(f"Backend failed with exit code {completed.returncode}: {detail}")
        validate_result(result, snapshot)
        if result["status"] != "success":
            raise EngineIntegrationError(f"Backend reported error with zero exit code: {result['errors']}")
        return result, backend.metadata
