"""Database reads/writes and domain DTO mapping, without allocation algorithms."""

import uuid
from collections import defaultdict

from sqlalchemy import func, select, text

from .models import ApplicationState, BusySlot, ExamDetails, OrganizationUnit, RequestHistory, RequestParticipant, RequestSlot, Resource, ResourceRequest, Role, User, UserRole


class PersistenceError(RuntimeError):
    pass


class StaleRun(PersistenceError):
    pass


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


def advance_identity(session, model, column="id"):
    sequence = session.scalar(select(func.pg_get_serial_sequence(model.__tablename__, column)))
    last = session.scalar(select(func.max(getattr(model, column)))) or 0
    session.execute(text("SELECT setval(CAST(:sequence AS regclass), :value, :used)"),
                    {"sequence": sequence, "value": max(last, 1), "used": bool(last)})
