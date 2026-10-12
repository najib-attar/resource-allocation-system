"""Database reads/writes and domain DTO mapping, without allocation algorithms."""

import uuid
from collections import defaultdict

from sqlalchemy import func, select, text, update

from .models import ApplicationState, BusySlot, ExamDetails, OrganizationUnit, RequestHistory, RequestParticipant, RequestSlot, Resource, ResourceRequest, Role, User, UserRole
from .models import Allocation, AllocationParticipant, AllocationRun, MeetingSuggestion, RequestDecision, SuggestionGroup
try:
    from ..engine_gateway import validate_result
except ImportError:
    from engine_gateway import validate_result


class PersistenceError(RuntimeError):
    pass


class StaleRun(PersistenceError):
    pass


def validate_publication(result, snapshot):
    """Verify duplicated result projections agree; do not repeat scheduling rules."""
    validate_result(result, snapshot)
    if result["status"] != "success":
        raise PersistenceError("Cannot publish an unsuccessful engine result.")
    by_request = defaultdict(list)
    spaces = {item["id"]: item for item in snapshot["spaces"]}
    for item in result["allocations"]:
        space = spaces[item["spaceId"]]
        if any(item[key] != space[source] for key, source in
               (("spaceName", "name"), ("spaceType", "type"), ("building", "building"), ("spaceCapacity", "capacity"))):
            raise PersistenceError("Engine resource metadata disagrees with its input snapshot.")
        by_request[item["requestId"]].append(item)
    for decision in result["requestResults"]:
        allocations = by_request[decision["requestId"]]
        if (decision["allocationCount"] != len(allocations)
                or decision["allocationIds"] != [item["allocationId"] for item in allocations]
                or decision["allocatedSpaceIds"] != [item["spaceId"] for item in allocations]
                or decision["assignedParticipants"] != sum(item["assignedParticipants"] for item in allocations)
                or (decision["status"] == "Approved") != bool(allocations)):
            raise PersistenceError("Engine allocation summary disagrees with its allocation rows.")


PROFILE_FIELDS = {"email": "email", "status": "status", "studentNo": "student_no", "program": "program",
                  "yearLevel": "year_level", "title": "title", "officeRoom": "office_room",
                  "assistantType": "assistant_type", "jobTitle": "job_title", "adminLevel": "admin_level"}


def state_row(session, lock=False):
    query = select(ApplicationState).where(ApplicationState.id == 1)
    if lock:
        query = query.with_for_update()
    state = session.scalar(query)
    if state is None:
        raise PersistenceError("Database is not initialized; run Alembic migrations before using the application.")
    return state


def slot_dict(item):
    return {"day": item.day, "startMinutes": item.start_minutes, "endMinutes": item.end_minutes}


def snapshot_from_session(session, strategy, run_id=None):
    roles = {item.id: item.name for item in session.scalars(select(Role))}
    units = {item.id: item.name for item in session.scalars(select(OrganizationUnit))}
    assignments = defaultdict(list)
    for item in session.scalars(select(UserRole).order_by(UserRole.user_id, UserRole.ordinal)):
        assignments[item.user_id].append(roles[item.role_id])
    users = []
    for item in session.scalars(select(User).order_by(User.source_order)):
        users.append({"id": item.id, "name": item.name, "role": roles[item.primary_role_id],
                      "primaryUnit": units.get(item.primary_unit_id, ""), "assignedRoles": assignments[item.id],
                      **{key: getattr(item, column) for key, column in PROFILE_FIELDS.items()}})
    resources = [{"id": item.id, "name": item.name, "type": item.type, "capacity": item.capacity,
                  "building": item.building, "available": item.available,
                  "features": {key: getattr(item, key) for key in ("projector", "whiteboard", "computers")}}
                 for item in session.scalars(select(Resource).order_by(Resource.source_order))]
    slots, participants = defaultdict(list), defaultdict(list)
    for item in session.scalars(select(RequestSlot).order_by(RequestSlot.request_id, RequestSlot.ordinal)):
        slots[item.request_id].append(slot_dict(item))
    for item in session.scalars(select(RequestParticipant).order_by(RequestParticipant.request_id, RequestParticipant.ordinal)):
        participants[item.request_id].append({"userId": item.user_id, "role": item.role})
    exams = {item.request_id: item for item in session.scalars(select(ExamDetails))}
    requests = []
    for item in session.scalars(select(ResourceRequest).order_by(ResourceRequest.submission_order)):
        request = {"id": item.id, "type": item.type, "requesterId": item.requester_id, "spaceId": item.resource_id,
                   "participantCount": item.participant_count, "title": item.title, "purpose": item.purpose,
                   "requiredFeature": item.required_feature, "requiredBuilding": item.required_building,
                   "slots": slots[item.id]}
        if item.type == "Exam":
            exam = exams.get(item.id)
            if exam is None:
                raise PersistenceError(f"Exam request {item.id} is missing its exam metadata.")
            request["exam"] = {"courseCode": exam.course_code, "courseName": exam.course_name,
                               "examType": exam.exam_type, "canSplitAcrossRooms": exam.can_split}
        if item.type == "CommitteeMeeting":
            request["participants"] = participants[item.id]
        requests.append(request)
    busy = [{"userId": item.user_id, "reason": item.reason, "slot": slot_dict(item)}
            for item in session.scalars(select(BusySlot).order_by(BusySlot.source_order))]
    return {"protocolVersion": 1, "runId": run_id or uuid.uuid4().hex, "strategy": strategy,
            "users": users, "spaces": resources, "busySlots": busy, "requests": requests}


def insert_request(session, request, explicit_order=None):
    record = ResourceRequest(type=request["type"], requester_id=request["requesterId"],
                             resource_id=request["spaceId"], participant_count=request["participantCount"],
                             title=request.get("title", ""), purpose=request.get("purpose", ""),
                             required_feature=request.get("requiredFeature", ""), required_building=request.get("requiredBuilding", ""))
    if "id" in request:
        record.id = request["id"]
    if explicit_order is not None:
        record.submission_order = explicit_order
    session.add(record)
    session.flush()
    for ordinal, slot in enumerate(request["slots"], 1):
        session.add(RequestSlot(request_id=record.id, ordinal=ordinal, day=slot["day"],
                                start_minutes=slot["startMinutes"], end_minutes=slot["endMinutes"]))
    for ordinal, participant in enumerate(request.get("participants", []), 1):
        session.add(RequestParticipant(request_id=record.id, user_id=participant["userId"], ordinal=ordinal,
                                       role=participant.get("role") or "Participant"))
    if request["type"] == "Exam":
        exam = request["exam"]
        session.add(ExamDetails(request_id=record.id, course_code=exam.get("courseCode", ""),
                                course_name=exam.get("courseName", ""), exam_type=exam.get("examType", ""),
                                can_split=exam["canSplitAcrossRooms"]))
    return record


class Repository:
    def __init__(self, database):
        self.database = database

    def snapshot(self):
        with self.database.transaction(read_only=True) as session:
            state = state_row(session)
            return snapshot_from_session(session, state.strategy)

    def save_request(self, request):
        from .importer import validate_request
        with self.database.transaction() as session:
            state = state_row(session, lock=True)
            users = set(session.scalars(select(User.id)))
            resources = set(session.scalars(select(Resource.id)))
            validate_request(request, users, resources)
            record = insert_request(session, request)
            session.add(RequestHistory(request_id=record.id, kind="saved", message="Request saved; pending allocation."))
            state.input_revision += 1
            session.flush()
            return record.id

    def set_strategy(self, strategy):
        from .models import STRATEGIES
        if strategy not in STRATEGIES:
            raise PersistenceError("Unknown allocation strategy.")
        with self.database.transaction() as session:
            state = state_row(session, lock=True)
            if state.strategy != strategy:
                state.strategy = strategy
                state.input_revision += 1

    def start_run(self):
        with self.database.transaction() as session:
            state = state_row(session, lock=True)
            snapshot = snapshot_from_session(session, state.strategy)
            run = AllocationRun(correlation_id=snapshot["runId"], input_revision=state.input_revision,
                                strategy=state.strategy, snapshot=snapshot)
            session.add(run)
            session.flush()
            return run.id, snapshot

    def fail_run(self, run_id, message, superseded=False):
        with self.database.transaction() as session:
            session.execute(update(AllocationRun).where(AllocationRun.id == run_id, AllocationRun.status == "running")
                            .values(status="superseded" if superseded else "failed", error=message))

    def publish_run(self, run_id, result, build):
        with self.database.transaction() as session:
            state = state_row(session, lock=True)
            run = session.get(AllocationRun, run_id)
            if run is None or run.status != "running":
                raise PersistenceError("Allocation run is missing or already completed.")
            if state.input_revision != run.input_revision:
                raise StaleRun("Inputs changed during allocation. Saved requests remain pending; retry allocation. Previous results remain active.")
            if state.active_run_id is not None and state.active_run_id > run.id:
                raise StaleRun("A newer allocation run is already active. This older run was not published.")
            validate_publication(result, run.snapshot)
            for ordinal, item in enumerate(result["requestResults"], 1):
                session.add(RequestDecision(run_id=run.id, request_id=item["requestId"], ordinal=ordinal,
                                            status=item["status"], reason=item["rejectionReason"], payload=item))
                session.add(RequestHistory(request_id=item["requestId"], run_id=run.id, kind="decision",
                                           message=item["status"] + (": " + item["rejectionReason"] if item["rejectionReason"] else "")))
            session.flush()
            for item in result["allocations"]:
                slot = item["slot"]
                allocation = Allocation(run_id=run.id, request_id=item["requestId"], engine_id=item["allocationId"],
                                        resource_id=item["spaceId"], day=slot["day"], start_minutes=slot["startMinutes"],
                                        end_minutes=slot["endMinutes"], assigned_participants=item["assignedParticipants"])
                session.add(allocation)
                session.flush()
                for ordinal, uid in enumerate(item["requiredParticipantIds"], 1):
                    session.add(AllocationParticipant(allocation_id=allocation.id, user_id=uid, ordinal=ordinal))
            for ordinal, group in enumerate(result["suggestions"], 1):
                session.add(SuggestionGroup(run_id=run.id, request_id=group["requestId"], ordinal=ordinal))
            session.flush()
            for group in result["suggestions"]:
                for rank, item in enumerate(group["items"], 1):
                    slot = item["slot"]
                    session.add(MeetingSuggestion(run_id=run.id, request_id=group["requestId"], rank=rank,
                                                   resource_id=item["spaceId"], day=slot["day"], start_minutes=slot["startMinutes"],
                                                   end_minutes=slot["endMinutes"], score=item["score"], time_distance=item["timeDistanceMinutes"],
                                                   day_distance=item["dayDistance"], conflict_count=item["conflictCount"], reason=item["reason"]))
            run.status, run.build, run.engine_version = "success", build, result["engineVersion"]
            state.active_run_id = run.id

    def read_view(self):
        with self.database.transaction(read_only=True) as session:
            state = state_row(session)
            snapshot = snapshot_from_session(session, state.strategy)
            document = None
            if state.active_run_id is not None:
                run = session.get(AllocationRun, state.active_run_id)
                if run is None or run.status != "success":
                    raise PersistenceError("Active allocation run is inconsistent; refusing stale-file fallback.")
                document = {"snapshot": run.snapshot, "result": result_from_session(session, run), "build": run.build}
                validate_publication(document["result"], document["snapshot"])
            return snapshot, document, state.active_run_id


def result_from_session(session, run):
    spaces = {item["id"]: item for item in run.snapshot["spaces"]}
    allocations = list(session.scalars(select(Allocation).where(Allocation.run_id == run.id).order_by(Allocation.engine_id)))
    participants = defaultdict(list)
    if allocations:
        for item in session.scalars(select(AllocationParticipant).where(AllocationParticipant.allocation_id.in_([a.id for a in allocations]))
                                   .order_by(AllocationParticipant.allocation_id, AllocationParticipant.ordinal)):
            participants[item.allocation_id].append(item.user_id)
    allocation_results = []
    for item in allocations:
        space = spaces[item.resource_id]
        allocation_results.append({"allocationId": item.engine_id, "requestId": item.request_id, "spaceId": item.resource_id,
                                   "spaceName": space["name"], "spaceType": space["type"], "building": space["building"],
                                   "spaceCapacity": space["capacity"], "slot": slot_dict(item),
                                   "assignedParticipants": item.assigned_participants, "requiredParticipantIds": participants[item.id]})
    suggestions = defaultdict(list)
    for item in session.scalars(select(MeetingSuggestion).where(MeetingSuggestion.run_id == run.id)
                               .order_by(MeetingSuggestion.request_id, MeetingSuggestion.rank)):
        suggestions[item.request_id].append({"spaceId": item.resource_id, "slot": slot_dict(item), "score": item.score,
                                             "timeDistanceMinutes": item.time_distance, "dayDistance": item.day_distance,
                                             "conflictCount": item.conflict_count, "reason": item.reason})
    groups = session.scalars(select(SuggestionGroup).where(SuggestionGroup.run_id == run.id).order_by(SuggestionGroup.ordinal))
    return {"protocolVersion": 1, "engineVersion": run.engine_version, "runId": run.correlation_id, "strategy": run.strategy,
            "status": "success", "errors": [], "allocations": allocation_results,
            "requestResults": [item.payload for item in session.scalars(select(RequestDecision).where(RequestDecision.run_id == run.id).order_by(RequestDecision.ordinal))],
            "suggestions": [{"requestId": group.request_id, "items": suggestions[group.request_id]} for group in groups]}


def advance_identity(session, model, column="id"):
    sequence = session.scalar(select(func.pg_get_serial_sequence(model.__tablename__, column)))
    last = session.scalar(select(func.max(getattr(model, column)))) or 0
    session.execute(text("SELECT setval(CAST(:sequence AS regclass), :value, :used)"),
                    {"sequence": sequence, "value": max(last, 1), "used": bool(last)})
