"""Shared domain-record validation for database saves and explicit imports."""

from .models import REQUEST_TYPES, ROLES, SPACE_TYPES
from .repository import PersistenceError


class DataValidationError(PersistenceError):
    pass


def require(condition, message):
    if not condition:
        raise DataValidationError(message)


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
