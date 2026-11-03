"""Real Flask review instance with synthetic service-created student records.

Only the PostgreSQL test harness's random owned schema is written. Historical
physical handover/returns use fixture clocks while seeding, never in the server.
"""
import json
import os
from pathlib import Path
import sys
import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]

from sqlalchemy import select
from werkzeug.serving import make_server
from recurring_fixtures import RoomFixture
from test_appointments import START
from web import app as web_app
from web.account_service import AccountService
from web.engine_gateway import EngineGateway
from web.equipment_service import EquipmentService
from web.feedback_service import FeedbackService
from web.persistence.models import LoginAccount
from web.waiting_list_service import WaitingListService, POLICY_VERSION


def seed(fixture):
    appointment = fixture.service
    confirmed = appointment.submit(1, [2], [], 'Fictional capstone consultation', 60, START, fixture.faculty)
    appointment.decide(confirmed, 2, 1, True)
    pending = appointment.submit(1, [2, 3], [4], 'Fictional research proposal review', 60,
                                 START + timedelta(hours=2), fixture.faculty)
    appointment.decide(pending, 2, 1, True)
    invitation = appointment.submit(4, [3], [1], 'Fictional peer project invitation', 60,
                                    START + timedelta(hours=4), fixture.faculty)
    appointment.decide(invitation, 3, 1, True)
    private = appointment.submit(4, [3], [], 'PRIVATE unrelated appointment', 60,
                                 START + timedelta(hours=5), fixture.faculty)
    room = fixture.request_room(start=START + timedelta(days=1), purpose='Fictional design team workspace',
                                participantIds=[4])
    fixture.rooms.decide(room, 7, 1, True)
    room_pending = fixture.request_room(start=START + timedelta(days=2), purpose='Fictional reading group',
                                        invitees=[2])
    pattern = dict(periodId=fixture.semester, approvalMode='partial', startDate='2030-01-17',
                   endDate='2030-01-24', weekdays=[4], startTime='14:00')
    series = fixture.rooms.submit(1, fixture.values(recurrence=pattern, purpose='Fictional weekly workshop'),
                                   [], 302, submission_key=uuid.uuid4().hex)
    fixture.rooms.decide(series, 7, 1, True)
    appointment.block(1, START + timedelta(days=3), START + timedelta(days=3, hours=1),
                       'Fictional independent study')
    equipment = EquipmentService(fixture.database, EngineGateway(ROOT))
    equipment.assign_custodian(6, fixture.faculty, 7)
    type_id = equipment.create_type(7, fixture.faculty, 'Development boards', 'Fictional teaching kit',
                                    'Microcontroller and accessories for coursework', {'architecture':'arm'},
                                    14, 'Collect and return at the faculty equipment desk.')
    units = [equipment.add_unit(7, type_id, 'FIC-KIT-' + str(n)) for n in range(1, 5)]
    past = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(days=4)
    with mock.patch('web.equipment_service.datetime', wraps=datetime) as clock:
        clock.now.return_value = past - timedelta(days=1)
        loan = equipment.submit(1, fixture.faculty, [dict(typeId=type_id, quantity=2)], past,
                                past + timedelta(days=2), 'Fictional lab coursework', '', uuid.uuid4().hex)
        equipment.decide(7, loan, True)
        clock.now.return_value = past + timedelta(hours=1)
        equipment.handover(7, loan, 'Synthetic inspection: usable kits.')
        equipment.return_units(7, loan, [units[0]], 'usable', 'One kit inspected and returned.')
    borrow_pending = equipment.submit(1, fixture.faculty, [dict(typeId=type_id, quantity=1)], START,
                                       START + timedelta(days=2), 'Fictional future project kit', '', uuid.uuid4().hex)
    equipment_series = equipment.submit(1, fixture.faculty, [dict(typeId=type_id, quantity=1)],
        START + timedelta(days=10, hours=4), START + timedelta(days=10, hours=5),
        'Fictional weekly electronics lab', '', uuid.uuid4().hex, recurrence=pattern)
    equipment.decide(7, equipment_series, True)
    waiting = WaitingListService(fixture.database, EngineGateway(ROOT))
    waiting.configure_notice(6, 60)
    queue_start = START + timedelta(days=4)
    occupied = fixture.request_room(actor=4, start=queue_start, count=8, faculty=fixture.other_faculty)
    fixture.rooms.decide(occupied, 7, 1, True)
    for resource in (301, 303):
        fixture.rooms.close_room(6, resource, queue_start, queue_start + timedelta(hours=1),
                                'Fictional maintenance interval')
    queue = waiting.join_room(1, fixture.values(start=queue_start, count=8, faculty=fixture.other_faculty,
        purpose='Fictional unavailable group room'), [], fixture.other_faculty,
        POLICY_VERSION, True, uuid.uuid4().hex)
    waiting.review(queue, 7, True)
    feedback = FeedbackService(fixture.database)
    report_resource = feedback.context('equipment', loan, 1)['resources'][0]['id']
    report = feedback.submit(1, 'equipment', loan, report_resource, 'problem',
        'Fictional accessory cable requires inspection.', False, uuid.uuid4().hex)
    detail = feedback.detail(report, 7)
    feedback.update(report, 7, detail['revision'], 'Under Review', 'normal',
                     'Fictional response: the faculty desk is arranging inspection.', uuid.uuid4().hex)
    return dict(appointment=confirmed, pending=pending, invitation=invitation, private=private,
                room=room, roomPending=room_pending, roomSeries=series, roomId=302,
                loan=loan, borrowPending=borrow_pending, equipmentSeries=equipment_series,
                equipmentType=type_id, faculty=fixture.faculty, queue=queue, report=report)


def main():
    if not os.environ.get('TEST_DATABASE_URL'):
        raise SystemExit('Set TEST_DATABASE_URL to a disposable PostgreSQL database.')
    fixture = RoomFixture()
    try:
        fixture.setUp()
        ids = seed(fixture)
        accounts = AccountService(fixture.database)
        password = 'Fictional-portal-review-password'
        users = {1:'portal-student', 5:'portal-empty', 2:'portal-professor', 6:'portal-admin', 7:'portal-staff'}
        with fixture.database.transaction(read_only=True) as session:
            existing = set(session.scalars(select(LoginAccount.user_id)))
        for actor, username in users.items():
            accounts.provision(actor, username, password, administrator=actor == 6, reset=actor in existing)
        web_app.app.config.update(DATABASE_URL=fixture.url,
            SECRET_KEY='fictional-portal-review-session-key-2030', TESTING=False, PROPAGATE_EXCEPTIONS=True)
        web_app.app.jinja_env.auto_reload = True
        port = int(os.environ.get('PORTAL_PORT', '5053'))
        output = ROOT / 'build' / 'student-portal' / 'preview.json'
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(dict(url=f'http://127.0.0.1:{port}', password=password,
            users=users, week='2030-01-07', ids=ids, schema=fixture.schema), indent=2), encoding='utf-8')
        print(f'Fictional review app: http://127.0.0.1:{port}', flush=True)
        with make_server('127.0.0.1', port, web_app.app, threaded=True) as server:
            server.serve_forever()
    finally:
        fixture.dispose_web_database()
        fixture.doCleanups()


if __name__ == '__main__':
    main()
