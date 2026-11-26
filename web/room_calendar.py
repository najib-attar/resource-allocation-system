"""Explicit dated projections and publication integrity, not room-selection rules."""

import uuid
from sqlalchemy import select

from .calendar_service import CalendarError, commitment_models, epoch, expand_weekly, legacy_intervals
from .persistence.models import (AcademicPeriod, Allocation, CalendarBlock,
    FacultyRoomApprover, LegacyCalendarBinding, LoginAccount, Resource,
    RoomAccess, RoomClosure, RoomOrganizerCommitment, RoomPolicy, RoomReservation, Role, User)
from .persistence.repository import state_row
from .teaching_calendar import overlaps_intervals, teaching_room_bounds, teaching_room_intervals


def valid_approvers(session):
    query = select(FacultyRoomApprover, LoginAccount, User, Role).join(
        LoginAccount, LoginAccount.user_id == FacultyRoomApprover.user_id).join(
        User, User.id == LoginAccount.user_id).join(Role, Role.id == User.primary_role_id)
    return {row.faculty_id: row.user_id for row, account, user, role in session.execute(query)
            if account.enabled and user.status.casefold() == 'active' and role.name != 'Student'
            and (role.name in {'Staff', 'Administrator'} or account.administrator)}


def academic_room_intervals(session, room_ids, start, end, run_id):
    if run_id is None or not room_ids:
        return [], set()
    allocations = list(session.scalars(select(Allocation).where(Allocation.run_id == run_id, Allocation.resource_id.in_(room_ids))))
    request_ids = {row.request_id for row in allocations}
    choices = {}
    for binding, period in session.execute(select(LegacyCalendarBinding, AcademicPeriod).join(
            AcademicPeriod, AcademicPeriod.id == LegacyCalendarBinding.period_id).where(LegacyCalendarBinding.request_id.in_(request_ids))):
        choices.setdefault(binding.request_id, []).append((binding, period))
    values, unresolved = [], set()
    for row in allocations:
        if row.request_id not in choices:
            unresolved.add(row.resource_id)
            continue
        for binding, period in choices[row.request_id]:
            values.extend({'resourceId': row.resource_id, 'start': epoch(a), 'end': epoch(b)} for a, b in
                expand_weekly(row.day, row.start_minutes, row.end_minutes, period.start_date, period.end_date,
                              period.timezone, start, end, binding.excluded_dates, binding.week_start))
    return values, unresolved


def person_busy(session, actor, start, end, active_run, exclude_request=None):
    intervals, unresolved = legacy_intervals(session, [actor], start, end, active_run)
    values = [{'start': row['start'], 'end': row['end']} for row in intervals]
    for model in (CalendarBlock, *commitment_models(session)):
        query = select(model).where(model.user_id == actor, model.start_at < end, model.end_at > start)
        if model is RoomOrganizerCommitment and exclude_request is not None:
            query = query.where(model.request_id != exclude_request)
        values.extend({'start': epoch(row.start_at), 'end': epoch(row.end_at)} for row in session.scalars(query))
    return values, not unresolved


def room_usage_intervals(session, room_ids, start, end, active_run_id, exclude_request=None):
    """One anonymous occupied-interval projection for scheduling and room pages."""
    busy, unresolved = academic_room_intervals(session, room_ids, start, end, active_run_id)
    busy.extend(teaching_room_intervals(session, room_ids, start, end))
    for model in (RoomClosure, RoomReservation):
        query = select(model).where(model.resource_id.in_(room_ids), model.start_at < end, model.end_at > start)
        if model is RoomReservation and exclude_request is not None:
            query = query.where(model.request_id != exclude_request)
        busy.extend({"resourceId": row.resource_id, "start": epoch(row.start_at), "end": epoch(row.end_at)}
                    for row in session.scalars(query))
    return busy, unresolved


def room_snapshot(session, actor, role, values, horizon, strategy='best_fit', selected=None,
                  action='recommend', exclude_request=None):
    state = state_row(session)
    start, end = horizon
    rooms = list(session.scalars(select(Resource).order_by(Resource.source_order, Resource.id)))
    policies = {row.resource_id: row for row in session.scalars(select(RoomPolicy))}
    approvers = valid_approvers(session)
    whitelist = {}
    for row in session.scalars(select(RoomAccess)):
        whitelist.setdefault(row.resource_id, []).append(row.user_id)
    busy, unresolved = room_usage_intervals(session, [row.id for row in rooms], start, end, state.active_run_id,
                                         exclude_request)
    grouped = {}
    for row in busy:
        grouped.setdefault(row['resourceId'], []).append({'start': row['start'], 'end': row['end']})
    person, resolved = person_busy(session, actor, start, end, state.active_run_id, exclude_request)
    payload = []
    for row in rooms:
        policy = policies.get(row.id)
        payload.append({'id': row.id, 'name': row.name, 'type': row.type, 'capacity': row.capacity,
                        'building': row.building, 'available': row.available,
                        'features': {'projector': row.projector, 'whiteboard': row.whiteboard, 'computers': row.computers},
                        'facultyId': policy.faculty_id if policy else 0, 'approverId': approvers.get(policy.faculty_id, 0) if policy else 0,
                        'enabled': bool(policy and policy.enabled), 'restricted': bool(policy and policy.restricted),
                        'allowedUserIds': whitelist.get(row.id, []), 'categories': policy.categories if policy else [],
                        'calendarResolved': row.id not in unresolved, 'busy': grouped.get(row.id, [])})
    snapshot = {'protocolVersion': 1, 'operation': 'studentRoom', 'runId': uuid.uuid4().hex, 'action': action,
                'strategy': strategy, 'organizerId': actor, 'organizerRole': role,
                'attendeeCount': values['count'], 'category': values['category'], 'requiredFeatures': values['features'],
                'preferredFacultyId': values.get('faculty') or 0, 'preferredBuilding': values.get('building', ''),
                'organizerResolved': resolved, 'organizerBusy': person,
                'proposed': {'start': epoch(values['start']), 'end': epoch(values['end'])},
                'horizon': {'start': epoch(start), 'end': epoch(end)}, 'rooms': payload}
    if selected is not None:
        snapshot['selectedRoomId'] = selected
    return snapshot, state.calendar_revision


def assert_room_publication(session, run_id):
    """Final exclusivity gate under the same lock as approval; shared exams stay valid."""
    if run_id is None:
        return
    protected = [row for model in (RoomReservation, RoomClosure) for row in session.scalars(select(model))]
    if protected:
        values, unresolved = academic_room_intervals(session, {row.resource_id for row in protected},
            min(row.start_at for row in protected), max(row.end_at for row in protected), run_id)
        if unresolved:
            raise CalendarError('Academic room allocations have unresolved dates for reserved/closed rooms. Configure explicit calendar bindings before publishing.')
        dated = [{"resourceId": row.resource_id, "start": row.start_at.timestamp(), "end": row.end_at.timestamp()}
                 for row in protected]
        if overlaps_intervals(values, dated, "resourceId"):
            raise CalendarError('Academic allocation conflicts with a confirmed student room reservation or closure. Previous results remain active.')

    room_ids, start, end = teaching_room_bounds(session,
        select(Allocation.resource_id).where(Allocation.run_id == run_id))
    if not room_ids:
        return
    values, unresolved = academic_room_intervals(session, room_ids, start, end, run_id)
    if unresolved:
        raise CalendarError('Academic room allocations have unresolved dates for rooms with published teaching. Configure explicit calendar bindings before publishing.')
    if overlaps_intervals(values, teaching_room_intervals(session, room_ids, start, end), "resourceId"):
        raise CalendarError('Academic allocation conflicts with published teaching. Previous results remain active.')
