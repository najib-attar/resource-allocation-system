"""Human eligibility review, separate from engine decisions and publication."""
from datetime import datetime, timezone
import hashlib
import json

from sqlalchemy import or_, select
from .persistence.models import (Allocation, ApplicationState, EligibilityEvent, LoginAccount,
    RequestDecision, RequestEligibility, RequestHistory, ResourceRequest, Role, User,
    ExamDetails, RequestParticipant, RequestSlot, Resource)
from .persistence.repository import PersistenceError, StaleRun, state_row


class EligibilityError(PersistenceError):
    pass


def administrator(session, actor):
    if type(actor) is not int or session.scalar(select(User.id).join(LoginAccount,
            LoginAccount.user_id == User.id).join(Role,Role.id == User.primary_role_id).where(
            User.id == actor, LoginAccount.enabled.is_(True), User.status.ilike('active'),
            or_(LoginAccount.administrator.is_(True),Role.name == 'Administrator'))) is None:
        raise PermissionError('An active university administrator is required.')


def outstanding_legacy(session):
    return list(session.scalars(select(ResourceRequest.id).join(RequestEligibility,
        RequestEligibility.request_id == ResourceRequest.id).join(RequestDecision,
        RequestDecision.request_id == ResourceRequest.id).join(ApplicationState,
        ApplicationState.active_run_id == RequestDecision.run_id).where(RequestEligibility.origin == 'Legacy',
        or_(RequestEligibility.status == 'Pending Eligibility Review',
            RequestEligibility.reviewed_revision.is_distinct_from(ResourceRequest.revision)))
        .order_by(ResourceRequest.id)))


def assert_legacy_reviewed(session):
    keys = outstanding_legacy(session)
    if keys:
        raise EligibilityError(f'Replacement allocation is blocked: {len(keys)} legacy requests in the current publication need eligibility review. Existing reservations remain unchanged. Open Academic Eligibility Review.')


class PresentationInput(dict):
    def assert_allocation_ready(self):
        raise EligibilityError('Presentation data includes unreviewed requests and cannot be sent to the allocation engine.')


class AllocationInput(dict):
    """Unchanged wire JSON plus a process-local stale/tamper check for DB callers."""
    def __init__(self, data, database, revision):
        super().__init__(data)
        self.database, self.input_revision = database, revision
        self.digest = self._digest()

    def _digest(self):
        return hashlib.sha256(json.dumps(self,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

    def assert_allocation_ready(self):
        if self._digest() != self.digest:
            raise StaleRun('Database allocation input was modified after eligibility validation.')
        with self.database.transaction(read_only=True) as session:
            if state_row(session).input_revision != self.input_revision:
                raise StaleRun('Eligibility or inputs changed before engine execution; retry.')
            assert_legacy_reviewed(session)


class EligibilityService:
    def __init__(self, database):
        self.database = database

    def list_for(self, actor):
        with self.database.transaction(read_only=True) as session:
            administrator(session,actor)
            active = state_row(session).active_run_id
            reserved = set(session.scalars(select(Allocation.request_id).where(Allocation.run_id == active)))
            return dict(outstandingLegacy=outstanding_legacy(session),items=[dict(id=r.id,title=r.title,
                type=r.type,ownerId=r.requester_id,ownerName=u.name,revision=r.revision,status=e.status,
                reviewVersion=e.version,origin=e.origin,reason=e.reason,publishedReservation=r.id in reserved)
                for r,e,u in session.execute(select(ResourceRequest,RequestEligibility,User)
                    .join(RequestEligibility,RequestEligibility.request_id == ResourceRequest.id)
                    .join(User,User.id == ResourceRequest.requester_id).order_by(ResourceRequest.submission_order))])

    def decide(self, actor, key, revision, version, approve, reason):
        if type(key) is not int or key <= 0 or type(revision) is not int or revision <= 0 or type(version) is not int or version < 0 or type(approve) is not bool:
            raise EligibilityError('Use valid request and review revisions.')
        if not isinstance(reason,str) or not 1 <= len(reason.strip()) <= 2000:
            raise EligibilityError('Record a reason between 1 and 2000 characters.')
        with self.database.transaction() as session:
            state_row(session,True)
            administrator(session,actor)
            row = session.get(ResourceRequest,key,with_for_update=True)
            meta = session.get(RequestEligibility,key,with_for_update=True)
            if row is None or meta is None:
                raise EligibilityError('Academic request not found.')
            if row.requester_id == actor:
                raise PermissionError('Another administrator must review your own academic request.')
            if row.revision != revision or meta.version != version:
                raise EligibilityError('This request or eligibility decision changed. Refresh before reviewing.')
            meta.status = 'Eligible' if approve else 'Eligibility Rejected'
            meta.version += 1
            meta.reviewed_revision, meta.reviewer_id = revision, actor
            meta.reason, meta.decided_at = reason.strip(), datetime.now(timezone.utc)
            session.add(RequestHistory(request_id=key,kind='eligibility',
                message=meta.status+': '+meta.reason+' Eligibility does not reserve resources or alter the current publication.'))
            session.flush()
            return meta.status

    def detail(self, actor, key):
        with self.database.transaction(read_only=True) as session:
            administrator(session,actor)
            value=session.execute(select(ResourceRequest,RequestEligibility,User,Resource)
                .join(RequestEligibility,RequestEligibility.request_id==ResourceRequest.id)
                .join(User,User.id==ResourceRequest.requester_id).join(Resource,Resource.id==ResourceRequest.resource_id)
                .where(ResourceRequest.id==key)).first()
            if value is None:raise EligibilityError('Academic request not found.')
            r,e,u,resource=value
            active=state_row(session).active_run_id
            exam=session.get(ExamDetails,key)
            return dict(id=r.id,title=r.title,purpose=r.purpose,type=r.type,ownerId=u.id,ownerName=u.name,
                facultyDeclaration=r.faculty_declaration,count=r.participant_count,resource=resource.name,
                feature=r.required_feature,building=r.required_building,revision=r.revision,reviewVersion=e.version,
                status=e.status,reason=e.reason,origin=e.origin,
                currentAllocationStatus=session.scalar(select(RequestDecision.status).where(RequestDecision.run_id==active,RequestDecision.request_id==key)),
                publishedReservation=session.scalar(select(Allocation.id).where(Allocation.run_id==active,Allocation.request_id==key).limit(1)) is not None,
                slots=[dict(day=s.day,startMinutes=s.start_minutes,endMinutes=s.end_minutes) for s in session.scalars(select(RequestSlot).where(RequestSlot.request_id==key).order_by(RequestSlot.ordinal))],
                exam=dict(courseCode=exam.course_code,courseName=exam.course_name,examType=exam.exam_type,canSplitAcrossRooms=exam.can_split) if exam else None,
                participants=[dict(name=person.name,role=p.role) for p,person in session.execute(select(RequestParticipant,User).join(User,User.id==RequestParticipant.user_id).where(RequestParticipant.request_id==key).order_by(RequestParticipant.ordinal))])

    def history(self, actor, key):
        with self.database.transaction(read_only=True) as session:
            administrator(session,actor)
            return [dict(version=e.version,revision=e.request_revision,status=e.status,reason=e.reason,
                actorId=e.actor_id,createdAt=e.created_at.isoformat()) for e in session.scalars(
                    select(EligibilityEvent).where(EligibilityEvent.request_id == key).order_by(EligibilityEvent.version))]
