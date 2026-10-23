"""Versioned stdin/stdout boundary. No application persistence or allocation decisions."""

import json
import os
import subprocess

from .backend_executable import resolve_backend_executable


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
        return self._execute(snapshot, "--json", validate_result)

    def execute_appointment(self, snapshot):
        return self._execute(snapshot, "--appointments-json", validate_appointment_result)

    def execute_room(self, snapshot):
        return self._execute(snapshot, "--rooms-json", validate_room_result)

    def execute_equipment(self, snapshot):
        return self._execute(snapshot, "--equipment-json", validate_equipment_result)

    def execute_room_series(self, snapshot):
        return self._execute(snapshot, "--room-series-json", validate_room_series_result)

    def execute_equipment_series(self, snapshot):
        return self._execute(snapshot, "--equipment-series-json", validate_equipment_series_result)

    def _execute(self, snapshot, mode, validator):
        backend = resolve_backend_executable(self.project_root, os.environ.get("RESOURCE_ALLOCATION_BACKEND"))
        if self.logger:
            self.logger.info("Executing JSON backend %s (built=%s source=%s binary=%s compiler=%s run=%s)",
                             backend.path, backend.metadata["built_at"], backend.metadata["source_sha256"],
                             backend.metadata["binary_sha256"], backend.metadata["compiler"], snapshot["runId"])
        try:
            completed = subprocess.run([str(backend.path), mode], input=json.dumps(snapshot, ensure_ascii=False, allow_nan=False),
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
        validator(result, snapshot)
        if result["status"] != "success":
            raise EngineIntegrationError(f"Backend reported error with zero exit code: {result['errors']}")
        return result, backend.metadata


def _valid_operation_header(result, snapshot, operation):
    return (isinstance(result, dict) and type(result.get('protocolVersion')) is int
            and result['protocolVersion'] == 1 and result.get('operation') == operation
            and result.get('runId') == snapshot['runId'] and result.get('status') == 'success'
            and isinstance(result.get('engineVersion'), str) and bool(result['engineVersion'])
            and type(result.get('feasible')) is bool and result.get('errors') == [])


def _series_header(result, snapshot, operation):
    if not (_valid_operation_header(result, snapshot, operation) and isinstance(result.get('occurrences'),list)
        and len(result['occurrences'])==len(snapshot['occurrences']) and 1<=len(result['occurrences'])<=366):
        raise EngineIntegrationError('Invalid recurring reservation engine response.')


def _series_children(result, snapshot, operation, validator):
    for row,period in zip(result['occurrences'],snapshot['occurrences']):
        if not isinstance(row,dict) or any(type(row.get(k)) is not int or row[k]!=period[k] for k in ('start','end')):
            raise EngineIntegrationError('Engine occurrence dates do not match the complete requested series.')
        child={**row,'protocolVersion':1,'operation':operation,'runId':snapshot['runId'],
               'engineVersion':result['engineVersion'],'status':'success','errors':[]}
        validator(child,{**snapshot,'proposed':period})


def validate_room_series_result(result, snapshot):
    _series_header(result,snapshot,'studentRoomSeries')
    validate_room_result({**result,'operation':'studentRoom'},snapshot)
    _series_children(result,snapshot,'studentRoom',validate_room_result)
    all_feasible=all(row['feasible'] for row in result['occurrences'])
    if (result['feasible'] and not all_feasible) or (snapshot['action']=='attendance' and result['feasible']!=all_feasible):
        raise EngineIntegrationError('Room series feasibility disagrees with its dated occurrences.')
    for row in result['alternatives']:
        offset=row.get('offsetMinutes')
        if type(offset) is not int or not 0<abs(offset)<=120 or row['start']!=snapshot['proposed']['start']+offset*60:
            raise EngineIntegrationError('Invalid alternative recurring time.')
    return result


def validate_equipment_series_result(result, snapshot):
    _series_header(result,snapshot,'equipmentSeries')
    _series_children(result,snapshot,'equipment',validate_equipment_result)
    if result.get('items')!=[] or result.get('alternativePeriods')!=[] or result['feasible']!=all(row['feasible'] for row in result['occurrences']):
        raise EngineIntegrationError('Equipment series must report all occurrence decisions without an ambiguous single-period assignment.')
    return result


def validate_equipment_result(result, snapshot):
    def require(condition):
        if not condition:
            raise EngineIntegrationError('Invalid equipment engine response.')
    require(_valid_operation_header(result, snapshot, 'equipment'))
    needs = {item['typeId']: item for item in snapshot['items']}
    types = {item['id']: item for item in snapshot['types']}
    units = {item['id']: item for item in snapshot['units']}
    require(isinstance(result.get('items'), list) and len(result['items']) == len(needs))
    seen, selected = set(), set()
    for row in result['items']:
        require(isinstance(row, dict) and type(row.get('typeId')) is int and row['typeId'] in needs and row['typeId'] not in seen)
        key = row['typeId']
        seen.add(key)
        require(type(row.get('availableQuantity')) is int and 0 <= row['availableQuantity'] <= len(units)
                and row.get('reasonCode') in {'AVAILABLE', 'INELIGIBLE', 'NO_CUSTODIAN', 'INSUFFICIENT_QUANTITY'}
                and isinstance(row.get('unitIds'), list) and isinstance(row.get('alternativeTypeIds'), list))
        require(row['reasonCode'] != 'AVAILABLE' or row['availableQuantity'] >= needs[key]['quantity'])
        require(len(row['unitIds']) == (needs[key]['quantity'] if result['feasible'] else 0))
        for uid in row['unitIds']:
            require(type(uid) is int and uid in units and units[uid]['typeId'] == key and uid not in selected)
            selected.add(uid)
        require(all(type(t) is int and t in types and t != key for t in row['alternativeTypeIds']))
    require(result['feasible'] == all(row['reasonCode'] == 'AVAILABLE' for row in result['items']))
    require(isinstance(result.get('alternativePeriods'), list) and len(result['alternativePeriods']) <= 3)
    for period in result['alternativePeriods']:
        require(isinstance(period, dict) and all(type(period.get(k)) is int for k in ('start', 'end'))
                and period['start'] > snapshot['proposed']['start'] and period['end'] <= 4102444800
                and period['end'] - period['start'] == snapshot['proposed']['end'] - snapshot['proposed']['start'])
    return result


def validate_room_result(result, snapshot):
    def require(condition):
        if not condition:
            raise EngineIntegrationError('Invalid room-selection engine response.')
    def number(value, minimum=0):
        return type(value) is int and minimum <= value <= 2147483647
    require(_valid_operation_header(result, snapshot, 'studentRoom') and result.get('reasonCode') in
            {'AVAILABLE', 'NO_ELIGIBLE_ROOM', 'ORGANIZER_BUSY', 'UNRESOLVED_CALENDAR'})
    rooms = {row['id']: row for row in snapshot['rooms']}
    for key in ('candidates', 'alternatives'):
        require(isinstance(result.get(key), list) and len(result[key]) <= (20 if key == 'candidates' else 5))
        seen = set()
        for row in result[key]:
            require(isinstance(row, dict) and number(row.get('roomId'), 1) and row['roomId'] in rooms)
            space = rooms[row['roomId']]
            require(number(row.get('facultyId'), 1) and row['facultyId'] == space['facultyId']
                    and number(row.get('capacity'), 1) and row['capacity'] == space['capacity']
                    and number(row.get('spareSeats')) and row['spareSeats'] == space['capacity'] - snapshot['attendeeCount']
                    and number(row.get('extraFacilities')) and row['extraFacilities'] <= 3
                    and number(row.get('preferencePenalty')) and row['preferencePenalty'] <= 2
                    and isinstance(row.get('reason'), str) and row['reason'])
            require(type(row.get('start')) is int and type(row.get('end')) is int
                    and snapshot['horizon']['start'] <= row['start'] < row['end'] <= snapshot['horizon']['end']
                    and row['end'] - row['start'] == snapshot['proposed']['end'] - snapshot['proposed']['start'])
            if key == 'candidates':
                require(row['start'] == snapshot['proposed']['start'] and row['end'] == snapshot['proposed']['end'])
                if snapshot['action'] == 'validate':
                    require(row['roomId'] == snapshot['selectedRoomId'])
            else:
                require(row['start'] != snapshot['proposed']['start'])
            identity = (row['roomId'], row['start'], row['end'])
            require(identity not in seen)
            seen.add(identity)
    require(isinstance(result.get('explanations'), list) and all(isinstance(row, str) for row in result['explanations']))
    require(result['feasible'] == (result['reasonCode'] == 'AVAILABLE'))
    if snapshot['action'] != 'attendance':
        require(result['feasible'] == bool(result['candidates']))
    else:
        require(not result['candidates'] and not result['alternatives'])
    return result


def validate_appointment_result(result, snapshot):
    def require(condition):
        if not condition:
            raise EngineIntegrationError("Invalid appointment engine response.")
    require(_valid_operation_header(result, snapshot, 'appointment') and result.get("reasonCode") in {
                "AVAILABLE", "NO_FEASIBLE_TIME", "UNRESOLVED_CALENDAR", "OUTSIDE_PUBLISHED_AVAILABILITY",
                "REQUIRED_PARTICIPANT_BUSY", "ORGANIZER_BUSY", "INVALID_INTERVAL"}
            and isinstance(result.get("recommendations"), list))
    require(result["feasible"] == (result["reasonCode"] == "AVAILABLE"))
    people = set(snapshot["invitedIds"])
    for item in result["recommendations"]:
        require(isinstance(item, dict) and type(item.get("start")) is int and type(item.get("end")) is int
                and snapshot["horizon"]["start"] <= item["start"] < item["end"] <= snapshot["horizon"]["end"]
                and item["end"] - item["start"] == snapshot["durationMinutes"] * 60
                and isinstance(item.get("reason"), str)
                and type(item.get("preferenceDistanceSeconds")) is int and item["preferenceDistanceSeconds"] >= 0)
        groups = [item.get(key) for key in ("availableInvitees", "unavailableInvitees", "unresolvedInvitees")]
        require(all(isinstance(group, list) and all(type(pid) is int for pid in group) for group in groups))
        combined = [pid for group in groups for pid in group]
        require(len(combined) == len(set(combined)) and set(combined) == people)
    require(result["feasible"] == bool(result["recommendations"]))
    if snapshot["action"] == "validate" and result["feasible"]:
        require(len(result["recommendations"]) == 1 and all(result["recommendations"][0][key] == snapshot["proposed"][key] for key in ("start", "end")))
    return result
