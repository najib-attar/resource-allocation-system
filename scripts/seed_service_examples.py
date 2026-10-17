"""Add reusable accepted/rejected/pending examples to an owned fictional demo."""

import argparse
from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from scripts.setup_local_demo import connection_url, prepare_settings, validate_period
from web.appointment_service import AppointmentService
from web.calendar_service import CalendarError, university_zone
from web.engine_gateway import EngineGateway, EngineIntegrationError
from web.equipment_service import EquipmentService
from web.persistence.database import Database
from web.persistence.models import (Appointment, AppointmentCommitment, BorrowRequest,
    AppointmentEvent, EquipmentEvent, EquipmentReservation, BorrowItem, LoginAccount,
    RoomEvent, RoomOrganizerCommitment, RoomReservation, StudentRoomRequest, User)
from web.room_request_service import RoomRequestService


def seed_service_examples(database, gateway, organizer, professor, invitee, first, last):
    """Use real services; reruns report existing cases without resetting decisions."""
    validate_period(first, last)
    zone = university_zone()
    start = max(datetime.combine(first, time(9), zone),
                datetime.now(zone).replace(second=0, microsecond=0)+timedelta(minutes=1))
    end = min(datetime.combine(last+timedelta(days=1), time(), zone), start+timedelta(days=7))
    if end-start < timedelta(days=3):
        raise ValueError('The explicit demo calendar needs at least three future days for these examples.')
    appointments, rooms, equipment = (AppointmentService(database, gateway),
        RoomRequestService(database, gateway), EquipmentService(database, gateway))
    directory = appointments.directory()
    faculty = next((row['facultyId'] for row in directory['professors'] if row['id'] == professor), None)
    if faculty is None:
        raise ValueError('The selected professor needs an explicit faculty.')
    report = []
    # Coordinate this maintenance tool only, not normal application operations.
    with database.transaction() as guard:
        if not guard.scalar(text('SELECT pg_try_advisory_xact_lock(4400301)')):
            raise ValueError('Service examples are already being prepared. Retry shortly.')
        for kind, model in (('Appointment', Appointment), ('Room', StudentRoomRequest), ('Equipment', BorrowRequest)):
            for case in ('Accepted', 'Rejected', 'Pending'):
                purpose = '[Demo] '+kind+' - '+case
                owner = model.borrower_id if model is BorrowRequest else model.organizer_id
                with database.transaction(read_only=True) as session:
                    ids = list(session.scalars(select(model.id).where(owner == organizer, model.purpose == purpose)))
                if len(ids) > 1:
                    raise ValueError('Duplicate labeled examples were found; existing data was not reset.')
                created = not ids
                if ids:
                    key = ids[0]
                elif kind == 'Appointment':
                    result, _ = appointments.evaluate(organizer, [professor], [invitee], 30, start,
                        min(end, start+timedelta(days=2)), faculty=faculty)
                    if not result['recommendations']:
                        raise ValueError('No feasible published professor time was found; calendars were not changed.')
                    slot = datetime.fromtimestamp(result['recommendations'][0]['start'], timezone.utc)
                    key = appointments.submit(organizer, [professor], [invitee], purpose, 30, slot, faculty)
                    if case != 'Pending':
                        appointments.decide(key, professor, 1, case == 'Accepted')
                elif kind == 'Room':
                    values = dict(start=start+timedelta(days=2), duration=60, count=4, category='study', purpose=purpose,
                                  features=[], description='Fictional workflow example.', faculty=faculty)
                    matches = rooms.recommend(organizer, values, [professor])
                    candidates = matches['candidates'] or matches['alternatives']
                    chosen = next((row for row in candidates if row['end'] <= int(end.timestamp())), None)
                    if not chosen:
                        raise ValueError('No eligible demo room/time was found; room policies were not changed.')
                    values['start'] = datetime.fromtimestamp(chosen['start'], timezone.utc)
                    key = rooms.submit(organizer, values, [professor], chosen['roomId'])
                    if case != 'Pending':
                        approver = rooms.detail(key, organizer)['approverId']
                        rooms.decide(key, approver, 1, case == 'Accepted',
                                     'Fictional example: faculty declined the proposed activity.' if case == 'Rejected' else '')
                else:
                    due = start+timedelta(days=2)
                    catalog = equipment.catalog(organizer, start, due)
                    selected = next((row for row in catalog if row['facultyId'] == faculty and row['available'] >= 2), None)
                    if selected is None:
                        raise ValueError('Two eligible equipment units and a custodian are required; inventory was not changed.')
                    identity = uuid.uuid5(uuid.NAMESPACE_URL, 'service-example:'+str(organizer)+':'+purpose).hex
                    key = equipment.submit(organizer, faculty, [{'typeId': selected['id'], 'quantity': 2}],
                        start, due, purpose, 'Fictional request; approval is not physical handover.', identity)
                    if case != 'Pending':
                        custodian = next(row['custodianId'] for row in equipment.directory(organizer)['faculties'] if row['id'] == faculty)
                        equipment.decide(custodian, key, case == 'Accepted', 'Fictional custodian decision example.')

                if kind == 'Appointment':
                    detail = appointments.detail(key, organizer)
                    receiver = professor
                    path = '/appointments/'+str(key)
                elif kind == 'Room':
                    detail = rooms.detail(key, organizer)
                    receiver = detail['approverId']
                    path = '/rooms/'+str(key)
                else:
                    detail = equipment.detail(organizer, key)
                    receiver = next(row['custodianId'] for row in equipment.directory(organizer)['faculties'] if row['id'] == faculty)
                    path = '/equipment/'+str(key)
                with database.transaction(read_only=True) as session:
                    recipient = session.get(LoginAccount, receiver)
                    if kind == 'Appointment':
                        assigned = len(list(session.scalars(select(AppointmentCommitment.user_id).where(AppointmentCommitment.appointment_id == key))))
                        if assigned != (2 if detail['status'] == 'Confirmed' else 0):
                            raise ValueError('Appointment commitments disagree with its current status.')
                    elif kind == 'Room':
                        bookings = list(session.scalars(select(RoomReservation).where(RoomReservation.request_id == key)))
                        people = list(session.scalars(select(RoomOrganizerCommitment).where(RoomOrganizerCommitment.request_id == key)))
                        assigned = len(bookings)
                        if (assigned, len(people)) != ((1, 1) if detail['status'] == 'Confirmed' else (0, 0)):
                            raise ValueError('Room commitments disagree with its current status.')
                    else:
                        assigned = len(list(session.scalars(select(EquipmentReservation.id).join(BorrowItem,
                            BorrowItem.id == EquipmentReservation.item_id).where(BorrowItem.request_id == key,
                                                                               EquipmentReservation.released.is_(False)))))
                        if detail['status'] in {'Pending Approval', 'Rejected', 'Cancelled', 'Returned'} and assigned:
                            raise ValueError('Unreserved equipment request has active reservations.')
                        if detail['status'] in {'Approved', 'Borrowed'} and assigned != sum(item['quantity'] for item in detail['items']):
                            raise ValueError('Equipment assignment does not fulfill the full requested quantity.')
                    event_model, parent = {'Appointment': (AppointmentEvent, AppointmentEvent.appointment_id),
                        'Room': (RoomEvent, RoomEvent.request_id),
                        'Equipment': (EquipmentEvent, EquipmentEvent.request_id)}[kind]
                    events = list(session.scalars(select(event_model).where(parent == key)))
                    if not events or any(not event.created_at.tzinfo or not event.actor_id for event in events):
                        raise ValueError('Lifecycle audit evidence is incomplete.')
                    report.append({'service': kind, 'example': case, 'id': key, 'status': detail['status'],
                        'created': created, 'url': path, 'decisionAccount': recipient.username if recipient else None,
                        'start': detail['start'].astimezone(zone).isoformat(), 'assignedRecords': assigned,
                        'historyEvents': len(events)})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', required=True, help='Owned fictional local demo profile directory.')
    args = parser.parse_args()
    database = None
    try:
        folder = Path(args.state_dir).resolve()
        if not (folder/'settings.json').is_file():
            raise ValueError('Initialize an owned fictional demo first. No settings or database were created.')
        settings = prepare_settings(folder/'settings.json')
        marker = folder/'postgres-data/local-demo-owner'
        if not marker.is_file() or marker.read_text() != settings['profileId'] or not settings['seeded']:
            raise ValueError('Use a successfully initialized, owned fictional demo. Existing profiles were not changed.')
        database = Database(connection_url(settings))
        people = {}
        with database.transaction(read_only=True) as session:
            for username in ('student1', 'student2', 'professor1'):
                account = session.scalar(select(LoginAccount).where(LoginAccount.username == username, LoginAccount.enabled.is_(True)))
                user = session.get(User, account.user_id) if account else None
                if user is None or not user.email.endswith('@example.invalid'):
                    raise ValueError('Examples require the configured fictional demo accounts; real users were not changed.')
                people[username] = user.id
        cases = seed_service_examples(database, EngineGateway(ROOT), people['student1'], people['professor1'],
            people['student2'], date.fromisoformat(settings['academicStart']), date.fromisoformat(settings['academicEnd']))
        print(json.dumps(cases, indent=2))
        print('Existing examples are reported, never reset. Pending examples remain available for manual decisions.')
        return 0
    except (ValueError, CalendarError, PermissionError, EngineIntegrationError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print('Examples could not be completed. Existing data was preserved; inspect database connectivity and migrations.', file=sys.stderr)
        return 1
    finally:
        if database:
            database.dispose()


if __name__ == '__main__':
    sys.exit(main())
