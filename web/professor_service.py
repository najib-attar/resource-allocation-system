"""Instructor-owned academic reads; no intake, review or allocation authority."""
from sqlalchemy import func, select

from .persistence.models import (AcademicPeriod, Allocation, AllocationRun, ExamDetails,
    LegacyCalendarBinding, LoginAccount, RequestDecision, RequestHistory,
    RequestParticipant, RequestSlot, Resource, ResourceRequest, Role, User)
from .persistence.repository import state_row


ACADEMIC_TYPES = {'Exam', 'OneTime', 'Recurring', 'CommitteeMeeting'}
STATUSES = {'Pending', 'Approved', 'Rejected'}


class ProfessorRequestError(ValueError):
    pass


class ProfessorService:
    def __init__(self, database):
        self.database = database

    def _instructor(self, session, actor):
        if type(actor) is not int or actor <= 0 or session.scalar(select(User.id)
                .join(Role, Role.id == User.primary_role_id)
                .join(LoginAccount, LoginAccount.user_id == User.id)
                .where(User.id == actor, Role.name == 'Instructor',
                       func.lower(User.status) == 'active', LoginAccount.enabled.is_(True))) is None:
            raise PermissionError('An active Instructor account is required.')

    def _publication(self, session):
        state = state_row(session)
        run = session.execute(select(AllocationRun.id, AllocationRun.input_revision)
            .where(AllocationRun.id == state.active_run_id, AllocationRun.status == 'success')).first()
        return (run.id if run else None), bool(run and run.input_revision != state.input_revision)

    def _query(self, actor, run_id):
        return (select(ResourceRequest, Resource, RequestDecision.status, RequestDecision.reason).join(Resource,
            Resource.id == ResourceRequest.resource_id).outerjoin(RequestDecision,
            (RequestDecision.request_id == ResourceRequest.id) & (RequestDecision.run_id == run_id))
            .where(ResourceRequest.requester_id == actor, ResourceRequest.type.in_(ACADEMIC_TYPES)))

    def _summary(self, row, resource, status, reason):
        return dict(id=row.id, type=row.type, title=row.title, purpose=row.purpose,
            participantCount=row.participant_count, revision=row.revision,
            status=status or 'Pending',
            requestedResource=dict(id=resource.id, name=resource.name),
            decision=dict(status=status, reason=reason) if status else None)

    def _context(self, run_id, changed):
        return dict(publicationId=run_id, inputsChangedSincePublication=changed,
            eligibilityReviewSupported=False, creationEnabled=False,
            academicNotificationsSupported=False,
            warnings=[
                'Pending means no decision in the active allocation publication; it is not eligibility approval.',
                'Professor academic intake is blocked until an administrative review gate is approved and implemented.',
                'Course and activity metadata are declarations, not verified teaching affiliations.',
                *(['Inputs have changed since the active allocation publication.'] if changed else [])])

    def list_for(self, actor, request_type='', status='', limit=50, offset=0):
        if request_type and request_type not in ACADEMIC_TYPES:
            raise ProfessorRequestError('Choose Exam, OneTime, Recurring or CommitteeMeeting.')
        if status and status not in STATUSES:
            raise ProfessorRequestError('Choose Pending, Approved or Rejected.')
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or not 0 <= offset <= 2147483647:
            raise ProfessorRequestError('Use a limit from 1 to 100 and a nonnegative offset.')
        with self.database.transaction(read_only=True) as session:
            self._instructor(session, actor)
            run_id, changed = self._publication(session)
            query = self._query(actor, run_id)
            if request_type:
                query = query.where(ResourceRequest.type == request_type)
            if status:
                query = query.where(func.coalesce(RequestDecision.status, 'Pending') == status)
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            items = [self._summary(*row) for row in session.execute(query.order_by(
                ResourceRequest.submission_order.desc()).limit(limit).offset(offset))]
            return dict(items=items, total=total, limit=limit, offset=offset,
                        **self._context(run_id, changed))

    def detail(self, actor, key):
        if type(key) is not int or not 0 < key <= 2147483647:
            raise ProfessorRequestError('Choose a valid academic request.')
        with self.database.transaction(read_only=True) as session:
            self._instructor(session, actor)
            run_id, changed = self._publication(session)
            record = session.execute(self._query(actor, run_id).where(ResourceRequest.id == key)).first()
            if record is None:
                raise PermissionError('This academic request is unavailable or private.')
            row, resource, status, reason = record
            item = self._summary(row, resource, status, reason)
            item.update(requiredFeature=row.required_feature, requiredBuilding=row.required_building,
                slots=[dict(day=s.day, startMinutes=s.start_minutes, endMinutes=s.end_minutes)
                       for s in session.scalars(select(RequestSlot).where(RequestSlot.request_id == key)
                                               .order_by(RequestSlot.ordinal))])
            exam = session.get(ExamDetails, key)
            item['examDeclaration'] = dict(courseCode=exam.course_code, courseName=exam.course_name,
                examType=exam.exam_type, canSplitAcrossRooms=exam.can_split) if exam else None
            item['participants'] = [dict(id=person.id, name=person.name, declaredRole=participant.role)
                for participant, person in session.execute(select(RequestParticipant, User).join(User,
                    User.id == RequestParticipant.user_id).where(RequestParticipant.request_id == key)
                    .order_by(RequestParticipant.ordinal))]
            item['allocations'] = [dict(resourceId=allocated.id, resourceName=allocated.name,
                building=allocated.building, day=a.day, startMinutes=a.start_minutes,
                endMinutes=a.end_minutes, assignedParticipants=a.assigned_participants)
                for a, allocated in session.execute(select(Allocation, Resource).join(Resource,
                    Resource.id == Allocation.resource_id).where(Allocation.run_id == run_id,
                    Allocation.request_id == key).order_by(Allocation.engine_id))] if status else []
            item['history'] = [dict(kind=h.kind, message=h.message, createdAt=h.created_at.isoformat())
                for h in session.scalars(select(RequestHistory).where(RequestHistory.request_id == key)
                                        .order_by(RequestHistory.created_at, RequestHistory.id))]
            item['academicBindings'] = [dict(period=period.name, startDate=period.start_date.isoformat(),
                endDate=period.end_date.isoformat(), timezone=period.timezone,
                weekStart=binding.week_start.isoformat() if binding.week_start else None,
                excludedDates=binding.excluded_dates)
                for binding, period in session.execute(select(LegacyCalendarBinding, AcademicPeriod)
                    .join(AcademicPeriod, AcademicPeriod.id == LegacyCalendarBinding.period_id)
                    .where(LegacyCalendarBinding.request_id == key).order_by(LegacyCalendarBinding.id))]
            item['calendarPublic'] = row.calendar_public
            item['instructorAttribution'] = row.academic_instructor_id
            item['calendarNote'] = ('Weekly allocations do not establish dated commitments without explicit '
                'academic bindings. Calendar publication and instructor attribution remain administrative metadata.')
            return dict(item=item, **self._context(run_id, changed))
