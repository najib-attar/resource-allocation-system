"""Instructor-owned academic reads; no intake, review or allocation authority."""
import re
from sqlalchemy import delete, exists, func, or_, select

from .persistence.models import (AcademicPeriod, Allocation, AllocationRun, ExamDetails,
    LegacyCalendarBinding, LoginAccount, RequestDecision, RequestHistory,
    RequestParticipant, RequestSlot, Resource, ResourceRequest, Role, User, RequestEligibility,
    AllocationEligibility, EligibilityEvent)
from .persistence.repository import state_row, save_request_in_session
from .persistence.validation import DataValidationError, validate_request


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
        current = exists(select(AllocationEligibility.request_id).where(AllocationEligibility.run_id == run_id,
            AllocationEligibility.request_id == ResourceRequest.id,AllocationEligibility.request_revision == ResourceRequest.revision))
        legacy = (RequestEligibility.origin == 'Legacy') & (RequestEligibility.legacy_revision == ResourceRequest.revision)
        return (select(ResourceRequest, Resource, RequestDecision.status, RequestDecision.reason, RequestEligibility).join(Resource,
            Resource.id == ResourceRequest.resource_id).join(RequestEligibility,RequestEligibility.request_id == ResourceRequest.id).outerjoin(RequestDecision,
            (RequestDecision.request_id == ResourceRequest.id) & (RequestDecision.run_id == run_id) & or_(current,legacy))
            .where(ResourceRequest.requester_id == actor, ResourceRequest.type.in_(ACADEMIC_TYPES)))

    def _summary(self, row, resource, status, reason, eligibility):
        return dict(id=row.id, type=row.type, title=row.title, purpose=row.purpose,
            participantCount=row.participant_count, revision=row.revision,
            status=status or 'Pending',
            requestedResource=dict(id=resource.id, name=resource.name),
            decision=dict(status=status, reason=reason) if status else None,
            eligibilityStatus=eligibility.status,eligibilityReason=eligibility.reason,
            reviewVersion=eligibility.version,reviewedRevision=eligibility.reviewed_revision,
            origin=eligibility.origin,facultyDeclaration=row.faculty_declaration)

    def _context(self, run_id, changed):
        return dict(publicationId=run_id, inputsChangedSincePublication=changed,
            eligibilityReviewSupported=True, creationEnabled=True,
            academicNotificationsSupported=False,
            warnings=[
                'Pending is an allocation state. Eligibility review and calendar publication are separate.',
                'Eligibility approval does not reserve resources or guarantee an allocation.',
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
            row, resource, status, reason, eligibility = record
            item = self._summary(row, resource, status, reason, eligibility)
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
            item['canRevise'] = session.scalar(select(Allocation.id).where(Allocation.run_id == run_id,
                Allocation.request_id == key).limit(1)) is None
            item['eligibilityHistory'] = [dict(version=e.version,revision=e.request_revision,status=e.status,
                reason=e.reason,actorId=e.actor_id,createdAt=e.created_at.isoformat()) for e in session.scalars(
                    select(EligibilityEvent).where(EligibilityEvent.request_id == key).order_by(EligibilityEvent.version))]
            item['instructorAttribution'] = row.academic_instructor_id
            item['calendarNote'] = ('Weekly allocations do not establish dated commitments without explicit '
                'academic bindings. Calendar publication and instructor attribution remain administrative metadata.')
            return dict(item=item, **self._context(run_id, changed))

    def directory(self, actor):
        with self.database.transaction(read_only=True) as session:
            self._instructor(session,actor)
            return dict(resources=[dict(id=r.id,name=r.name,type=r.type,capacity=r.capacity,building=r.building,
                available=r.available) for r in session.scalars(select(Resource).order_by(Resource.source_order))],
                participants=[dict(id=u.id,name=u.name) for u in session.scalars(select(User).where(
                    func.lower(User.status)=='active').order_by(User.source_order))])

    def submit(self, actor, values, submission_key=None, key=None, revision=None):
        if not isinstance(values,dict) or set(values)-{'type','spaceId','participantCount','title','purpose','slots',
                'requiredFeature','requiredBuilding','facultyDeclaration','exam','participants'}:
            raise ProfessorRequestError('Use supported academic request fields; identity and review decisions come from the server.')
        if not isinstance(submission_key,str) or not re.fullmatch('[0-9a-f]{32}',submission_key):
            raise ProfessorRequestError('Use a valid submission key. Refresh the form.')
        with self.database.transaction() as session:
            state_row(session,True)
            self._instructor(session,actor)
            item = dict(values,requesterId=actor)
            for field,maximum in (('title',500),('purpose',2000),('facultyDeclaration',500)):
                value=item.get(field,'')
                if not isinstance(value,str) or len(value.strip())>maximum or (field!='facultyDeclaration' and not value.strip()):
                    raise ProfessorRequestError(f'Enter a valid {field} (maximum {maximum} characters).')
                item[field]=value.strip()
            try:
                validate_request(item,set(session.scalars(select(User.id))),set(session.scalars(select(Resource.id))))
            except DataValidationError as error:
                raise ProfessorRequestError(str(error)) from error
            if item['type']=='Exam':
                exam=item['exam']
                if any(not exam.get(k,'').strip() or len(exam[k])>500 for k in ('courseCode','courseName')) or exam.get('examType') not in {'Midterm','Final','Quiz','General'}:
                    raise ProfessorRequestError('Exam requests require declared course code/name and a supported exam type.')
            if item['type']=='CommitteeMeeting':
                people=item.get('participants',[])
                active=set(session.scalars(select(User.id).where(func.lower(User.status)=='active')))
                if not people or any(p['userId'] not in active or len(p.get('role',''))>100 for p in people):
                    raise ProfessorRequestError('Select at least one active required participant with a valid declared role.')
            if key is None:
                prior=session.scalar(select(ResourceRequest).where(ResourceRequest.submission_key==submission_key))
                if prior is not None:
                    meta=session.get(RequestEligibility,prior.id)
                    if prior.requester_id!=actor or meta.origin!='Professor' or meta.submitted_by!=actor:
                        raise PermissionError('This submission key is unavailable.')
                result=save_request_in_session(session,item,submission_key)
                meta=session.get(RequestEligibility,result)
                if prior is None:
                    meta.origin,meta.submitted_by='Professor',actor
                    meta.version+=1
                return result
            if type(key) is not int or type(revision) is not int:
                raise ProfessorRequestError('A current request revision is required.')
            row=session.scalar(select(ResourceRequest).where(ResourceRequest.id==key,ResourceRequest.requester_id==actor).with_for_update())
            if row is None:
                raise PermissionError('This academic request is unavailable or private.')
            if row.revision!=revision:
                raise ProfessorRequestError('The request changed. Refresh before revising.')
            if session.scalar(select(Allocation.id).where(Allocation.run_id==state_row(session).active_run_id,
                    Allocation.request_id==key).limit(1)) is not None:
                raise ProfessorRequestError('Published reservations are read-only. A separately approved replacement workflow is required.')
            for field,attribute in (('type','type'),('spaceId','resource_id'),('participantCount','participant_count'),
                    ('title','title'),('purpose','purpose'),('facultyDeclaration','faculty_declaration'),
                    ('requiredFeature','required_feature'),('requiredBuilding','required_building')):
                setattr(row,attribute,item.get(field,''))
            row.revision+=1
            session.flush()
            for model in (RequestSlot,RequestParticipant,ExamDetails):
                session.execute(delete(model).where(model.request_id==key))
            for ordinal,slot in enumerate(item['slots'],1):
                session.add(RequestSlot(request_id=key,ordinal=ordinal,day=slot['day'],start_minutes=slot['startMinutes'],end_minutes=slot['endMinutes']))
            if item['type']=='Exam':
                exam=item['exam']
                session.add(ExamDetails(request_id=key,course_code=exam['courseCode'],course_name=exam['courseName'],exam_type=exam['examType'],can_split=exam['canSplitAcrossRooms']))
            for ordinal,p in enumerate(item.get('participants',[]),1):
                session.add(RequestParticipant(request_id=key,ordinal=ordinal,user_id=p['userId'],role=p.get('role') or 'Participant'))
            session.add(RequestHistory(request_id=key,kind='revision',message=f'Revised by Instructor {actor}; eligibility review required again.'))
            return key
