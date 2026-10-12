"""Database-backed presentation views. Compatibility names are not file paths."""

try:
    from .backend_result_adapter import BackendResultAdapter
    from .engine_result_projection import clock, result_tables, time_data
    from .result_table_schema import OUTPUT_HEADERS
except ImportError:
    from backend_result_adapter import BackendResultAdapter
    from engine_result_projection import clock, result_tables, time_data
    from result_table_schema import OUTPUT_HEADERS


INPUT_HEADERS = {
    "users.csv": "userId,name,role,email,status,primaryUnit,assignedRoles,studentNo,program,yearLevel,title,officeRoom,assistantType,jobTitle,adminLevel",
    "spaces.csv": "spaceId,type,name,capacity,hasProjector,hasWhiteboard,hasComputers,isAvailable,building",
    "requests.csv": "requestId,requestType,userId,spaceId,participantCount,requiredFeature,requiredBuilding,timeData,title,purpose,courseCode,courseName,examType,canSplitAcrossRooms",
    "request_participants.csv": "requestId,userId,participantRole",
    "user_busy_slots.csv": "userId,day,startTime,endTime,reason",
}


def input_tables(snapshot):
    rows = {name: [] for name in INPUT_HEADERS}
    for user in snapshot["users"]:
        rows["users.csv"].append(dict(user, userId=user["id"], assignedRoles="|".join(user.get("assignedRoles", []))))
    for space in snapshot["spaces"]:
        rows["spaces.csv"].append(dict(space, spaceId=space["id"], isAvailable=space["available"],
                                      **{"has" + key.title(): value for key, value in space["features"].items()}))
    for item in snapshot["requests"]:
        rows["requests.csv"].append(dict(item, **item.get("exam", {}), requestId=item["id"], requestType=item["type"],
                                        userId=item["requesterId"], spaceId=item["spaceId"], timeData=time_data(item["slots"])))
        for participant in item.get("participants", []):
            rows["request_participants.csv"].append(dict(requestId=item["id"], userId=participant["userId"],
                                                       participantRole=participant.get("role") or "Participant"))
    for item in snapshot["busySlots"]:
        slot = item["slot"]
        rows["user_busy_slots.csv"].append(dict(userId=item["userId"], day=slot["day"], startTime=clock(slot["startMinutes"]),
                                               endTime=clock(slot["endMinutes"]), reason=item["reason"]))
    def scalar(value):
        return str(value).lower() if type(value) is bool else str(value)
    return {name: {"exists": True, "headers": headers.split(","), "message": "",
                   "rows": [{key: scalar(row.get(key, "")) for key in headers.split(",")} for row in rows[name]]}
            for name, headers in INPUT_HEADERS.items()}


class DatabaseResultAdapter(BackendResultAdapter):
    """Reuse UI formatting while pinning one immutable, repeatable-read DB view."""

    def __init__(self, repository, raw_data_files):
        snapshot, document, self.run_id = repository.read_view()
        self.raw_data_files = list(raw_data_files)
        self._tables = input_tables(snapshot)
        self._texts = {"config.txt": {"exists": True, "message": "", "content": "allocation_strategy=" + snapshot["strategy"]}}
        self.strategy = snapshot["strategy"]
        self.engine_result = document["result"] if document else None
        self._tables.update({name: {"exists": False, "headers": headers.split(","), "rows": [],
                                   "message": "Allocation has not been run yet."} for name, headers in OUTPUT_HEADERS.items()})
        if document:
            self._tables.update(result_tables(document["snapshot"], document["result"]))

    def pin(self, state=None):
        return self

    def read_csv_table(self, filename):
        return self._tables[filename]

    def read_text_file(self, filename):
        return self._texts[filename]
