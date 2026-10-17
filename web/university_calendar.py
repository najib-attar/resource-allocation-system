"""Read-only, permission-scoped calendar projections; never scheduling decisions."""

import calendar
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import and_, or_, select

from .calendar_service import CalendarError, aware, expand_weekly, local_instant, university_zone
from .equipment_access import custodian_faculties
from .persistence.models import (AcademicPeriod, Allocation, Appointment, AppointmentInvitation,
    AppointmentProfessor, BorrowItem, BorrowRequest, BusySlot, CalendarBlock, EquipmentReservation,
    EquipmentUnit, LegacyCalendarBinding, LoginAccount, RequestHistory,
    RequestParticipant, Resource, ResourceRequest, Role, RoomInvitation, StudentRoomRequest, User)
from .persistence.repository import state_row
from .room_calendar import valid_approvers


CATEGORIES = {'academic': 'Academic / university', 'appointment': 'Appointments', 'room': 'Room activities',
              'equipment': 'Equipment reminders', 'personal': 'Personal blocks'}
STATES = {'pending': 'Pending', 'confirmed': 'Confirmed', 'completed': 'Completed', 'cancelled': 'Cancelled',
          'rejected': 'Declined / rejected', 'overdue': 'Overdue'}
SCOPES = {'relevant': 'My activities and assigned responsibilities', 'personal': 'My activities only',
          'published': 'Published academic schedule (not enrollment)'}


def selection(view='month', day=None, now=None):
    zone = university_zone()
    now = aware(now or datetime.now(timezone.utc))
    try:
        selected = date.fromisoformat(day) if day is not None else now.astimezone(zone).date()
        if view not in {'month', 'week', 'day'} or not 1970 <= selected.year <= 2099:
            raise ValueError()
    except (ValueError, TypeError) as error:
        raise CalendarError('Choose month, week or day and a valid date between 1970 and 2099.') from error
    if view == 'month':
        dates = [d for week in calendar.Calendar().monthdatescalendar(selected.year, selected.month) for d in week]
        title = selected.strftime('%B %Y')
    else:
        first = selected - timedelta(days=selected.weekday()) if view == 'week' else selected
        dates = [first + timedelta(days=n) for n in range(7 if view == 'week' else 1)]
        title = (dates[0].strftime('%d %b') + ' - ' + dates[-1].strftime('%d %b %Y')) if view == 'week' else selected.strftime('%A %d %B %Y')

    def adjacent(direction):
        if view == 'month':
            index = selected.year * 12 + selected.month - 1 + direction
            year, month = divmod(index, 12)
            result = date(year, month + 1, min(selected.day, calendar.monthrange(year, month + 1)[1]))
        else:
            result = selected + timedelta(days=direction * (7 if view == 'week' else 1))
        return result if 1970 <= result.year <= 2099 else None

    return {'view': view, 'date': selected, 'today': now.astimezone(zone).date(), 'now': now,
            'title': title, 'dates': dates, 'previous': adjacent(-1), 'next': adjacent(1), 'zone': zone.key,
            'start': local_instant(datetime.combine(dates[0], time()), zone, check_range=False),
            'end': local_instant(datetime.combine(dates[-1] + timedelta(days=1), time()), zone, check_range=False)}


def _filters(values, choices):
    if values is None:
        return set(choices)
    if not isinstance(values, (list, tuple, set)) or any(value not in choices for value in values):
        raise CalendarError('Choose recognized calendar categories and statuses.')
    return set(values)


def _identity(session, actor):
    if type(actor) is not int or actor <= 0:
        raise PermissionError('An active university account is required.')
    row = session.execute(select(User, LoginAccount, Role).join(LoginAccount, LoginAccount.user_id == User.id)
        .join(Role, Role.id == User.primary_role_id).where(User.id == actor, LoginAccount.enabled.is_(True))).first()
    if row is None or row[0].status.casefold() != 'active':
        raise PermissionError('An active university account is required.')
    return row[1].administrator or row[2].name == 'Administrator'


class UniversityCalendarService:
    EVENT_LIMIT = 5000

    def __init__(self, database):
        self.database = database

    def load(self, actor, view='month', day=None, categories=None, states=None, scope='relevant', now=None):
        selected = selection(view, day, now)
        categories, states = _filters(categories, CATEGORIES), _filters(states, STATES)
        if scope not in SCOPES:
            raise CalendarError('Choose a recognized calendar audience.')
        with self.database.transaction(read_only=True) as session:
            admin = _identity(session, actor)
            events, warnings = self._read(session, actor, selected, categories, scope)
            if len(events) > self.EVENT_LIMIT:
                raise CalendarError('Too many calendar entries. Choose a narrower view, category or audience.')
        events = [event for event in events if event['state'] in states]
        events.sort(key=lambda event: (event['start'], event['category'], event['id']))
        days = []
        zone = university_zone()
        for day in selected['dates']:
            first = local_instant(datetime.combine(day, time()), zone, check_range=False)
            last = local_instant(datetime.combine(day + timedelta(days=1), time()), zone, check_range=False)
            entries = [e for e in events if (first <= e['start'] < last if e['end'] is None else e['start'] < last and e['end'] > first)]
            days.append({'date': day, 'entries': entries, 'outsideMonth': day.month != selected['date'].month})
        return {**selected, 'days': days, 'events': events, 'warnings': sorted(warnings), 'categories': categories,
                'states': states, 'scope': scope, 'administrator': admin,
                'rows': self._hours(days) if view != 'month' else [],
                'categoryOptions': CATEGORIES, 'stateOptions': STATES, 'scopeOptions': SCOPES}

    @staticmethod
    def _hours(days):
        first, last = 8, 18
        for day in days:
            for event in day['entries']:
                first = min(first, event['start'].hour if event['start'].date() == day['date'] else 0)
                end = event['end'] or event['start'] + timedelta(minutes=1)
                last = max(last, min(24, end.hour + bool(end.minute or end.second)) if end.date() == day['date'] else 24)
        result = []
        for hour in range(first, last):
            cells = []
            for day in days:
                entries = [e for e in day['entries'] if
                    (e['start'].date() == day['date'] and e['start'].hour == hour) or
                    (e['end'] is not None and e['start'].date() <= day['date'] <= e['end'].date() and
                     e['start'] < datetime.combine(day['date'], time(), e['start'].tzinfo) + timedelta(hours=hour+1) and
                     e['end'] > datetime.combine(day['date'], time(), e['start'].tzinfo) + timedelta(hours=hour))]
                cells.append(entries)
            result.append({'label': f'{hour:02d}:00', 'cells': cells})
        return result

    def _read(self, session, actor, selected, categories, scope):
        events, warnings = [], set()
        start, end, now = selected['start'], selected['end'], selected['now']
        zone = university_zone()

        def add(key, category, title, a, b, status, url, *, busy=False, note='', location='', state=None):
            a, b = aware(a), aware(b) if b is not None else None
            if not (start <= a < end if b is None else a < end and b > start):
                return
            normalized = state or ('pending' if status in {'Pending Approval', 'Pending Faculty Approval', 'Needs Revision'} else
                'cancelled' if status == 'Cancelled' else 'rejected' if status in {'Declined', 'Rejected'} else
                'completed' if status == 'Returned' or (b is not None and b <= now and status in {'Confirmed', 'Approved'}) else 'confirmed')
            events.append({'id': key, 'category': category, 'title': title, 'start': a.astimezone(zone),
                'end': b.astimezone(zone) if b is not None else None, 'status': status, 'state': normalized,
                'label': STATES[normalized], 'url': url, 'busy': busy and normalized == 'confirmed',
                'note': note, 'location': location, 'reminder': b is None})

        if 'academic' in categories:
            self._academic(session, actor, start, end, scope == 'published', add, warnings)
        if scope == 'published':
            return events, warnings
        if 'appointment' in categories:
            permitted = or_(Appointment.organizer_id == actor,
                Appointment.id.in_(select(AppointmentProfessor.appointment_id).where(AppointmentProfessor.user_id == actor)),
                Appointment.id.in_(select(AppointmentInvitation.appointment_id).where(AppointmentInvitation.user_id == actor)))
            rows = list(session.scalars(select(Appointment).where(permitted, Appointment.start_at < end, Appointment.end_at > start)))
            professors, invited = {}, {}
            for professor in session.scalars(select(AppointmentProfessor).where(AppointmentProfessor.appointment_id.in_([r.id for r in rows]))):
                professors.setdefault(professor.appointment_id, []).append(professor)
            for invitation in session.scalars(select(AppointmentInvitation).where(AppointmentInvitation.user_id == actor,
                    AppointmentInvitation.appointment_id.in_([r.id for r in rows]))):
                invited[invitation.appointment_id] = invitation.status
            for row in rows:
                required = professors.get(row.id, [])
                mandatory = row.organizer_id == actor or any(p.user_id == actor for p in required)
                approved = sum(p.decision == 'Approved' and p.revision == row.revision for p in required)
                note = f'{approved}/{len(required)} professors approved revision {row.revision}.'
                if not mandatory:
                    note += ' Optional invitation: ' + invited[row.id] + '; not a personal reservation.'
                add('appointment:'+str(row.id), 'appointment', row.purpose, row.start_at, row.end_at, row.status,
                    '/appointments/'+str(row.id), busy=mandatory and row.status == 'Confirmed', note=note,
                    state='rejected' if not mandatory and invited[row.id] == 'Declined' else None)
        if 'room' in categories:
            managed = [fid for fid, uid in valid_approvers(session).items() if uid == actor] if scope == 'relevant' else []
            invited_ids = select(RoomInvitation.request_id).where(RoomInvitation.user_id == actor)
            permitted = or_(StudentRoomRequest.organizer_id == actor, StudentRoomRequest.id.in_(invited_ids),
                and_(StudentRoomRequest.approver_id == actor, StudentRoomRequest.faculty_id.in_(managed)))
            query = select(StudentRoomRequest, Resource).join(Resource, Resource.id == StudentRoomRequest.resource_id).where(
                permitted, StudentRoomRequest.start_at < end, StudentRoomRequest.end_at > start)
            invitations = dict(session.execute(select(RoomInvitation.request_id, RoomInvitation.status)
                .where(RoomInvitation.user_id == actor)).all())
            for row, room in session.execute(query):
                own = row.organizer_id == actor
                add('room:'+str(row.id), 'room', row.purpose, row.start_at, row.end_at, row.status,
                    '/rooms/'+str(row.id), busy=own and row.status == 'Confirmed',
                    location=room.name+' - '+room.building,
                    note='Organizer booking.' if own else 'Assigned review or optional invitation; not a personal reservation.',
                    state='rejected' if not own and invitations.get(row.id) == 'Declined' else None)
        if 'equipment' in categories:
            self._equipment(session, actor, start, end, scope, now, add)
        if 'personal' in categories:
            for row in session.scalars(select(CalendarBlock).where(CalendarBlock.user_id == actor,
                    CalendarBlock.start_at < end, CalendarBlock.end_at > start)):
                add('block:'+str(row.id), 'personal', row.reason or 'Personal block', row.start_at, row.end_at,
                    'Confirmed', '/appointments/calendar', busy=True, note='Own unavailable interval.')
        return events, warnings

    def _academic(self, session, actor, start, end, published, add, warnings):
        run_id = state_row(session).active_run_id
        scope = ResourceRequest.calendar_public.is_(True) if published else or_(ResourceRequest.requester_id == actor,
            ResourceRequest.id.in_(select(RequestParticipant.request_id).where(RequestParticipant.user_id == actor)))
        rows = list(session.execute(select(Allocation, ResourceRequest, Resource).join(ResourceRequest,
            ResourceRequest.id == Allocation.request_id).join(Resource, Resource.id == Allocation.resource_id)
            .where(Allocation.run_id == run_id, scope))) if run_id is not None else []
        busy = [] if published else list(session.scalars(select(BusySlot).where(BusySlot.user_id == actor)))
        request_ids, busy_ids = {r.id for _, r, _ in rows}, {b.id for b in busy}
        bindings = {}
        query = select(LegacyCalendarBinding, AcademicPeriod).join(AcademicPeriod,
            AcademicPeriod.id == LegacyCalendarBinding.period_id).where(or_(LegacyCalendarBinding.request_id.in_(request_ids),
                LegacyCalendarBinding.busy_slot_id.in_(busy_ids)))
        for binding, period in session.execute(query):
            key = ('request', binding.request_id) if binding.request_id is not None else ('busy', binding.busy_slot_id)
            bindings.setdefault(key, []).append((binding, period))
        instructors = {u.id: u.name for u in session.scalars(select(User).join(Role, Role.id == User.primary_role_id).where(
            User.id.in_({r.academic_instructor_id for _, r, _ in rows}), Role.name == 'Instructor', User.status == 'active'))}
        groups = {}
        sources = [('request', r.id, allocation, r, room) for allocation, r, room in rows]
        sources += [('busy', b.id, b, None, None) for b in busy]
        for kind, key, slot, request, room in sources:
            choices = bindings.get((kind, key), [])
            if not choices:
                warnings.add('Some university commitments have unresolved academic dates. They were not expanded; this calendar is not a complete availability check.')
            for binding, period in choices:
                for a, b in expand_weekly(slot.day, slot.start_minutes, slot.end_minutes, period.start_date,
                        period.end_date, period.timezone, start, end, binding.excluded_dates, binding.week_start):
                    group = groups.setdefault((kind, key, a, b), {'rooms': set(), 'request': request, 'slot': slot})
                    if room:
                        group['rooms'].add(room.name + (' - '+room.building if room.building else ''))
        for (kind, key, a, b), group in groups.items():
            request = group['request']
            title = (request.title or 'University activity '+str(key)) if request else group['slot'].reason or 'University commitment'
            instructor = instructors.get(request.academic_instructor_id) if request else None
            note = ('Published schedule; this does not indicate enrollment.' if published else 'Explicitly bound university commitment.')
            if instructor:
                note += ' Instructor: '+instructor+'.'
            add(f'academic:{kind}:{key}:{int(a.timestamp())}', 'academic', title, a, b, 'Confirmed',
                '/calendar/academic/'+str(key)+'?date='+a.astimezone(university_zone()).date().isoformat() if request else '/appointments/calendar',
                busy=not published, note=note, location='; '.join(sorted(group['rooms'])))

    def _equipment(self, session, actor, start, end, scope, now, add):
        physical = select(BorrowItem.request_id).join(EquipmentReservation, EquipmentReservation.item_id == BorrowItem.id).where(or_(
            and_(EquipmentReservation.handed_at >= start, EquipmentReservation.handed_at < end),
            and_(EquipmentReservation.returned_at >= start, EquipmentReservation.returned_at < end)))
        permitted = or_(BorrowRequest.borrower_id == actor, BorrowRequest.faculty_id.in_(
            custodian_faculties(actor))) if scope == 'relevant' else BorrowRequest.borrower_id == actor
        rows = list(session.scalars(select(BorrowRequest).where(permitted, or_(
            and_(BorrowRequest.start_at < end, BorrowRequest.due_at >= start), BorrowRequest.id.in_(physical)))))
        bookings = {}
        for request_id, booking, asset in session.execute(select(BorrowItem.request_id, EquipmentReservation, EquipmentUnit.asset_tag)
                .join(EquipmentReservation, EquipmentReservation.item_id == BorrowItem.id)
                .join(EquipmentUnit, EquipmentUnit.id == EquipmentReservation.unit_id).where(BorrowItem.request_id.in_([r.id for r in rows]))):
            bookings.setdefault(request_id, []).append((booking, asset))
        for row in rows:
            path = '/equipment/'+str(row.id)
            values = bookings.get(row.id, [])
            outstanding = [b for b, _ in values if b.handed_at is not None and b.returned_at is None]
            overdue = bool(outstanding and row.due_at < now)
            note = 'Equipment reminder only; never participant-busy time. '+str(len(outstanding))+' units physically outstanding.'
            state = 'completed' if row.status in {'Borrowed', 'Partially Returned', 'Returned'} else None
            add('pickup:'+str(row.id), 'equipment', 'Scheduled pickup: '+row.purpose, row.start_at, None, row.status,
                path, note=note, state=state)
            add('due:'+str(row.id), 'equipment', 'Return due: '+row.purpose, row.due_at, None, row.status,
                path, note=note, state='overdue' if overdue else None)
            for booking, asset in values:
                if booking.handed_at is not None:
                    add('handover:'+str(booking.id), 'equipment', 'Collected: '+asset, booking.handed_at, None,
                        row.status, path, note='Recorded physical handover.', state='completed')
                if booking.returned_at is not None:
                    add('return:'+str(booking.id), 'equipment', 'Returned: '+asset, booking.returned_at, None,
                        row.status, path, note='Custodian-verified physical return.', state='completed')

    def academic_detail(self, actor, key, day):
        selected = selection('day', day)
        with self.database.transaction(read_only=True) as session:
            _identity(session, actor)
            row = session.get(ResourceRequest, key)
            own = row is not None and (row.requester_id == actor or session.get(RequestParticipant, (key, actor)) is not None)
            if row is None or not (own or row.calendar_public):
                raise PermissionError('This academic activity is unavailable or private.')
            events, warnings = self._read(session, actor, selected, {'academic'}, 'personal' if own else 'published')
            events = [e for e in events if e['id'].startswith('academic:request:'+str(key)+':')]
            return {'title': row.title or 'University activity '+str(key), 'events': events, 'warnings': sorted(warnings)}

    def publications(self, actor):
        with self.database.transaction(read_only=True) as session:
            if not _identity(session, actor):
                raise PermissionError('University administration access is required.')
            return {'requests': [{'id': r.id, 'title': r.title, 'type': r.type, 'public': r.calendar_public,
                'instructorId': r.academic_instructor_id} for r in session.scalars(select(ResourceRequest).where(
                    ResourceRequest.type != 'CommitteeMeeting').order_by(ResourceRequest.submission_order))],
                'instructors': [{'id': u.id, 'name': u.name} for u in session.scalars(select(User).join(Role,
                    Role.id == User.primary_role_id).where(Role.name == 'Instructor', User.status == 'active').order_by(User.name))]}

    def publish(self, actor, key, public, instructor=None):
        if type(public) is not bool or (instructor is not None and (type(instructor) is not int or instructor <= 0)):
            raise CalendarError('Select a valid publication state and optional professor.')
        with self.database.transaction() as session:
            if not _identity(session, actor):
                raise PermissionError('University administration access is required.')
            row = session.get(ResourceRequest, key, with_for_update=True)
            if row is None or row.type == 'CommitteeMeeting':
                raise CalendarError('Only ordinary academic activities may be published; committees remain private.')
            if instructor is not None and session.scalar(select(User.id).join(Role, Role.id == User.primary_role_id).where(
                    User.id == instructor, Role.name == 'Instructor', User.status == 'active')) is None:
                raise CalendarError('Select an active professor, not an inferred teaching assignment.')
            if (row.calendar_public, row.academic_instructor_id) != (public, instructor):
                row.calendar_public, row.academic_instructor_id = public, instructor
                session.add(RequestHistory(request_id=key, kind='calendar_publication',
                    message=f'Calendar publication {"enabled" if public else "disabled"} by user {actor}; instructor {instructor}.'))
