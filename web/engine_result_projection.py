"""In-memory compatibility tables for existing templates; never writes CSV outputs."""

try:
    from .shared_file_state import OUTPUT_HEADERS
except ImportError:
    from shared_file_state import OUTPUT_HEADERS


def clock(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def time_data(slots):
    return ";".join(f"{slot['day']}-{clock(slot['startMinutes'])}-{clock(slot['endMinutes'])}" for slot in slots)


def result_tables(snapshot, result):
    rows = {name: [] for name in OUTPUT_HEADERS}
    requests = {item["id"]: item for item in snapshot["requests"]}
    spaces = {item["id"]: item for item in snapshot["spaces"]}
    decisions = {item["requestId"]: item for item in result["requestResults"]}
    for allocation in result["allocations"]:
        slot = allocation["slot"]
        row = {key: allocation[key] for key in ("allocationId", "requestId", "spaceId", "spaceName", "spaceType", "building", "assignedParticipants")}
        row.update(day=slot["day"], startHour=clock(slot["startMinutes"]), endHour=clock(slot["endMinutes"]))
        rows["allocations.csv"].append(row)
        decision = decisions[allocation["requestId"]]
        rows["allocation_summaries.csv"].append(dict(row, requestTitle=decision["title"], requestPurpose=decision["purpose"],
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
        rows["request_results.csv"].append(row)
        assigned = [item for item in result["allocations"] if item["requestId"] == rid]
        rows["request_summaries.csv"].append(dict(row, requiredParticipants=participants,
            assignedParticipants=decision["assignedParticipants"], allocationCount=decision["allocationCount"],
            allocatedSpaces=" | ".join(item["spaceName"] for item in assigned),
            summaryText=decision["rejectionReason"] if decision["status"] == "Rejected" else f"Approved: {len(assigned)} allocation(s)."))
    def scalar(value):
        return str(value).lower() if type(value) is bool else str(value)
    return {name: {"exists": True, "headers": headers.split(","), "message": "",
                   "rows": [{key: scalar(row.get(key, "")) for key in headers.split(",")} for row in rows[name]]}
            for name, headers in OUTPUT_HEADERS.items()}


def suggestion_display(group):
    return {"heading": "Suggested least-change alternative times", "raw": "", "items": [
        f"{('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')[item['slot']['day'] - 1]} "
        f"{clock(item['slot']['startMinutes'])}-{clock(item['slot']['endMinutes'])} in space {item['spaceId']} "
        f"(distance: {item['timeDistanceMinutes']} minutes)" for item in group["items"]],
        "empty_message": "" if group["items"] else "No available alternative time found."}
