"""Project structured input/results into file-free presentation tables."""

from .result_table_schema import INPUT_HEADERS, OUTPUT_HEADERS, table_view


def clock(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def time_data(slots):
    return ";".join(f"{slot['day']}-{clock(slot['startMinutes'])}-{clock(slot['endMinutes'])}" for slot in slots)


def input_tables(snapshot):
    rows = {name: [] for name in INPUT_HEADERS}
    for user in snapshot["users"]:
        rows["users"].append(dict(user, userId=user["id"], assignedRoles="|".join(user.get("assignedRoles", []))))
    for space in snapshot["spaces"]:
        rows["spaces"].append(dict(space, spaceId=space["id"], isAvailable=space["available"],
                                      **{"has" + key.title(): value for key, value in space["features"].items()}))
    for item in snapshot["requests"]:
        rows["requests"].append(dict(item, **item.get("exam", {}), requestId=item["id"], requestType=item["type"],
                                        userId=item["requesterId"], spaceId=item["spaceId"], timeData=time_data(item["slots"])))
        for participant in item.get("participants", []):
            rows["request_participants"].append(dict(requestId=item["id"], userId=participant["userId"],
                                                       participantRole=participant.get("role") or "Participant"))
    for item in snapshot["busySlots"]:
        slot = item["slot"]
        rows["user_busy_slots"].append(dict(userId=item["userId"], day=slot["day"], startTime=clock(slot["startMinutes"]),
                                               endTime=clock(slot["endMinutes"]), reason=item["reason"]))
    return {name: table_view(headers, rows[name]) for name, headers in INPUT_HEADERS.items()}


def result_tables(snapshot, result):
    rows = {name: [] for name in OUTPUT_HEADERS}
    requests = {item["id"]: item for item in snapshot["requests"]}
    spaces = {item["id"]: item for item in snapshot["spaces"]}
    decisions = {item["requestId"]: item for item in result["requestResults"]}
    for allocation in result["allocations"]:
        slot = allocation["slot"]
        row = {key: allocation[key] for key in ("allocationId", "requestId", "spaceId", "spaceName", "spaceType", "building", "assignedParticipants")}
        row.update(day=slot["day"], startHour=clock(slot["startMinutes"]), endHour=clock(slot["endMinutes"]))
        rows["allocations"].append(row)
        decision = decisions[allocation["requestId"]]
        rows["allocation_summaries"].append(dict(row, requestTitle=decision["title"], requestPurpose=decision["purpose"],
            requestType=decision["requestType"], startTime=row["startHour"], endTime=row["endHour"], spaceCapacity=allocation["spaceCapacity"]))
    for decision in result["requestResults"]:
        rid = decision["requestId"]
        request = requests[rid]
        space = spaces[request["spaceId"]]
        exam = request.get("exam", {})
        participants = " | ".join(f"{item['userId']}:{item.get('role') or 'Participant'}" for item in request.get("participants", []))
        row = dict(decision, **exam, committeeParticipants=participants, participants=request["participantCount"],
                   spaceName=space["name"], spaceType=space["type"], spaceBuilding=space.get("building", ""),
                   requiredBuilding=request.get("requiredBuilding", ""), requiredFeature=request.get("requiredFeature", ""),
                   timeInfo=time_data(request["slots"]), lifecycleHistory=" | ".join(decision["history"]))
        rows["request_results"].append(row)
        assigned = [item for item in result["allocations"] if item["requestId"] == rid]
        rows["request_summaries"].append(dict(row, requiredParticipants=participants,
            assignedParticipants=decision["assignedParticipants"], allocationCount=decision["allocationCount"],
            allocatedSpaces=" | ".join(item["spaceName"] for item in assigned),
            summaryText=decision["rejectionReason"] if decision["status"] == "Rejected" else f"Approved: {len(assigned)} allocation(s)."))
    return {name: table_view(headers, rows[name]) for name, headers in OUTPUT_HEADERS.items()}


def suggestion_display(group):
    return {"heading": "Suggested least-change alternative times", "raw": "", "items": [
        f"{('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')[item['slot']['day'] - 1]} "
        f"{clock(item['slot']['startMinutes'])}-{clock(item['slot']['endMinutes'])} in space {item['spaceId']} "
        f"(distance: {item['timeDistanceMinutes']} minutes)" for item in group["items"]],
        "empty_message": "" if group["items"] else "No available alternative time found."}
