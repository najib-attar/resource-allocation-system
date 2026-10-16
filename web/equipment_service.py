"""Equipment lifecycle transactions; the C++ boundary owns inventory matching."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import uuid

from sqlalchemy import or_, select

from .calendar_service import CalendarError, aware, epoch
from .notification_service import publish_event
from .persistence.models import (BorrowExtension, BorrowItem, BorrowRequest, EquipmentCategory,
    EquipmentCustodian, EquipmentEvent, EquipmentReservation, EquipmentType, EquipmentUnit,
    EQUIPMENT_CONDITIONS, LoginAccount, OrganizationUnit, Role, User)


class EquipmentError(CalendarError):
    pass


class EquipmentService:
    def __init__(self, database, gateway):
        self.database, self.gateway = database, gateway

    def _user(self, session, actor, student=False):
        user = session.get(User, actor) if type(actor) is int and actor > 0 else None
        account = session.get(LoginAccount, actor) if user else None
        if not user or user.status.casefold() != 'active' or not account or not account.enabled:
            raise PermissionError('An active signed-in university account is required.')
        role = session.get(Role, user.primary_role_id).name
        if student and role != 'Student':
            raise PermissionError('Only students can borrow equipment.')
        return user, account, role

    def _admin(self, session, actor):
        _, account, role = self._user(session, actor)
        if not (account.administrator or role == 'Administrator'):
            raise PermissionError('University administration access is required.')

    def _faculty(self, session, key, lock=False):
        if type(key) is not int or key <= 0:
            raise EquipmentError('Choose a valid owning faculty.')
        query = select(OrganizationUnit).where(OrganizationUnit.id == key, OrganizationUnit.unit_type == 'Faculty')
        row = session.scalar(query.with_for_update() if lock else query)
        if row is None:
            raise EquipmentError('Choose an explicitly configured owning faculty.')
        return row

    def _custodian(self, session, faculty):
        assignment = session.get(EquipmentCustodian, faculty)
        if not assignment:
            return None
        user = session.get(User, assignment.user_id)
        account = session.get(LoginAccount, assignment.user_id)
        role = session.get(Role, user.primary_role_id).name
        return user.id if user.status.casefold() == 'active' and account.enabled and (account.administrator or role in {'Staff', 'Administrator'}) else None

    def _staff(self, session, actor, faculty):
        self._user(session, actor)
        if self._custodian(session, faculty) != actor:
            raise PermissionError('Only the current authorized equipment custodian of this faculty may perform this action.')

    def _faculties(self, session, user):
        result, key = [], user.primary_unit_id
        while key is not None:
            row = session.get(OrganizationUnit, key)
            if not row or key in result:
                raise EquipmentError('University organization configuration is invalid.')
            result.append(key)
            key = row.parent_id
        return result

    def _text(self, value, label, limit=2000, required=True):
        if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
            raise EquipmentError('Enter valid ' + label + '.')
        return value.strip()

    def _specs(self, value):
        if not isinstance(value, dict) or len(value) > 50 or any(not isinstance(k, str) or not k.strip() or len(k)>100
            or not isinstance(v, str) or len(v)>2000 for k, v in value.items()):
            raise EquipmentError('Specifications must be a bounded object of text keys and values.')
        return value

    def _items(self, items):
        if not isinstance(items, list) or not 1 <= len(items) <= 50:
            raise EquipmentError('Select 1-50 different equipment types.')
        result, seen = [], set()
        for item in items:
            if not isinstance(item, dict) or type(item.get('typeId')) is not int or item['typeId'] <= 0 or item['typeId'] in seen:
                raise EquipmentError('Select each valid equipment type only once.')
            if type(item.get('quantity')) is not int or not 1 <= item['quantity'] <= 1000:
                raise EquipmentError('Equipment quantities must be between 1 and 1000.')
            seen.add(item['typeId'])
            result.append({'typeId': item['typeId'], 'quantity': item['quantity'], 'specifications': self._specs(item.get('specifications', {}))})
        return sorted(result, key=lambda row: row['typeId'])

    def _period(self, start, due, future=True):
        start, due = aware(start), aware(due)
        epoch(start), epoch(due)
        if not start < due or due-start > timedelta(days=365) or (future and start <= datetime.now(timezone.utc)):
            raise EquipmentError('Choose a future borrowing interval of at most 365 days with return after pickup.')
        return start, due

    def _snapshot(self, session, actor, faculty, items, start, due, exclude=None, only_units=None):
        user, _, _ = self._user(session, actor, student=True)
        types = list(session.scalars(select(EquipmentType).where(EquipmentType.faculty_id == faculty).order_by(EquipmentType.id)))
        units = list(session.scalars(select(EquipmentUnit).where(EquipmentUnit.type_id.in_([t.id for t in types])).order_by(EquipmentUnit.id)))
        query = select(EquipmentReservation).join(BorrowItem, BorrowItem.id == EquipmentReservation.item_id).where(
            BorrowItem.faculty_id == faculty, EquipmentReservation.released.is_(False))
        if exclude is not None:
            query = query.where(BorrowItem.request_id != exclude)
        bookings = {}
        for row in session.scalars(query):
            bookings.setdefault(row.unit_id, []).append(row)
        return {'protocolVersion': 1, 'operation': 'equipment', 'runId': uuid.uuid4().hex, 'facultyId': faculty,
            'custodianActive': self._custodian(session, faculty) is not None, 'borrowerFacultyIds': self._faculties(session, user),
            'proposed': {'start': epoch(start), 'end': epoch(due)}, 'items': items,
            'types': [{'id': t.id, 'facultyId': t.faculty_id, 'categoryId': t.category_id, 'enabled': t.enabled,
                       'maxLoanDays': t.max_loan_days, 'specifications': t.specifications, 'eligibleFacultyIds': t.eligible_faculty_ids} for t in types],
            'units': [{'id': u.id, 'typeId': u.type_id, 'condition': u.condition,
                       'held': any(b.handed_at is not None and b.returned_at is None for b in bookings.get(u.id, [])),
                       'reservations': [{'start': epoch(b.start_at), 'end': epoch(b.due_at)} for b in bookings.get(u.id, [])]}
                      for u in units if only_units is None or u.id in only_units]}

    def _match(self, session, actor, faculty, items, start, due, exclude=None, only_units=None):
        snapshot = self._snapshot(session, actor, faculty, items, start, due, exclude, only_units)
        known = {t['id'] for t in snapshot['types']}
        if any(i['typeId'] not in known for i in items):
            raise EquipmentError('Every requested item must belong to the same selected faculty.')
        result, _ = self.gateway.execute_equipment(snapshot)
        return result

    def _require_match(self, result):
        if not result['feasible']:
            reasons = sorted({row['reasonCode'] for row in result['items'] if row['reasonCode'] != 'AVAILABLE'})
            raise EquipmentError('Equipment cannot fulfill the complete request: ' + ', '.join(reasons) + '. Refresh availability or amend the request.')

    def recommend(self, actor, faculty, items, start, due):
        items, (start, due) = self._items(items), self._period(start, due)
        with self.database.transaction(read_only=True) as session:
            self._faculty(session, faculty)
            result = self._match(session, actor, faculty, items, start, due)
            # Physical identifiers stay private until this student's reservation is approved.
            for row in result['items']:
                row.pop('unitIds')
            return result

    def _event(self, session, actor, faculty, message, request_id=None, unit_id=None):
        event = EquipmentEvent(actor_id=actor, faculty_id=faculty, request_id=request_id, unit_id=unit_id, message=message)
        if request_id is None:
            session.add(event)
        else:
            publish_event(session, event)

    def submit(self, actor, faculty, items, start, due, purpose, notes, submission_key):
        items, (start, due) = self._items(items), self._period(start, due)
        purpose, notes = self._text(purpose, 'purpose'), self._text(notes, 'notes', 4000, False)
        if not isinstance(submission_key, str) or not re.fullmatch('[0-9a-f]{32}', submission_key):
            raise EquipmentError('Refresh the borrowing form to obtain a valid submission identity.')
        payload = {'faculty': faculty, 'items': items, 'start': start.isoformat(), 'due': due.isoformat(), 'purpose': purpose, 'notes': notes}
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self.database.transaction() as session:
            # Also serializes retries sent to different faculties for the same student.
            session.scalar(select(User).where(User.id == actor).with_for_update())
            self._user(session, actor, student=True)
            existing = session.scalar(select(BorrowRequest).where(BorrowRequest.borrower_id == actor, BorrowRequest.submission_key == submission_key))
            if existing:
                if existing.submission_fingerprint != fingerprint:
                    raise EquipmentError('This submission identity was already used for different requirements.')
                return existing.id
            self._faculty(session, faculty, True)
            self._require_match(self._match(session, actor, faculty, items, start, due))
            row = BorrowRequest(borrower_id=actor, faculty_id=faculty, start_at=start, due_at=due, purpose=purpose,
                notes=notes, submission_key=submission_key, submission_fingerprint=fingerprint)
            session.add(row)
            session.flush()
            session.add_all(BorrowItem(request_id=row.id, faculty_id=faculty, type_id=i['typeId'], quantity=i['quantity'],
                                       specifications=i['specifications']) for i in items)
            self._event(session, actor, faculty, 'Submitted for custodian approval; pending requests reserve no units.', row.id)
            return row.id

    def _request(self, session, actor, key, lock=False):
        self._user(session, actor)
        row = session.get(BorrowRequest, key) if type(key) is int and key > 0 else None
        if row is None or (actor != row.borrower_id and self._custodian(session, row.faculty_id) != actor):
            raise PermissionError('This borrowing request is unavailable or private.')
        if lock:
            self._faculty(session, row.faculty_id, True)
            session.refresh(row)
            if actor != row.borrower_id and self._custodian(session, row.faculty_id) != actor:
                raise PermissionError('The equipment custodian assignment changed. Refresh your access.')
        return row

    def _lines(self, session, key):
        return list(session.scalars(select(BorrowItem).where(BorrowItem.request_id == key).order_by(BorrowItem.id)))

    def _needs(self, lines):
        return [{'typeId': i.type_id, 'quantity': i.quantity, 'specifications': i.specifications} for i in lines]

    def _reservations(self, session, key):
        return list(session.scalars(select(EquipmentReservation).join(BorrowItem, BorrowItem.id == EquipmentReservation.item_id)
                                   .where(BorrowItem.request_id == key).order_by(EquipmentReservation.id)))

    def decide(self, actor, key, approve, reason=''):
        if type(approve) is not bool:
            raise EquipmentError('Select approve or reject.')
        reason = self._text(reason, 'decision reason', required=False)
        with self.database.transaction() as session:
            row = self._request(session, actor, key, True)
            self._staff(session, actor, row.faculty_id)
            if row.status != 'Pending Approval':
                raise EquipmentError('Only a pending request may be decided; refresh its status.')
            if approve:
                if row.due_at <= datetime.now(timezone.utc):
                    raise EquipmentError('The borrowing interval has expired. Reject and request a new proposal.')
                lines = self._lines(session, key)
                result = self._match(session, row.borrower_id, row.faculty_id, self._needs(lines), row.start_at, row.due_at)
                self._require_match(result)
                by_type = {i.type_id: i for i in lines}
                for item in result['items']:
                    session.add_all(EquipmentReservation(item_id=by_type[item['typeId']].id, type_id=item['typeId'], unit_id=uid,
                        start_at=row.start_at, due_at=row.due_at) for uid in item['unitIds'])
            row.status = 'Approved' if approve else 'Rejected'
            self._event(session, actor, row.faculty_id, row.status + '. ' + reason, key)

    def cancel(self, actor, key):
        with self.database.transaction() as session:
            row = self._request(session, actor, key, True)
            if row.status not in {'Pending Approval', 'Approved'}:
                raise EquipmentError('Only pending requests or uncollected reservations can be cancelled. Borrowed equipment must be returned.')
            for booking in self._reservations(session, key):
                if booking.handed_at is not None:
                    raise EquipmentError('Collected equipment must be physically returned, not cancelled.')
                booking.released = True
            row.status = 'Cancelled'
            self._event(session, actor, row.faculty_id, 'Cancelled before collection; reservations released.', key)

    def handover(self, actor, key, condition):
        condition = self._text(condition, 'handover inspection')
        with self.database.transaction() as session:
            row = self._request(session, actor, key, True)
            self._staff(session, actor, row.faculty_id)
            now = datetime.now(timezone.utc)
            if row.status != 'Approved' or not row.start_at <= now < row.due_at:
                raise EquipmentError('Handover requires an approved reservation within its pickup/return interval.')
            reservations = self._reservations(session, key)
            result = self._match(session, row.borrower_id, row.faculty_id, self._needs(self._lines(session, key)),
                                 row.start_at, row.due_at, key, {b.unit_id for b in reservations})
            self._require_match(result)
            for booking in reservations:
                booking.handed_at, booking.handed_by, booking.handover_condition = now, actor, condition
            row.status = 'Borrowed'
            self._event(session, actor, row.faculty_id, 'Physical handover verified. ' + condition, key)

    def intend_return(self, actor, key):
        with self.database.transaction() as session:
            row = self._request(session, actor, key, True)
            if actor != row.borrower_id:
                raise PermissionError('Only the borrower may indicate return intent.')
            if row.status not in {'Borrowed', 'Partially Returned'}:
                raise EquipmentError('Only collected equipment can be offered for return.')
            self._event(session, actor, row.faculty_id, 'Student intends to return equipment. Availability unchanged until physical inspection.', key)

    def return_units(self, actor, key, unit_ids, condition, notes):
        if not isinstance(unit_ids, list) or not unit_ids or any(type(x) is not int for x in unit_ids) or len(unit_ids) != len(set(unit_ids)):
            raise EquipmentError('Select distinct units to inspect.')
        if condition not in {'usable', 'damaged', 'missing', 'lost', 'maintenance'}:
            raise EquipmentError('Select a supported return condition.')
        notes = self._text(notes, 'return notes', required=False)
        with self.database.transaction() as session:
            row = self._request(session, actor, key, True)
            self._staff(session, actor, row.faculty_id)
            if row.status not in {'Borrowed', 'Partially Returned'}:
                raise EquipmentError('This loan is not awaiting physical return.')
            bookings = self._reservations(session, key)
            eligible = {b.unit_id: b for b in bookings if b.handed_at is not None and b.returned_at is None}
            if not set(unit_ids) <= set(eligible):
                raise EquipmentError('Select only outstanding units from this loan.')
            for uid in unit_ids:
                booking = eligible[uid]
                session.get(EquipmentUnit, uid).condition = condition
                booking.return_condition = condition + (': ' + notes if notes else '')
                if condition not in {'missing', 'lost'}:
                    booking.returned_at, booking.received_by, booking.released = datetime.now(timezone.utc), actor, True
                self._event(session, actor, row.faculty_id, 'Custodian inspection: '+condition+'. '+notes, key, uid)
            returned = sum(b.returned_at is not None for b in bookings)
            row.status = 'Returned' if returned == len(bookings) else 'Partially Returned' if returned else 'Borrowed'

    def request_extension(self, actor, key, due, reason):
        due = aware(due)
        epoch(due)
        reason = self._text(reason, 'extension reason')
        with self.database.transaction() as session:
            row = self._request(session, actor, key, True)
            if row.borrower_id != actor:
                raise PermissionError('Only the borrower can request an extension.')
            if row.status not in {'Borrowed', 'Partially Returned'} or due <= max(row.due_at, datetime.now(timezone.utc)) or due-row.start_at>timedelta(days=365):
                raise EquipmentError('Extensions require an active loan and a later future due date within one year of pickup.')
            if session.scalar(select(BorrowExtension.id).where(BorrowExtension.request_id == key, BorrowExtension.status == 'Pending')):
                raise EquipmentError('An extension request is already awaiting a decision.')
            extension = BorrowExtension(request_id=key, due_at=due, reason=reason)
            session.add(extension)
            session.flush()
            self._event(session, actor, row.faculty_id, 'Extension requested until '+due.isoformat()+'. '+reason, key)
            return extension.id

    def decide_extension(self, actor, key, extension_id, approve):
        if type(approve) is not bool:
            raise EquipmentError('Choose approve or reject.')
        with self.database.transaction() as session:
            row = self._request(session, actor, key, True)
            self._staff(session, actor, row.faculty_id)
            extension = session.get(BorrowExtension, extension_id)
            if not extension or extension.request_id != key or extension.status != 'Pending' or row.status not in {'Borrowed', 'Partially Returned'}:
                raise EquipmentError('This extension is no longer awaiting a decision on an active loan.')
            if approve:
                if extension.due_at <= max(row.due_at, datetime.now(timezone.utc)):
                    raise EquipmentError('The proposed extension has expired or is no longer later than the current due date.')
                outstanding = [b for b in self._reservations(session, key) if b.returned_at is None]
                needs = self._needs(self._lines(session, key))
                for item in needs:
                    item['quantity'] = sum(b.type_id == item['typeId'] for b in outstanding)
                needs = [i for i in needs if i['quantity']]
                self._require_match(self._match(session, row.borrower_id, row.faculty_id, needs,
                    row.start_at, extension.due_at, key, {b.unit_id for b in outstanding}))
                for booking in outstanding:
                    booking.due_at = extension.due_at
                row.due_at = extension.due_at
            extension.status, extension.decided_by = ('Approved' if approve else 'Rejected'), actor
            self._event(session, actor, row.faculty_id, 'Extension '+extension.status+'.', key)

    def directory(self, actor):
        with self.database.transaction(read_only=True) as session:
            _, account, role = self._user(session, actor)
            return {'faculties': [{'id': f.id, 'name': f.name, 'custodianId': self._custodian(session, f.id)} for f in session.scalars(
                        select(OrganizationUnit).where(OrganizationUnit.unit_type == 'Faculty').order_by(OrganizationUnit.name))],
                    'isAdmin': account.administrator or role == 'Administrator',
                    'custodianFaculties': list(session.scalars(select(EquipmentCustodian.faculty_id).where(EquipmentCustodian.user_id == actor)))}

    def catalog(self, actor, start, due):
        start, due = self._period(start, due)
        with self.database.transaction(read_only=True) as session:
            self._user(session, actor, student=True)
            types = list(session.scalars(select(EquipmentType).where(EquipmentType.enabled.is_(True)).order_by(EquipmentType.faculty_id, EquipmentType.name)))
            result = []
            for faculty in sorted({t.faculty_id for t in types}):
                rows = [t for t in types if t.faculty_id == faculty]
                # Bound matching batches without changing the catalog schema or exposing serial numbers.
                for offset in range(0, len(rows), 50):
                    batch = rows[offset:offset+50]
                    matches = self._match(session, actor, faculty, [{'typeId': t.id, 'quantity': 1, 'specifications': {}} for t in batch], start, due)
                    by_type = {i['typeId']: i for i in matches['items']}
                    for t in batch:
                        match = by_type[t.id]
                        if match['reasonCode'] == 'INELIGIBLE':
                            continue
                        result.append({'id': t.id, 'name': t.name, 'description': t.description, 'specifications': t.specifications,
                            'category': session.get(EquipmentCategory, t.category_id).name, 'facultyId': faculty,
                            'faculty': session.get(OrganizationUnit, faculty).name, 'maxDays': t.max_loan_days,
                            'pickup': t.pickup_instructions, 'available': match['availableQuantity'], 'reason': match['reasonCode']})
            return result

    def detail(self, actor, key):
        with self.database.transaction(read_only=True) as session:
            row = self._request(session, actor, key)
            custodian = self._custodian(session, row.faculty_id)
            bookings = self._reservations(session, key)
            return {'id': row.id, 'borrowerId': row.borrower_id, 'borrower': session.get(User, row.borrower_id).name,
                'faculty': session.get(OrganizationUnit, row.faculty_id).name, 'facultyId': row.faculty_id,
                'isCustodian': custodian == actor, 'isBorrower': row.borrower_id == actor, 'status': row.status,
                'purpose': row.purpose, 'notes': row.notes, 'start': row.start_at, 'due': row.due_at,
                'overdue': any(b.handed_at is not None and b.returned_at is None and b.due_at < datetime.now(timezone.utc) for b in bookings),
                'items': [{'name': session.get(EquipmentType, i.type_id).name, 'quantity': i.quantity, 'specifications': i.specifications} for i in self._lines(session, key)],
                'units': [{'id': b.unit_id, 'asset': session.get(EquipmentUnit, b.unit_id).asset_tag,
                    'condition': session.get(EquipmentUnit, b.unit_id).condition, 'handed': b.handed_at, 'returned': b.returned_at,
                    'handoverCondition': b.handover_condition, 'returnCondition': b.return_condition, 'released': b.released} for b in bookings],
                'extensions': [{'id': e.id, 'due': e.due_at, 'reason': e.reason, 'status': e.status} for e in session.scalars(
                    select(BorrowExtension).where(BorrowExtension.request_id == key).order_by(BorrowExtension.id))],
                'history': [{'message': e.message, 'at': e.created_at, 'actor': session.get(User, e.actor_id).name, 'unitId': e.unit_id} for e in session.scalars(
                    select(EquipmentEvent).where(EquipmentEvent.request_id == key).order_by(EquipmentEvent.id))]}

    def list_for(self, actor):
        with self.database.transaction(read_only=True) as session:
            self._user(session, actor)
            faculties = [fid for fid in session.scalars(select(EquipmentCustodian.faculty_id).where(EquipmentCustodian.user_id == actor))
                         if self._custodian(session, fid) == actor]
            keys = list(session.scalars(select(BorrowRequest.id).where(or_(BorrowRequest.borrower_id == actor,
                BorrowRequest.faculty_id.in_(faculties))).order_by(BorrowRequest.created_at.desc(), BorrowRequest.id.desc())))
        return [self.detail(actor, key) for key in keys]

    def assign_custodian(self, actor, faculty, custodian):
        with self.database.transaction() as session:
            self._admin(session, actor)
            self._faculty(session, faculty, True)
            _, account, role = self._user(session, custodian)
            if not (account.administrator or role in {'Staff', 'Administrator'}):
                raise EquipmentError('Select an active staff or administrator account as equipment custodian.')
            assignment = session.get(EquipmentCustodian, faculty)
            previous = assignment.user_id if assignment else None
            if assignment:
                assignment.user_id = custodian
            else:
                session.add(EquipmentCustodian(faculty_id=faculty, user_id=custodian))
            self._event(session, actor, faculty, f'Equipment custodian assignment changed from {previous} to {custodian}.')

    def create_type(self, actor, faculty, category, name, description, specifications, max_days, pickup, eligible_faculties=None):
        name, category = self._text(name, 'equipment name', 200), self._text(category, 'category', 150)
        description, pickup = self._text(description, 'description', 4000, False), self._text(pickup, 'pickup instructions', 2000, False)
        specifications = self._specs(specifications)
        if type(max_days) is not int or not 1 <= max_days <= 365:
            raise EquipmentError('Configure a maximum borrowing duration between 1 and 365 days.')
        eligible_faculties = eligible_faculties or []
        if not isinstance(eligible_faculties, list) or len(eligible_faculties)>100 or any(type(f) is not int for f in eligible_faculties) or len(set(eligible_faculties))!=len(eligible_faculties):
            raise EquipmentError('Select distinct eligible faculties, or leave empty for all students.')
        with self.database.transaction() as session:
            self._faculty(session, faculty, True)
            self._staff(session, actor, faculty)
            for key in eligible_faculties:
                self._faculty(session, key)
            # Shared categories need a cross-faculty unique-name-safe insert.
            from sqlalchemy.dialects.postgresql import insert
            session.execute(insert(EquipmentCategory).values(name=category).on_conflict_do_nothing(index_elements=['name']))
            cat = session.scalar(select(EquipmentCategory).where(EquipmentCategory.name == category))
            row = EquipmentType(faculty_id=faculty, category_id=cat.id, name=name, description=description,
                specifications=specifications, max_loan_days=max_days, pickup_instructions=pickup, eligible_faculty_ids=eligible_faculties)
            session.add(row)
            session.flush()
            self._event(session, actor, faculty, 'Equipment type registered: '+name+'. Maximum loan days: '+str(max_days))
            return row.id

    def add_unit(self, actor, type_id, asset_tag, condition='usable'):
        asset_tag = self._text(asset_tag, 'unique inventory identifier', 150)
        if condition not in EQUIPMENT_CONDITIONS:
            raise EquipmentError('Select a supported inventory condition.')
        with self.database.transaction() as session:
            equipment = session.get(EquipmentType, type_id)
            if not equipment:
                raise EquipmentError('Choose an existing equipment type.')
            self._faculty(session, equipment.faculty_id, True)
            self._staff(session, actor, equipment.faculty_id)
            if session.scalar(select(EquipmentUnit.id).where(EquipmentUnit.asset_tag == asset_tag)):
                raise EquipmentError('This inventory identifier already exists.')
            unit = EquipmentUnit(type_id=type_id, asset_tag=asset_tag, condition=condition)
            session.add(unit)
            session.flush()
            self._event(session, actor, equipment.faculty_id, 'Inventory unit registered: '+asset_tag+'; '+condition, unit_id=unit.id)
            return unit.id

    def set_condition(self, actor, unit_id, condition, notes):
        if condition not in EQUIPMENT_CONDITIONS:
            raise EquipmentError('Select a supported inventory condition.')
        notes = self._text(notes, 'condition notes')
        with self.database.transaction() as session:
            unit = session.get(EquipmentUnit, unit_id)
            if not unit:
                raise EquipmentError('Select an existing inventory unit.')
            equipment = session.get(EquipmentType, unit.type_id)
            self._faculty(session, equipment.faculty_id, True)
            self._staff(session, actor, equipment.faculty_id)
            session.refresh(unit)
            held = session.scalar(select(EquipmentReservation.id).where(EquipmentReservation.unit_id == unit_id,
                EquipmentReservation.handed_at.is_not(None), EquipmentReservation.returned_at.is_(None)))
            if held and condition == 'usable':
                raise EquipmentError('Verify the physical return before marking an outstanding unit usable.')
            unit.condition, unit.notes = condition, notes
            self._event(session, actor, equipment.faculty_id, 'Inventory condition: '+condition+'. '+notes, unit_id=unit_id)

    def inventory(self, actor, faculty):
        with self.database.transaction(read_only=True) as session:
            self._staff(session, actor, faculty)
            types = list(session.scalars(select(EquipmentType).where(EquipmentType.faculty_id == faculty).order_by(EquipmentType.id)))
            rows = []
            for unit in session.scalars(select(EquipmentUnit).where(EquipmentUnit.type_id.in_([t.id for t in types])).order_by(EquipmentUnit.id)):
                loans = list(session.execute(select(EquipmentReservation, BorrowItem.request_id).join(BorrowItem, BorrowItem.id == EquipmentReservation.item_id)
                    .where(EquipmentReservation.unit_id == unit.id, EquipmentReservation.released.is_(False))))
                held = any(b.handed_at is not None and b.returned_at is None for b, _ in loans)
                overdue = any(b.handed_at is not None and b.returned_at is None and b.due_at < datetime.now(timezone.utc) for b, _ in loans)
                rows.append({'id': unit.id, 'asset': unit.asset_tag, 'type': next(t.name for t in types if t.id == unit.type_id),
                    'condition': unit.condition, 'held': held, 'overdue': overdue, 'notes': unit.notes,
                    'attention': overdue or (unit.condition != 'usable' and bool(loans)) or (held and len(loans)>1),
                    'requests': sorted({key for _, key in loans})})
            return {'types': [{'id': t.id, 'name': t.name, 'maxDays': t.max_loan_days, 'enabled': t.enabled} for t in types], 'units': rows}

    def configure_type(self, actor, type_id, enabled, max_days):
        if type(enabled) is not bool or type(max_days) is not int or not 1 <= max_days <= 365:
            raise EquipmentError('Configure an enabled flag and maximum duration between 1 and 365 days.')
        with self.database.transaction() as session:
            row = session.get(EquipmentType, type_id)
            if not row:
                raise EquipmentError('Choose an existing equipment type.')
            self._faculty(session, row.faculty_id, True)
            self._staff(session, actor, row.faculty_id)
            row.enabled, row.max_loan_days = enabled, max_days
            self._event(session, actor, row.faculty_id, f'Equipment policy changed: type {type_id}, enabled={enabled}, maximum days={max_days}. Existing loans retained.')

    def management_directory(self, actor):
        with self.database.transaction(read_only=True) as session:
            self._admin(session, actor)
            rows = session.execute(select(User, LoginAccount, Role.name).join(LoginAccount, LoginAccount.user_id == User.id)
                .join(Role, Role.id == User.primary_role_id).where(User.status == 'active', LoginAccount.enabled.is_(True)).order_by(User.name))
            return [{'id': u.id, 'name': u.name, 'role': role} for u, a, role in rows if a.administrator or role in {'Staff', 'Administrator'}]

    def refresh_overdue_alerts(self, actor):
        # No scheduler or automatic return: refresh durable alerts only for visible loans.
        for item in self.list_for(actor):
            if not item['overdue']:
                continue
            with self.database.transaction() as session:
                row = self._request(session, actor, item['id'], True)
                if not any(b.handed_at and b.returned_at is None and b.due_at < datetime.now(timezone.utc)
                           for b in self._reservations(session, row.id)):
                    continue
                message = 'Overdue equipment: due '+row.due_at.isoformat()+'. Physical return is required; affected reservations need custodian attention.'
                if not session.scalar(select(EquipmentEvent.id).where(EquipmentEvent.request_id == row.id, EquipmentEvent.message == message)):
                    self._event(session, actor, row.faculty_id, message, row.id)
