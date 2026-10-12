"""Relational records for the existing weekly application, not C++ domain rules."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Identity, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


ROLES = ("Student", "TeachingAssistant", "Staff", "Instructor", "Administrator")
STRATEGIES = ("greedy", "priority", "multi_room_exam_greedy", "multi_room_exam_best_fit", "shared_room_exam_best_fit")
REQUEST_TYPES = ("OneTime", "Recurring", "Exam", "CommitteeMeeting")
SPACE_TYPES = ("Classroom", "Laboratory", "MeetingRoom")


class Base(DeclarativeBase):
    pass


def allowed(column, values):
    return column + " IN (" + ",".join("'" + item + "'" for item in values) + ")"


def slot_checks():
    return (CheckConstraint("day BETWEEN 1 AND 7"),
            CheckConstraint("start_minutes >= 0 AND start_minutes < end_minutes AND end_minutes <= 1440"))


class Role(Base):
    __tablename__ = "role"
    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)


class OrganizationUnit(Base):
    __tablename__ = "organization_unit"
    __table_args__ = (CheckConstraint("parent_id IS NULL OR parent_id <> id"),)
    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    unit_type: Mapped[str | None] = mapped_column(String(100))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("organization_unit.id"), index=True)


class User(Base):
    __tablename__ = "university_user"
    __table_args__ = (CheckConstraint("id > 0"), CheckConstraint("year_level >= 0"))
    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    source_order: Mapped[int] = mapped_column(Integer, unique=True)
    name: Mapped[str] = mapped_column(Text)
    primary_role_id: Mapped[int] = mapped_column(ForeignKey("role.id"), index=True)
    primary_unit_id: Mapped[int | None] = mapped_column(ForeignKey("organization_unit.id"), index=True)
    email: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(Text, default="active")
    student_no: Mapped[str] = mapped_column(Text, default="")
    program: Mapped[str] = mapped_column(Text, default="")
    year_level: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(Text, default="")
    office_room: Mapped[str] = mapped_column(Text, default="")
    assistant_type: Mapped[str] = mapped_column(Text, default="")
    job_title: Mapped[str] = mapped_column(Text, default="")
    admin_level: Mapped[str] = mapped_column(Text, default="")


class UserRole(Base):
    __tablename__ = "user_role"
    __table_args__ = (UniqueConstraint("user_id", "ordinal"),)
    user_id: Mapped[int] = mapped_column(ForeignKey("university_user.id"), primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("role.id"), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer)


class Resource(Base):
    __tablename__ = "resource"
    __table_args__ = (CheckConstraint("id > 0 AND capacity > 0"), CheckConstraint(allowed("type", SPACE_TYPES)))
    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    source_order: Mapped[int] = mapped_column(Integer, unique=True)
    type: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(Text)
    capacity: Mapped[int] = mapped_column(Integer)
    building: Mapped[str] = mapped_column(Text, default="")
    projector: Mapped[bool] = mapped_column(Boolean, default=False)
    whiteboard: Mapped[bool] = mapped_column(Boolean, default=False)
    computers: Mapped[bool] = mapped_column(Boolean, default=False)
    available: Mapped[bool] = mapped_column(Boolean, default=True)


class ResourceRequest(Base):
    __tablename__ = "resource_request"
    __table_args__ = (CheckConstraint("id > 0 AND participant_count > 0 AND revision > 0"), CheckConstraint(allowed("type", REQUEST_TYPES)))
    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    submission_order: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    type: Mapped[str] = mapped_column(String(30))
    requester_id: Mapped[int] = mapped_column(ForeignKey("university_user.id"), index=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resource.id"), index=True)
    participant_count: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text, default="")
    purpose: Mapped[str] = mapped_column(Text, default="")
    required_feature: Mapped[str] = mapped_column(Text, default="")
    required_building: Mapped[str] = mapped_column(Text, default="")
    revision: Mapped[int] = mapped_column(Integer, default=1)


class RequestSlot(Base):
    __tablename__ = "request_slot"
    __table_args__ = slot_checks()
    request_id: Mapped[int] = mapped_column(ForeignKey("resource_request.id"), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[int] = mapped_column(Integer)
    start_minutes: Mapped[int] = mapped_column(Integer)
    end_minutes: Mapped[int] = mapped_column(Integer)


class ExamDetails(Base):
    __tablename__ = "exam_details"
    request_id: Mapped[int] = mapped_column(ForeignKey("resource_request.id"), primary_key=True)
    course_code: Mapped[str] = mapped_column(Text, default="")
    course_name: Mapped[str] = mapped_column(Text, default="")
    exam_type: Mapped[str] = mapped_column(Text, default="")
    can_split: Mapped[bool] = mapped_column(Boolean, default=False)


class RequestParticipant(Base):
    __tablename__ = "request_participant"
    __table_args__ = (UniqueConstraint("request_id", "ordinal"),)
    request_id: Mapped[int] = mapped_column(ForeignKey("resource_request.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("university_user.id"), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(Text, default="Participant")


class BusySlot(Base):
    __tablename__ = "busy_slot"
    __table_args__ = slot_checks()
    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("university_user.id"), index=True)
    source_order: Mapped[int] = mapped_column(Integer, unique=True)
    day: Mapped[int] = mapped_column(Integer)
    start_minutes: Mapped[int] = mapped_column(Integer)
    end_minutes: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text, default="")


class AllocationRun(Base):
    __tablename__ = "allocation_run"
    __table_args__ = (CheckConstraint(allowed("status", ("running", "success", "failed", "superseded"))), CheckConstraint(allowed("strategy", STRATEGIES)))
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    correlation_id: Mapped[str] = mapped_column(String(32), unique=True)
    input_revision: Mapped[int] = mapped_column(BigInteger)
    strategy: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)
    snapshot: Mapped[dict] = mapped_column(JSONB)
    build: Mapped[dict] = mapped_column(JSONB, default=dict)
    engine_version: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApplicationState(Base):
    __tablename__ = "application_state"
    __table_args__ = (CheckConstraint("id = 1 AND input_revision >= 0"), CheckConstraint(allowed("strategy", STRATEGIES)))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    input_revision: Mapped[int] = mapped_column(BigInteger, default=0)
    strategy: Mapped[str] = mapped_column(String(50), default="greedy")
    active_run_id: Mapped[int | None] = mapped_column(ForeignKey("allocation_run.id"))


class RequestDecision(Base):
    __tablename__ = "request_decision"
    __table_args__ = (CheckConstraint(allowed("status", ("Approved", "Rejected"))),)
    run_id: Mapped[int] = mapped_column(ForeignKey("allocation_run.id"), primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("resource_request.id"), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB)


class Allocation(Base):
    __tablename__ = "allocation"
    __table_args__ = (ForeignKeyConstraint(["run_id", "request_id"], ["request_decision.run_id", "request_decision.request_id"]),
                      UniqueConstraint("run_id", "engine_id"), CheckConstraint("assigned_participants > 0"), *slot_checks())
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[int] = mapped_column(BigInteger, index=True)
    request_id: Mapped[int] = mapped_column(Integer, index=True)
    engine_id: Mapped[int] = mapped_column(Integer)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resource.id"), index=True)
    day: Mapped[int] = mapped_column(Integer)
    start_minutes: Mapped[int] = mapped_column(Integer)
    end_minutes: Mapped[int] = mapped_column(Integer)
    assigned_participants: Mapped[int] = mapped_column(Integer)


class AllocationParticipant(Base):
    __tablename__ = "allocation_participant"
    allocation_id: Mapped[int] = mapped_column(ForeignKey("allocation.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("university_user.id"), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, server_default="0")


class SuggestionGroup(Base):
    __tablename__ = "suggestion_group"
    __table_args__ = (ForeignKeyConstraint(["run_id", "request_id"], ["request_decision.run_id", "request_decision.request_id"]),)
    run_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    request_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer)


class MeetingSuggestion(Base):
    __tablename__ = "meeting_suggestion"
    __table_args__ = (ForeignKeyConstraint(["run_id", "request_id"], ["suggestion_group.run_id", "suggestion_group.request_id"]), *slot_checks())
    run_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    request_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rank: Mapped[int] = mapped_column(Integer, primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resource.id"))
    day: Mapped[int] = mapped_column(Integer)
    start_minutes: Mapped[int] = mapped_column(Integer)
    end_minutes: Mapped[int] = mapped_column(Integer)
    score: Mapped[int] = mapped_column(Integer)
    time_distance: Mapped[int] = mapped_column(Integer)
    day_distance: Mapped[int] = mapped_column(Integer)
    conflict_count: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)


class RequestHistory(Base):
    __tablename__ = "request_history"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("resource_request.id"), index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("allocation_run.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
