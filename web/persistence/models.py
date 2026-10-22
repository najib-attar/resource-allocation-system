"""Relational records for the existing weekly application, not C++ domain rules."""

from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Computed, Date, DateTime, ForeignKey, ForeignKeyConstraint, Identity, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ExcludeConstraint, JSONB, TSTZRANGE
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
    __table_args__ = (CheckConstraint("id > 0"), CheckConstraint("year_level >= 0"), CheckConstraint("source_order > 0", name="ck_user_source_order"))
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
    __table_args__ = (UniqueConstraint("user_id", "ordinal"), CheckConstraint("ordinal > 0", name="ck_user_role_ordinal"))
    user_id: Mapped[int] = mapped_column(ForeignKey("university_user.id"), primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("role.id"), primary_key=True, index=True)
    ordinal: Mapped[int] = mapped_column(Integer)


class Resource(Base):
    __tablename__ = "resource"
    __table_args__ = (CheckConstraint("id > 0 AND capacity > 0"), CheckConstraint(allowed("type", SPACE_TYPES)), CheckConstraint("source_order > 0", name="ck_resource_source_order"))
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
    __table_args__ = (CheckConstraint("id > 0 AND participant_count > 0 AND revision > 0"), CheckConstraint(allowed("type", REQUEST_TYPES)), CheckConstraint("submission_order > 0", name="ck_request_submission_order"),
                      CheckConstraint("(submission_key IS NULL AND submission_fingerprint IS NULL) OR (submission_key IS NOT NULL AND submission_fingerprint IS NOT NULL AND submission_key ~ '^[0-9a-f]{32}$' AND submission_fingerprint ~ '^[0-9a-f]{64}$')", name="ck_submission_identity"),
                      CheckConstraint("NOT calendar_public OR type <> 'CommitteeMeeting'", name="ck_calendar_public_request_type"))
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
    submission_key: Mapped[str | None] = mapped_column(String(32), unique=True)
    submission_fingerprint: Mapped[str | None] = mapped_column(String(64))
    calendar_public: Mapped[bool] = mapped_column(Boolean, server_default="false")
    academic_instructor_id: Mapped[int | None] = mapped_column(ForeignKey("university_user.id"), index=True)


class RequestSlot(Base):
    __tablename__ = "request_slot"
    __table_args__ = (*slot_checks(), CheckConstraint("ordinal > 0", name="ck_request_slot_ordinal"))
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
    __table_args__ = (UniqueConstraint("request_id", "ordinal"), CheckConstraint("ordinal > 0", name="ck_request_participant_ordinal"))
    request_id: Mapped[int] = mapped_column(ForeignKey("resource_request.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("university_user.id"), primary_key=True, index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(Text, default="Participant")


class BusySlot(Base):
    __tablename__ = "busy_slot"
    __table_args__ = (*slot_checks(), CheckConstraint("source_order > 0", name="ck_busy_source_order"))
    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("university_user.id"), index=True)
    source_order: Mapped[int] = mapped_column(Integer, unique=True)
    day: Mapped[int] = mapped_column(Integer)
    start_minutes: Mapped[int] = mapped_column(Integer)
    end_minutes: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text, default="")


class AllocationRun(Base):
    __tablename__ = "allocation_run"
    __table_args__ = (CheckConstraint(allowed("status", ("running", "success", "failed", "superseded"))), CheckConstraint(allowed("strategy", STRATEGIES)), CheckConstraint("input_revision >= 0", name="ck_run_input_revision"))
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
    __table_args__ = (CheckConstraint("id = 1 AND input_revision >= 0"), CheckConstraint(allowed("strategy", STRATEGIES)),
                      CheckConstraint("waiting_notice_minutes > 0", name="ck_waiting_notice"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    input_revision: Mapped[int] = mapped_column(BigInteger, default=0)
    strategy: Mapped[str] = mapped_column(String(50), default="greedy")
    active_run_id: Mapped[int | None] = mapped_column(ForeignKey("allocation_run.id"))
    calendar_revision: Mapped[int] = mapped_column(BigInteger, server_default="0")
    waiting_notice_minutes: Mapped[int | None] = mapped_column(Integer)
    recurring_limits: Mapped[dict] = mapped_column(JSONB, server_default="'{}'::jsonb")
    reservation_priorities: Mapped[list] = mapped_column(JSONB, server_default="'[]'::jsonb")


class RequestDecision(Base):
    __tablename__ = "request_decision"
    __table_args__ = (CheckConstraint(allowed("status", ("Approved", "Rejected"))),
                      UniqueConstraint("run_id", "ordinal", name="uq_decision_order"), CheckConstraint("ordinal > 0", name="ck_decision_ordinal"))
    run_id: Mapped[int] = mapped_column(ForeignKey("allocation_run.id"), primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("resource_request.id"), primary_key=True, index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB)


class Allocation(Base):
    __tablename__ = "allocation"
    __table_args__ = (ForeignKeyConstraint(["run_id", "request_id"], ["request_decision.run_id", "request_decision.request_id"]),
                      UniqueConstraint("run_id", "engine_id"), CheckConstraint("assigned_participants > 0"), *slot_checks(),
                      Index("ix_allocation_decision", "run_id", "request_id"), CheckConstraint("engine_id >= 0", name="ck_allocation_engine_id"))
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[int] = mapped_column(BigInteger)
    request_id: Mapped[int] = mapped_column(Integer, index=True)
    engine_id: Mapped[int] = mapped_column(Integer)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resource.id"), index=True)
    day: Mapped[int] = mapped_column(Integer)
    start_minutes: Mapped[int] = mapped_column(Integer)
    end_minutes: Mapped[int] = mapped_column(Integer)
    assigned_participants: Mapped[int] = mapped_column(Integer)


class AllocationParticipant(Base):
    __tablename__ = "allocation_participant"
    __table_args__ = (CheckConstraint("ordinal >= 0", name="ck_allocation_participant_ordinal"),)
    allocation_id: Mapped[int] = mapped_column(ForeignKey("allocation.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("university_user.id"), primary_key=True, index=True)
    ordinal: Mapped[int] = mapped_column(Integer, server_default="0")


class SuggestionGroup(Base):
    __tablename__ = "suggestion_group"
    __table_args__ = (ForeignKeyConstraint(["run_id", "request_id"], ["request_decision.run_id", "request_decision.request_id"]),
                      UniqueConstraint("run_id", "ordinal", name="uq_suggestion_group_order"), CheckConstraint("ordinal > 0", name="ck_suggestion_group_ordinal"))
    run_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    request_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer)


class MeetingSuggestion(Base):
    __tablename__ = "meeting_suggestion"
    __table_args__ = (ForeignKeyConstraint(["run_id", "request_id"], ["suggestion_group.run_id", "suggestion_group.request_id"]), *slot_checks(),
                      CheckConstraint("rank > 0 AND score >= 0 AND time_distance >= 0 AND day_distance >= 0 AND conflict_count >= 0", name="ck_suggestion_scores"))
    run_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    request_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rank: Mapped[int] = mapped_column(Integer, primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resource.id"), index=True)
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


class LoginAccount(Base):
    __tablename__ = "login_account"
    __table_args__ = (CheckConstraint("failed_attempts >= 0 AND session_version > 0"),)
    user_id: Mapped[int] = mapped_column(ForeignKey("university_user.id"), primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    administrator: Mapped[bool] = mapped_column(Boolean, default=False)
    session_version: Mapped[int] = mapped_column(Integer, default=1)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AcademicPeriod(Base):
    __tablename__ = "academic_period"
    __table_args__ = (CheckConstraint("start_date <= end_date"),)
    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    timezone: Mapped[str] = mapped_column(String(100))
    is_semester: Mapped[bool] = mapped_column(Boolean, server_default='false')


class LegacyCalendarBinding(Base):
    __tablename__ = "legacy_calendar_binding"
    __table_args__ = (
        CheckConstraint("(busy_slot_id IS NULL) <> (request_id IS NULL)"),
        UniqueConstraint("period_id", "busy_slot_id"), UniqueConstraint("period_id", "request_id"),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("academic_period.id"), index=True)
    busy_slot_id: Mapped[int | None] = mapped_column(ForeignKey("busy_slot.id"), index=True)
    request_id: Mapped[int | None] = mapped_column(ForeignKey("resource_request.id"), index=True)
    week_start: Mapped[date | None] = mapped_column(Date)
    excluded_dates: Mapped[list] = mapped_column(JSONB, default=list)


class ProfessorAvailability(Base):
    __tablename__ = "professor_availability"
    __table_args__ = (*slot_checks(), CheckConstraint("valid_from <= valid_until"))
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("university_user.id"), index=True)
    day: Mapped[int] = mapped_column(Integer)
    start_minutes: Mapped[int] = mapped_column(Integer)
    end_minutes: Mapped[int] = mapped_column(Integer)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_until: Mapped[date] = mapped_column(Date)
    timezone: Mapped[str] = mapped_column(String(100))
    excluded_dates: Mapped[list] = mapped_column(JSONB, default=list)


class CalendarBlock(Base):
    __tablename__ = "calendar_block"
    __table_args__ = (CheckConstraint("start_at < end_at"), Index("ix_calendar_block_user_start", "user_id", "start_at"))
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("university_user.id"))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(Text, default="")


class Appointment(Base):
    __tablename__ = "appointment"
    __table_args__ = (
        CheckConstraint("revision > 0 AND duration_minutes > 0 AND start_at < end_at"),
        CheckConstraint("end_at = start_at + duration_minutes * interval '1 minute'"),
        CheckConstraint(allowed("status", ("Pending Approval", "Declined", "Confirmed", "Cancelled"))),
        Index("ix_appointment_organizer_start", "organizer_id", "start_at"),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    organizer_id: Mapped[int] = mapped_column(ForeignKey("university_user.id"))
    purpose: Mapped[str] = mapped_column(Text)
    duration_minutes: Mapped[int] = mapped_column(Integer)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="Pending Approval")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AppointmentProfessor(Base):
    __tablename__ = "appointment_professor"
    __table_args__ = (CheckConstraint(allowed("decision", ("Pending", "Approved", "Declined"))), CheckConstraint("revision > 0"))
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointment.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("university_user.id"), primary_key=True, index=True)
    revision: Mapped[int] = mapped_column(Integer)
    decision: Mapped[str] = mapped_column(String(20), default="Pending")


class AppointmentInvitation(Base):
    __tablename__ = "appointment_invitation"
    __table_args__ = (CheckConstraint(allowed("status", ("Invited", "Declined"))),)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointment.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("university_user.id"), primary_key=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="Invited")


class AppointmentCommitment(Base):
    __tablename__ = "appointment_commitment"
    __table_args__ = (
        CheckConstraint("start_at < end_at"),
        ExcludeConstraint(("user_id", "="), ("period", "&&"), using="gist", name="ex_appointment_person_overlap"),
    )
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointment.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("university_user.id"), primary_key=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period: Mapped[object] = mapped_column(TSTZRANGE, Computed("tstzrange(start_at, end_at, '[)')", persisted=True))


class AppointmentEvent(Base):
    __tablename__ = "appointment_event"
    __table_args__ = (CheckConstraint("revision > 0"),)
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointment.id"), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("university_user.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


ROOM_CATEGORIES = ("study", "meeting", "lecture", "club", "other")
ROOM_REQUEST_STATES = ("Pending Faculty Approval", "Needs Revision", "Rejected", "Confirmed", "Cancelled")


class FacultyRoomApprover(Base):
    __tablename__ = "faculty_room_approver"
    faculty_id: Mapped[int] = mapped_column(ForeignKey("organization_unit.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("login_account.user_id"), index=True)


class RoomPolicy(Base):
    __tablename__ = "room_policy"
    __table_args__ = (CheckConstraint("jsonb_typeof(categories) = 'array' AND jsonb_array_length(categories) BETWEEN 1 AND 5 AND '[\"study\",\"meeting\",\"lecture\",\"club\",\"other\"]'::jsonb @> categories"),)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resource.id"), primary_key=True)
    faculty_id: Mapped[int] = mapped_column(ForeignKey("organization_unit.id"), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    restricted: Mapped[bool] = mapped_column(Boolean, default=False)
    categories: Mapped[list] = mapped_column(JSONB, default=lambda: list(ROOM_CATEGORIES))


class RoomAccess(Base):
    __tablename__ = "room_access"
    resource_id: Mapped[int] = mapped_column(ForeignKey("room_policy.resource_id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("university_user.id"), primary_key=True, index=True)


class RoomClosure(Base):
    __tablename__ = "room_closure"
    __table_args__ = (CheckConstraint("start_at < end_at"), Index("ix_room_closure_resource_start", "resource_id", "start_at"))
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resource.id"))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(Text, default="")


class StudentRoomRequest(Base):
    __tablename__ = "student_room_request"
    __table_args__ = (CheckConstraint(allowed("category", ROOM_CATEGORIES)), CheckConstraint(allowed("status", ROOM_REQUEST_STATES)),
                      CheckConstraint("revision > 0 AND attendee_count > 0 AND duration_minutes BETWEEN 1 AND 1440 AND start_at < end_at"),
                      CheckConstraint("end_at = start_at + duration_minutes * interval '1 minute'"),
                      CheckConstraint("jsonb_typeof(required_features) = 'array' AND '[\"projector\",\"whiteboard\",\"computers\"]'::jsonb @> required_features"),
                      CheckConstraint("status <> 'Confirmed' OR (approved_revision IS NOT NULL AND approved_revision = revision AND approved_by IS NOT NULL AND approved_by = approver_id)"),
                      Index("ix_student_room_organizer_start", "organizer_id", "start_at"), Index("ix_student_room_approver_status", "approver_id", "status"))
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    organizer_id: Mapped[int] = mapped_column(ForeignKey("university_user.id"))
    priority: Mapped[int] = mapped_column(Integer, server_default='0')
    resource_id: Mapped[int] = mapped_column(ForeignKey("resource.id"), index=True)
    faculty_id: Mapped[int] = mapped_column(ForeignKey("organization_unit.id"), index=True)
    approver_id: Mapped[int] = mapped_column(ForeignKey("login_account.user_id"))
    category: Mapped[str] = mapped_column(String(30))
    purpose: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    club_affiliation: Mapped[str] = mapped_column(Text, default="")
    attendee_count: Mapped[int] = mapped_column(Integer)
    required_features: Mapped[list] = mapped_column(JSONB, default=list)
    preferred_faculty_id: Mapped[int | None] = mapped_column(ForeignKey("organization_unit.id"), index=True)
    preferred_building: Mapped[str] = mapped_column(Text, default="")
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_minutes: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="Pending Faculty Approval")
    approved_revision: Mapped[int | None] = mapped_column(Integer)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("login_account.user_id"), index=True)
    explanation: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RoomInvitation(Base):
    __tablename__ = "room_invitation"
    __table_args__ = (CheckConstraint(allowed("status", ("Invited", "Accepted", "Declined"))), CheckConstraint("revision > 0"))
    request_id: Mapped[int] = mapped_column(ForeignKey("student_room_request.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("university_user.id"), primary_key=True, index=True)
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="Invited")


class RoomReservation(Base):
    __tablename__ = "room_reservation"
    __table_args__ = (CheckConstraint("start_at < end_at"), ExcludeConstraint(("resource_id", "="), ("period", "&&"), using="gist", name="ex_student_room_overlap"))
    request_id: Mapped[int] = mapped_column(ForeignKey("student_room_request.id"), primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resource.id"), index=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    occurrence_id: Mapped[int | None] = mapped_column(ForeignKey("reservation_occurrence.id"), unique=True)
    period: Mapped[object] = mapped_column(TSTZRANGE, Computed("tstzrange(start_at, end_at, '[)')", persisted=True))


class RoomOrganizerCommitment(Base):
    __tablename__ = "room_organizer_commitment"
    __table_args__ = (CheckConstraint("start_at < end_at"), ExcludeConstraint(("user_id", "="), ("period", "&&"), using="gist", name="ex_room_organizer_overlap"))
    request_id: Mapped[int] = mapped_column(ForeignKey("student_room_request.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("university_user.id"), index=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    occurrence_id: Mapped[int | None] = mapped_column(ForeignKey("reservation_occurrence.id"), unique=True)
    period: Mapped[object] = mapped_column(TSTZRANGE, Computed("tstzrange(start_at, end_at, '[)')", persisted=True))


class RoomEvent(Base):
    __tablename__ = "room_event"
    __table_args__ = (CheckConstraint("revision > 0"),)
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("student_room_request.id"), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("university_user.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Notification(Base):
    __tablename__ = "notification"
    __table_args__ = (
        CheckConstraint("num_nonnulls(appointment_event_id, room_event_id, equipment_event_id, feedback_event_id) = 1", name="ck_notification_source"),
        UniqueConstraint("recipient_id", "appointment_event_id"),
        UniqueConstraint("recipient_id", "room_event_id"),
        UniqueConstraint("recipient_id", "equipment_event_id"),
        UniqueConstraint("recipient_id", "feedback_event_id"),
        Index("ix_notification_recipient_read_id", "recipient_id", "read_at", "id"),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("university_user.id"))
    appointment_event_id: Mapped[int | None] = mapped_column(ForeignKey("appointment_event.id"), index=True)
    room_event_id: Mapped[int | None] = mapped_column(ForeignKey("room_event.id"), index=True)
    equipment_event_id: Mapped[int | None] = mapped_column(ForeignKey("equipment_event.id"), index=True)
    feedback_event_id: Mapped[int | None] = mapped_column(ForeignKey("feedback_event.id"), index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


EQUIPMENT_CONDITIONS = ('usable', 'maintenance', 'damaged', 'missing', 'lost', 'retired')
BORROW_STATES = ('Pending Approval', 'Approved', 'Rejected', 'Borrowed', 'Partially Returned', 'Returned', 'Cancelled')


class EquipmentCategory(Base):
    __tablename__ = 'equipment_category'
    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True)


class EquipmentCustodian(Base):
    __tablename__ = 'equipment_custodian'
    faculty_id: Mapped[int] = mapped_column(ForeignKey('organization_unit.id'), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('login_account.user_id'), index=True)


class EquipmentType(Base):
    __tablename__ = 'equipment_type'
    __table_args__ = (UniqueConstraint('id', 'faculty_id'), CheckConstraint('max_loan_days BETWEEN 1 AND 365'),
                      CheckConstraint("jsonb_typeof(specifications) = 'object' AND jsonb_typeof(eligible_faculty_ids) = 'array'"))
    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    faculty_id: Mapped[int] = mapped_column(ForeignKey('organization_unit.id'), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey('equipment_category.id'), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default='')
    specifications: Mapped[dict] = mapped_column(JSONB, default=dict)
    max_loan_days: Mapped[int] = mapped_column(Integer)
    eligible_faculty_ids: Mapped[list] = mapped_column(JSONB, default=list)
    pickup_instructions: Mapped[str] = mapped_column(Text, default='')
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class EquipmentUnit(Base):
    __tablename__ = 'equipment_unit'
    __table_args__ = (UniqueConstraint('id', 'type_id'), CheckConstraint(allowed('condition', EQUIPMENT_CONDITIONS)))
    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    type_id: Mapped[int] = mapped_column(ForeignKey('equipment_type.id'), index=True)
    asset_tag: Mapped[str] = mapped_column(String(150), unique=True)
    condition: Mapped[str] = mapped_column(String(20), default='usable')
    notes: Mapped[str] = mapped_column(Text, default='')


class BorrowRequest(Base):
    __tablename__ = 'borrow_request'
    priority: Mapped[int] = mapped_column(Integer, server_default='0')
    __table_args__ = (UniqueConstraint('id', 'faculty_id'), UniqueConstraint('borrower_id', 'submission_key'),
                      CheckConstraint(allowed('status', BORROW_STATES)), CheckConstraint('start_at < due_at'),
                      CheckConstraint("submission_key ~ '^[0-9a-f]{32}$' AND submission_fingerprint ~ '^[0-9a-f]{64}$'"),
                      Index('ix_borrow_faculty_status', 'faculty_id', 'status'))
    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    borrower_id: Mapped[int] = mapped_column(ForeignKey('university_user.id'), index=True)
    faculty_id: Mapped[int] = mapped_column(ForeignKey('organization_unit.id'))
    purpose: Mapped[str] = mapped_column(Text)
    notes: Mapped[str] = mapped_column(Text, default='')
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default='Pending Approval')
    submission_key: Mapped[str] = mapped_column(String(32))
    submission_fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BorrowItem(Base):
    __tablename__ = 'borrow_item'
    __table_args__ = (ForeignKeyConstraint(['request_id', 'faculty_id'], ['borrow_request.id', 'borrow_request.faculty_id']),
                      ForeignKeyConstraint(['type_id', 'faculty_id'], ['equipment_type.id', 'equipment_type.faculty_id']),
                      UniqueConstraint('request_id', 'type_id'), UniqueConstraint('id', 'type_id'),
                      Index('ix_borrow_item_request_faculty', 'request_id', 'faculty_id'),
                      Index('ix_borrow_item_type_faculty', 'type_id', 'faculty_id'),
                      CheckConstraint("quantity BETWEEN 1 AND 1000 AND jsonb_typeof(specifications) = 'object'"))
    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    request_id: Mapped[int] = mapped_column(Integer)
    faculty_id: Mapped[int] = mapped_column(Integer, index=True)
    type_id: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)
    specifications: Mapped[dict] = mapped_column(JSONB, default=dict)


class EquipmentReservation(Base):
    __tablename__ = 'equipment_reservation'
    __table_args__ = (ForeignKeyConstraint(['item_id', 'type_id'], ['borrow_item.id', 'borrow_item.type_id']),
                      ForeignKeyConstraint(['unit_id', 'type_id'], ['equipment_unit.id', 'equipment_unit.type_id']),
                      CheckConstraint('start_at < due_at'),
                      CheckConstraint('returned_at IS NULL OR (handed_at IS NOT NULL AND returned_at >= handed_at AND released)'),
                      CheckConstraint('handed_at IS NULL OR (handed_by IS NOT NULL AND handover_condition IS NOT NULL)'),
                      CheckConstraint('returned_at IS NULL OR (received_by IS NOT NULL AND return_condition IS NOT NULL)'),
                      CheckConstraint('NOT released OR handed_at IS NULL OR returned_at IS NOT NULL', name='ck_equipment_physical_release'),
                      Index('ix_equipment_reservation_item_type', 'item_id', 'type_id'),
                      Index('ix_equipment_reservation_unit_type', 'unit_id', 'type_id'),
                      Index('uq_equipment_outstanding_unit', 'unit_id', unique=True, postgresql_where='handed_at IS NOT NULL AND returned_at IS NULL'),
                      ExcludeConstraint(('unit_id', '='), ('period', '&&'), where="NOT released", using='gist', name='ex_equipment_overlap'))
    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    item_id: Mapped[int] = mapped_column(Integer)
    occurrence_id: Mapped[int | None] = mapped_column(ForeignKey('reservation_occurrence.id'), index=True)
    type_id: Mapped[int] = mapped_column(Integer, index=True)
    unit_id: Mapped[int] = mapped_column(Integer)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period: Mapped[object] = mapped_column(TSTZRANGE, Computed("tstzrange(start_at, due_at, '[)')", persisted=True))
    released: Mapped[bool] = mapped_column(Boolean, default=False)
    handed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    handed_by: Mapped[int | None] = mapped_column(ForeignKey('login_account.user_id'), index=True)
    handover_condition: Mapped[str | None] = mapped_column(Text)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_by: Mapped[int | None] = mapped_column(ForeignKey('login_account.user_id'), index=True)
    return_condition: Mapped[str | None] = mapped_column(Text)


class BorrowExtension(Base):
    __tablename__ = 'borrow_extension'
    __table_args__ = (CheckConstraint(allowed('status', ('Pending', 'Approved', 'Rejected'))),
                      Index('uq_pending_borrow_extension', 'request_id', unique=True, postgresql_where="status = 'Pending'"))
    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey('borrow_request.id'), index=True)
    occurrence_id: Mapped[int | None] = mapped_column(ForeignKey('reservation_occurrence.id'), index=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default='Pending')
    reason: Mapped[str] = mapped_column(Text)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey('login_account.user_id'), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EquipmentEvent(Base):
    __tablename__ = 'equipment_event'
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    faculty_id: Mapped[int] = mapped_column(ForeignKey('organization_unit.id'), index=True)
    request_id: Mapped[int | None] = mapped_column(ForeignKey('borrow_request.id'), index=True)
    unit_id: Mapped[int | None] = mapped_column(ForeignKey('equipment_unit.id'), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey('university_user.id'), index=True)
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


WAITING_ACTIVE = ('Pending Review', 'Preapproved')
WAITING_STATES = (*WAITING_ACTIVE, 'Assigned', 'Rejected', 'Cancelled', 'Expired', 'Ineligible')


class WaitingListEntry(Base):
    """Queue metadata only; the linked room/borrowing request owns requirements."""
    __tablename__ = 'waiting_list_entry'
    __table_args__ = (
        CheckConstraint('num_nonnulls(room_request_id, borrow_request_id) = 1', name='ck_waiting_parent'),
        CheckConstraint(allowed('status', WAITING_STATES), name='ck_waiting_status'),
        CheckConstraint("submission_key ~ '^[0-9a-f]{32}$' AND fingerprint ~ '^[0-9a-f]{64}$' AND queue_key ~ '^[0-9a-f]{64}$'", name='ck_waiting_keys'),
        CheckConstraint("length(policy_version) > 0 AND (notice_minutes IS NULL OR notice_minutes > 0)", name='ck_waiting_consent'),
        CheckConstraint("status NOT IN ('Preapproved','Assigned') OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)", name='ck_waiting_approval'),
        UniqueConstraint('owner_id', 'submission_key'),
        Index('ix_waiting_faculty_status_id', 'faculty_id', 'status', 'id'),
        Index('ix_waiting_queue_status_id', 'queue_key', 'status', 'id'),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    room_request_id: Mapped[int | None] = mapped_column(ForeignKey('student_room_request.id'), unique=True)
    borrow_request_id: Mapped[int | None] = mapped_column(ForeignKey('borrow_request.id'), unique=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey('university_user.id'), index=True)
    faculty_id: Mapped[int] = mapped_column(ForeignKey('organization_unit.id'))
    submission_key: Mapped[str] = mapped_column(String(32))
    fingerprint: Mapped[str] = mapped_column(String(64))
    queue_key: Mapped[str] = mapped_column(String(64))
    policy_version: Mapped[str] = mapped_column(String(100))
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())
    notice_minutes: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default='Pending Review')
    approved_by: Mapped[int | None] = mapped_column(ForeignKey('login_account.user_id'), index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    top_three_notified: Mapped[bool] = mapped_column(Boolean, default=False)
    first_notified: Mapped[bool] = mapped_column(Boolean, default=False)
    explanation: Mapped[str] = mapped_column(Text, default='Awaiting responsible staff review; no resource is reserved.')


FEEDBACK_CATEGORIES = ('problem', 'improvement', 'general')
FEEDBACK_STATES = ('Submitted', 'Under Review', 'Resolved', 'Closed')
FEEDBACK_PRIORITIES = ('low', 'normal', 'high', 'urgent')


class ResourceFeedback(Base):
    __tablename__ = 'resource_feedback'
    __table_args__ = (
        CheckConstraint('(room_request_id IS NOT NULL AND room_resource_id IS NOT NULL AND room_revision IS NOT NULL AND room_revision > 0 AND equipment_reservation_id IS NULL) OR (room_request_id IS NULL AND room_resource_id IS NULL AND room_revision IS NULL AND equipment_reservation_id IS NOT NULL)', name='ck_feedback_usage'),
        CheckConstraint(allowed('category', FEEDBACK_CATEGORIES)),
        CheckConstraint(allowed('status', FEEDBACK_STATES)),
        CheckConstraint(allowed('priority', FEEDBACK_PRIORITIES)),
        CheckConstraint("length(btrim(description)) BETWEEN 1 AND 4000 AND length(response) <= 4000 AND revision > 0"),
        CheckConstraint("submission_key ~ '^[0-9a-f]{32}$' AND fingerprint ~ '^[0-9a-f]{64}$'"),
        UniqueConstraint('reporter_id', 'submission_key'),
        Index('ix_feedback_faculty_status', 'faculty_id', 'status', 'id'),
        Index('ix_feedback_reporter_created', 'reporter_id', 'created_at', 'id'),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    room_request_id: Mapped[int | None] = mapped_column(ForeignKey('student_room_request.id'), index=True)
    room_resource_id: Mapped[int | None] = mapped_column(ForeignKey('resource.id'), index=True)
    room_revision: Mapped[int | None] = mapped_column(Integer)
    equipment_reservation_id: Mapped[int | None] = mapped_column(ForeignKey('equipment_reservation.id'), index=True)
    reporter_id: Mapped[int] = mapped_column(ForeignKey('university_user.id'))
    faculty_id: Mapped[int] = mapped_column(ForeignKey('organization_unit.id'))
    assigned_to_id: Mapped[int] = mapped_column(ForeignKey('login_account.user_id'), index=True)
    category: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default='Submitted')
    priority: Mapped[str] = mapped_column(String(10), default='normal')
    response: Mapped[str] = mapped_column(Text, default='')
    revision: Mapped[int] = mapped_column(Integer, default=1)
    submission_key: Mapped[str] = mapped_column(String(32))
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())


class FeedbackEvent(Base):
    __tablename__ = 'feedback_event'
    __table_args__ = (
        UniqueConstraint('report_id', 'action_key'), UniqueConstraint('report_id', 'revision'),
        CheckConstraint("revision > 0 AND length(btrim(message)) BETWEEN 1 AND 4500"),
        CheckConstraint(allowed('status', FEEDBACK_STATES)),
        CheckConstraint("action_key ~ '^[0-9a-f]{32}$' AND fingerprint ~ '^[0-9a-f]{64}$'"),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey('resource_feedback.id'), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey('university_user.id'), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)
    action_key: Mapped[str] = mapped_column(String(32))
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())


class ReservationSeries(Base):
    __tablename__ = 'reservation_series'
    __table_args__ = (
        CheckConstraint('num_nonnulls(room_request_id, borrow_request_id) = 1'),
        CheckConstraint("start_date <= end_date AND end_date-start_date <= 730 AND start_minutes BETWEEN 0 AND 1439 AND duration_minutes BETWEEN 1 AND 525600"),
        CheckConstraint("jsonb_typeof(weekdays) = 'array' AND jsonb_array_length(weekdays) BETWEEN 1 AND 7 AND '[1,2,3,4,5,6,7]'::jsonb @> weekdays"),
        CheckConstraint("submission_key ~ '^[0-9a-f]{32}$' AND fingerprint ~ '^[0-9a-f]{64}$'"),
        CheckConstraint("approval_mode IN ('all','partial')", name='ck_series_approval_mode'),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    room_request_id: Mapped[int | None] = mapped_column(ForeignKey('student_room_request.id'), unique=True)
    borrow_request_id: Mapped[int | None] = mapped_column(ForeignKey('borrow_request.id'), unique=True)
    period_id: Mapped[int | None] = mapped_column(ForeignKey('academic_period.id'), index=True)
    approval_mode: Mapped[str] = mapped_column(String(10), server_default='all')
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    start_minutes: Mapped[int] = mapped_column(Integer)
    duration_minutes: Mapped[int] = mapped_column(Integer)
    weekdays: Mapped[list] = mapped_column(JSONB)
    timezone: Mapped[str] = mapped_column(String(64))
    submission_key: Mapped[str] = mapped_column(String(32), unique=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())


class ReservationOccurrence(Base):
    __tablename__ = 'reservation_occurrence'
    __table_args__ = (
        UniqueConstraint('series_id', 'ordinal'),
        CheckConstraint("ordinal BETWEEN 1 AND 366 AND start_at < end_at AND status IN ('Proposed','Unavailable','Rejected','Reserved','Completed','Cancelled')"),
        ExcludeConstraint(('series_id', '='), ('period', '&&'), using='gist', name='ex_series_self_overlap'),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    series_id: Mapped[int] = mapped_column(ForeignKey('reservation_series.id'), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period: Mapped[object] = mapped_column(TSTZRANGE, Computed("tstzrange(start_at, end_at, '[)')", persisted=True))
    status: Mapped[str] = mapped_column(String(12), default='Proposed')
    explanation: Mapped[str] = mapped_column(Text, server_default="''")
    decided_by: Mapped[int | None] = mapped_column(ForeignKey('login_account.user_id'), index=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReservationPriorityOverride(Base):
    """One immutable audit record for either existing resource-request workflow."""
    __tablename__ = 'reservation_priority_override'
    __table_args__ = (
        CheckConstraint('num_nonnulls(room_request_id, borrow_request_id) = 1'),
        CheckConstraint('original_priority >= 0 AND selected_priority >= 0 AND original_priority <> selected_priority'),
        CheckConstraint('length(btrim(reason)) BETWEEN 1 AND 2000'),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    room_request_id: Mapped[int | None] = mapped_column(ForeignKey('student_room_request.id'), index=True)
    borrow_request_id: Mapped[int | None] = mapped_column(ForeignKey('borrow_request.id'), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey('login_account.user_id'), index=True)
    original_priority: Mapped[int] = mapped_column(Integer)
    selected_priority: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())
    transaction_id: Mapped[int] = mapped_column(BigInteger, server_default=func.txid_current())
