"""Read-only administration composition; source services retain every mutation.

Operational records keep the current faculty/custodian scopes. Every response is
one PostgreSQL repeatable-read snapshot; returned rows are bounded in SQL.
"""
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import and_, func, or_, select

from .academic_eligibility import administrator, outstanding_legacy_query
from .calendar_service import university_zone
from .equipment_access import custodian_faculties
from .feedback_access import managed_scope, room_faculties
from .notification_service import _visible
from .persistence.models import (Allocation, AllocationRun, BorrowRequest, EquipmentUnit,
    EquipmentType, RequestDecision, RequestEligibility, Resource, ResourceFeedback,
    OrganizationUnit, ResourceRequest, StudentRoomRequest, User, WaitingListEntry)
from .persistence.repository import state_row


class AdminDashboardService:
    LIMIT = 5
    DOMAINS = ('allocation', 'rooms', 'equipment', 'waiting', 'issues')
    QUEUES = ('all', 'academic', 'rooms', 'equipment', 'waiting', 'issues')

    def __init__(self, database):
        self.database = database

    @staticmethod
    def _count(session, query):
        return session.scalar(select(func.count()).select_from(query.order_by(None).subquery()))

    @staticmethod
    def _scopes(actor):
        return {
            'rooms': StudentRoomRequest.faculty_id.in_(room_faculties(actor)),
            'equipment': BorrowRequest.faculty_id.in_(custodian_faculties(actor)),
            'waiting': or_(and_(WaitingListEntry.room_request_id.is_not(None),
                               WaitingListEntry.faculty_id.in_(room_faculties(actor))),
                           and_(WaitingListEntry.borrow_request_id.is_not(None),
                                WaitingListEntry.faculty_id.in_(custodian_faculties(actor)))),
            'issues': managed_scope(actor),
        }

    def load(self, actor, queue='all'):
        if queue not in self.QUEUES:
            raise ValueError('Choose a supported action queue.')
        with self.database.transaction(read_only=True) as session:
            administrator(session, actor)
            state = state_row(session)
            scopes = self._scopes(actor)
            # A queued parent is reviewed through WaitingListService, not the
            # ordinary approval action. Do not count it as two pending decisions.
            room_waiting = select(WaitingListEntry.room_request_id).where(
                WaitingListEntry.room_request_id.is_not(None),
                WaitingListEntry.status.in_(('Pending Review', 'Preapproved')))
            equipment_waiting = select(WaitingListEntry.borrow_request_id).where(
                WaitingListEntry.borrow_request_id.is_not(None),
                WaitingListEntry.status.in_(('Pending Review', 'Preapproved')))
            definitions = {
                'academic': (select(ResourceRequest.id, ResourceRequest.title.label('title'),
                    RequestEligibility.status).join(RequestEligibility,
                    RequestEligibility.request_id == ResourceRequest.id).where(
                    RequestEligibility.status == 'Pending Eligibility Review',
                    ResourceRequest.requester_id != actor), 'eligibility.detail', 'request_id'),
                'rooms': (select(StudentRoomRequest.id, StudentRoomRequest.purpose.label('title'),
                    StudentRoomRequest.status).where(scopes['rooms'],
                    StudentRoomRequest.approver_id == actor,
                    StudentRoomRequest.status == 'Pending Faculty Approval',
                    StudentRoomRequest.id.not_in(room_waiting)), 'rooms.detail', 'request_id'),
                'equipment': (select(BorrowRequest.id, BorrowRequest.purpose.label('title'),
                    BorrowRequest.status).where(scopes['equipment'],
                    BorrowRequest.status == 'Pending Approval', BorrowRequest.id.not_in(equipment_waiting)),
                    'equipment.detail', 'request_id'),
                'waiting': (select(WaitingListEntry.id,
                    WaitingListEntry.explanation.label('title'), WaitingListEntry.status).where(
                    scopes['waiting'], WaitingListEntry.status == 'Pending Review'), 'waiting.detail', 'entry_id'),
                'issues': (select(ResourceFeedback.id, ResourceFeedback.category.label('title'),
                    ResourceFeedback.status).where(scopes['issues'],
                    ResourceFeedback.status.in_(('Submitted', 'Under Review'))), 'feedback.detail', 'report_id'),
            }
            queues = {}
            for key, (query, endpoint, parameter) in definitions.items():
                queues[key] = dict(count=self._count(session, query), endpoint=endpoint, parameter=parameter,
                    items=[dict(row) for row in session.execute(query.order_by(query.selected_columns.id)
                        .limit(self.LIMIT)).mappings()] if queue in ('all', key) else [])
            legacy = outstanding_legacy_query()
            run = session.execute(select(AllocationRun.id, AllocationRun.strategy,
                AllocationRun.created_at, AllocationRun.input_revision).where(
                AllocationRun.id == state.active_run_id)).first() if state.active_run_id else None
            visible = _visible(actor)
            return dict(name=session.get(User, actor).name, queue=queue, queues=queues,
                legacyOutstanding=self._count(session, legacy), strategy=state.strategy,
                activeRun=dict(id=run.id, strategy=run.strategy, created=run.created_at,
                    inputsChanged=run.input_revision != state.input_revision) if run else None,
                allocationStates=dict(session.execute(select(RequestDecision.status, func.count()).where(
                    RequestDecision.run_id == state.active_run_id).group_by(RequestDecision.status)).all()),
                runs=[dict(id=r.id, strategy=r.strategy, status=r.status, created=r.created_at)
                    for r in session.execute(select(AllocationRun.id, AllocationRun.strategy, AllocationRun.status,
                        AllocationRun.created_at).order_by(AllocationRun.id.desc()).limit(self.LIMIT))],
                unread=session.scalar(select(func.count()).select_from(visible).where(visible.c.read_at.is_(None))),
                inventories=[dict(id=key, name=name) for key, name in session.execute(select(
                    OrganizationUnit.id, OrganizationUnit.name).where(
                    OrganizationUnit.id.in_(custodian_faculties(actor))).order_by(OrganizationUnit.id).limit(20))],
                resources=session.scalar(select(func.count()).select_from(Resource)),
                equipmentUnits=session.scalar(select(func.count()).select_from(EquipmentUnit).join(
                    EquipmentType, EquipmentType.id == EquipmentUnit.type_id).where(
                    EquipmentType.faculty_id.in_(custodian_faculties(actor)))))

    def report(self, actor, domain='allocation', start=None, end=None, now=None):
        """Current statuses of records whose documented source date is in range.

        These are not historic occupancy percentages or status-at-that-date claims.
        No exports, private appointment data or inferred utilization is returned.
        """
        if domain not in self.DOMAINS:
            raise ValueError('Choose a supported report domain.')
        today = (now or datetime.now(timezone.utc)).astimezone(university_zone()).date()
        try:
            first = date.fromisoformat(start) if start else today - timedelta(days=29)
            last = date.fromisoformat(end) if end else today
        except (TypeError, ValueError) as error:
            raise ValueError('Choose valid report dates.') from error
        if not 0 <= (last - first).days < 366:
            raise ValueError('Choose an ordered report period of at most 366 days.')
        models = {
            'allocation': (AllocationRun, AllocationRun.created_at, 'Run creation date'),
            'rooms': (StudentRoomRequest, StudentRoomRequest.start_at, 'Requested start date'),
            'equipment': (BorrowRequest, BorrowRequest.start_at, 'Requested collection date'),
            'waiting': (WaitingListEntry, WaitingListEntry.accepted_at, 'Queue entry date'),
            'issues': (ResourceFeedback, ResourceFeedback.created_at, 'Report submission date'),
        }
        model, column, basis = models[domain]
        try:
            lower = datetime.combine(first, time.min, university_zone())
            upper = datetime.combine(last + timedelta(days=1), time.min, university_zone())
        except OverflowError as error:
            raise ValueError('Choose report dates before the end of year 9999.') from error
        query = select(model.status.label('status')).where(column >= lower, column < upper)
        with self.database.transaction(read_only=True) as session:
            administrator(session, actor)
            if domain != 'allocation':
                query = query.where(self._scopes(actor)[domain])
            rows = query.subquery()
            states = dict(session.execute(select(rows.c.status, func.count()).group_by(rows.c.status)
                .order_by(rows.c.status)).all())
            return dict(domain=domain, start=first.isoformat(), end=last.isoformat(), basis=basis,
                timezone=university_zone().key, states=states, total=sum(states.values()),
                scope='Campus academic runs' if domain == 'allocation' else 'Your currently assigned faculties only')

    def run_detail(self, actor, key, page=1, allocation_page=1):
        if (type(key) is not int or not 0 < key <= 9223372036854775807
                or type(page) is not int or not 1 <= page <= 10000
                or type(allocation_page) is not int or not 1 <= allocation_page <= 10000):
            raise ValueError('Choose a valid allocation run and page.')
        with self.database.transaction(read_only=True) as session:
            administrator(session, actor)
            run = session.execute(select(AllocationRun.id, AllocationRun.status, AllocationRun.strategy,
                AllocationRun.created_at).where(AllocationRun.id == key)).first()
            if run is None:
                raise LookupError('Allocation run not found.')
            query = select(RequestDecision.request_id, RequestDecision.status, RequestDecision.reason).where(
                RequestDecision.run_id == key).order_by(RequestDecision.ordinal)
            decisions = list(session.execute(query.limit(50).offset((page - 1) * 50)))
            allocated = select(Allocation.id).where(Allocation.run_id == key)
            rooms = [dict(requestId=a.request_id, name=name, day=a.day, start=a.start_minutes,
                end=a.end_minutes) for a, name in session.execute(select(Allocation, Resource.name).join(
                Resource, Resource.id == Allocation.resource_id).where(Allocation.run_id == key)
                .order_by(Allocation.id).limit(100).offset((allocation_page - 1) * 100))]
            return dict(id=key, status=run.status, strategy=run.strategy, created=run.created_at,
                active=state_row(session).active_run_id == key, page=page,
                total=self._count(session, query), allocations=rooms, allocationPage=allocation_page,
                allocationTotal=self._count(session, allocated),
                decisions=[dict(id=d.request_id, status=d.status, reason=d.reason) for d in decisions])
