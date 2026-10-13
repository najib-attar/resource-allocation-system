"""Versioned stdin/stdout boundary. No application persistence or allocation decisions."""

import json
import os
import subprocess

try:
    from .backend_executable import resolve_backend_executable
except ImportError:
    from backend_executable import resolve_backend_executable


PROTOCOL_VERSION = 1


class EngineIntegrationError(RuntimeError):
    pass


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
