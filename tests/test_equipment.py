"""Real PostgreSQL and real-engine equipment lifecycle, permissions and races."""
from datetime import timedelta
import multiprocessing
import uuid
from unittest import mock

from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError

from postgres_fixtures import PostgresTestCase, ROOT
from test_appointments import seed_appointments, START
from web.account_service import AccountService
from web.engine_gateway import EngineGateway, EngineIntegrationError, validate_equipment_result
from web.equipment_service import EquipmentService, EquipmentError
from web.notification_service import NotificationService
from web.persistence.database import Database
from web.persistence.models import (BorrowRequest, BorrowItem, EquipmentReservation, EquipmentType,
    EquipmentCustodian, EquipmentEvent, OrganizationUnit)


def approve_process(url, key, queue):
    database = Database(url)
    try:
        EquipmentService(database, EngineGateway(ROOT)).decide(6, key, True)
        queue.put('approved')
    except EquipmentError:
        queue.put('unavailable')
    finally:
        database.dispose()


class EquipmentFixture(PostgresTestCase):
    def setUp(self):
        super().setUp()
        self.faculty = seed_appointments(self.database)
        for uid in (1, 2, 3, 4, 5, 6):
            AccountService(self.database).provision(uid, 'equipment-user'+str(uid), 'Fictional-equipment-password', administrator=uid==6)
        self.service = EquipmentService(self.database, EngineGateway(ROOT))
        self.service.assign_custodian(6, self.faculty, 6)
        self.type_id = self.service.create_type(6, self.faculty, 'Development boards', 'Fictional STM32', 'Teaching kit',
            {'architecture':'arm'}, 14, 'Collect from the faculty equipment desk.')
        self.units = [self.service.add_unit(6, self.type_id, 'FIC-BOARD-'+str(n)) for n in range(2)]

    def request(self, quantity=1, actor=1, start=START, due=None, submission_key=None, items=None):
        return self.service.submit(actor, self.faculty, items or [{'typeId':self.type_id,'quantity':quantity}],
            start, due or start+timedelta(days=3), 'Fictional university project', '', submission_key or uuid.uuid4().hex)

    def handover(self, key):
        with mock.patch('web.equipment_service.datetime') as clock:
            clock.now.return_value = START+timedelta(hours=1)
            self.service.handover(6, key, 'Both units inspected and usable.')

    def return_units(self, key, unit_ids, condition, notes):
        with mock.patch('web.equipment_service.datetime') as clock:
            clock.now.return_value = START+timedelta(hours=2)
            self.service.return_units(6, key, unit_ids, condition, notes)


class EquipmentWorkflowTests(EquipmentFixture):
    def test_concurrent_duplicate_submissions_create_one_request(self):
        from concurrent.futures import ThreadPoolExecutor
        identity=uuid.uuid4().hex
        with ThreadPoolExecutor(max_workers=2) as workers:
            results=list(workers.map(lambda _:self.request(submission_key=identity),range(2)))
        self.assertEqual(results[0],results[1])
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(BorrowRequest)),1)

    def test_database_exclusion_blocks_overlapping_unit_even_without_service(self):
        first=self.request();second=self.request(actor=4)
        self.service.decide(6,first,True)
        asset=self.service.detail(1,first)['units'][0]['id']
        with self.assertRaises(IntegrityError) as caught,self.database.transaction() as session:
            session.get(BorrowRequest,second).status='Approved'
            item=session.scalar(select(BorrowItem).where(BorrowItem.request_id==second))
            session.add(EquipmentReservation(item_id=item.id,type_id=self.type_id,unit_id=asset,start_at=START,due_at=START+timedelta(days=3)))
        self.assertEqual(caught.exception.orig.sqlstate,'23P01')

    def test_faculty_eligibility_and_disabled_policy_are_enforced_by_engine(self):
        with self.database.transaction() as session:
            session.get(EquipmentType,self.type_id).eligible_faculty_ids=[self.faculty]
        with self.assertRaises(EquipmentError):self.request()
        with self.database.transaction() as session:
            from web.persistence.models import User
            session.get(User,1).primary_unit_id=self.faculty
        self.assertIsInstance(self.request(),int)
        self.service.configure_type(6,self.type_id,False,14)
        with self.assertRaises(EquipmentError):self.request()

    def test_overdue_alert_is_durable_once_per_due_date(self):
        key=self.request();self.service.decide(6,key,True);self.handover(key)
        with mock.patch('web.equipment_service.datetime') as clock:
            clock.now.return_value=START+timedelta(days=4)
            self.service.refresh_overdue_alerts(1);self.service.refresh_overdue_alerts(1)
        with self.database.transaction(read_only=True) as session:
            messages=list(session.scalars(select(EquipmentEvent.message).where(EquipmentEvent.request_id==key)))
        self.assertEqual(sum(m.startswith('Overdue equipment:') for m in messages),1)

    def test_pending_then_approval_reserves_exact_quantity_and_notifies(self):
        key = self.request(2)
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(EquipmentReservation)),0)
        self.service.decide(6,key,True)
        item = self.service.detail(1,key)
        self.assertEqual((item['status'],len(item['units'])),('Approved',2))
        self.assertEqual({u['id'] for u in item['units']},set(self.units))
        self.assertTrue(any(i['kind']=='equipment' for i in NotificationService(self.database).inbox(1)['items']))

    def test_handover_return_intent_partial_return_and_damage(self):
        key=self.request(2);self.service.decide(6,key,True);self.handover(key)
        self.service.intend_return(1,key)
        self.assertEqual(self.service.detail(1,key)['status'],'Borrowed')
        self.return_units(key,[self.units[0]],'usable','Physically inspected')
        self.assertEqual(self.service.detail(1,key)['status'],'Partially Returned')
        self.return_units(key,[self.units[1]],'damaged','Broken connector')
        self.assertEqual(self.service.detail(1,key)['status'],'Returned')
        result=self.service.recommend(4,self.faculty,[{'typeId':self.type_id,'quantity':2}],START,START+timedelta(days=2))
        self.assertFalse(result['feasible']);self.assertEqual(result['items'][0]['availableQuantity'],1)

    def test_missing_unit_is_not_a_physical_return(self):
        key=self.request();self.service.decide(6,key,True);self.handover(key)
        uid=self.service.detail(1,key)['units'][0]['id']
        with self.assertRaises(IntegrityError),self.database.transaction() as session:
            booking=session.scalar(select(EquipmentReservation).where(EquipmentReservation.unit_id==uid))
            booking.released=True
        self.return_units(key,[uid],'missing','Student could not produce the unit')
        self.assertEqual(self.service.detail(1,key)['status'],'Borrowed')
        self.assertIsNone(self.service.detail(1,key)['units'][0]['returned'])
        with self.assertRaises(EquipmentError): self.service.set_condition(6,uid,'usable','Not actually returned')
        self.return_units(key,[uid],'usable','Recovered and physically inspected')
        self.assertEqual(self.service.detail(1,key)['status'],'Returned')

    def test_reject_cancel_release_and_borrowed_cannot_cancel(self):
        key=self.request();self.service.decide(6,key,False,'Not approved')
        self.assertEqual(self.service.detail(1,key)['status'],'Rejected')
        key=self.request(2);self.service.decide(6,key,True);self.service.cancel(1,key)
        self.assertTrue(all(u['released'] for u in self.service.detail(1,key)['units']))
        key=self.request();self.service.decide(6,key,True);self.handover(key)
        with self.assertRaises(EquipmentError): self.service.cancel(1,key)

    def test_no_partial_approval_after_competing_request(self):
        first=self.request(2);second=self.request(2,actor=4)
        self.service.decide(6,first,True)
        with self.assertRaises(EquipmentError): self.service.decide(6,second,True)
        self.assertEqual(self.service.detail(4,second)['status'],'Pending Approval')
        self.assertEqual(self.service.detail(4,second)['units'],[])

    def test_multi_item_request_and_same_faculty_constraint(self):
        second=self.service.create_type(6,self.faculty,'Instruments','Meter','',{},7,'Desk')
        self.service.add_unit(6,second,'FIC-METER')
        key=self.request(items=[{'typeId':self.type_id,'quantity':2},{'typeId':second,'quantity':1}])
        self.service.decide(6,key,True)
        self.assertEqual(len(self.service.detail(1,key)['units']),3)
        with self.database.transaction() as session:
            other=OrganizationUnit(name='Other fictional faculty',unit_type='Faculty');session.add(other);session.flush();fid=other.id
        self.service.assign_custodian(6,fid,6)
        third=self.service.create_type(6,fid,'Instruments','Other meter','',{},7,'Other desk')
        with self.assertRaises(EquipmentError): self.request(items=[{'typeId':third,'quantity':1}])

    def test_permissions_custodian_replacement_and_private_catalog(self):
        key=self.request()
        for action in (lambda:self.service.detail(4,key), lambda:self.service.decide(2,key,True),
                       lambda:self.service.handover(1,key,'Unverified'),lambda:self.service.assign_custodian(1,self.faculty,2)):
            with self.assertRaises(PermissionError): action()
        with self.assertRaises(EquipmentError): self.service.assign_custodian(6,self.faculty,2)
        self.assertNotIn('FIC-BOARD',str(self.service.catalog(1,START,START+timedelta(days=1))))
        from web.persistence.models import Role, User
        with self.database.transaction() as session:
            role=session.scalar(select(Role).where(Role.name=='Staff'))
            session.add(User(id=7,source_order=7,name='Fictional Equipment Officer',primary_role_id=role.id))
            faculty=OrganizationUnit(name='Fictional Arts Faculty',unit_type='Faculty');session.add(faculty);session.flush();other=faculty.id
        AccountService(self.database).provision(7,'equipment-staff','Fictional-officer-password')
        self.service.assign_custodian(6,other,7)
        with self.assertRaises(PermissionError):self.service.detail(7,key)
        with self.assertRaises(PermissionError):self.service.set_condition(7,self.units[0],'maintenance','Wrong faculty')
        self.service.assign_custodian(6,self.faculty,7)
        with self.assertRaises(PermissionError):self.service.decide(6,key,True)
        self.service.decide(7,key,True)
        self.assertEqual(self.service.detail(1,key)['status'],'Approved')
        self.assertFalse(any(i['kind']=='equipment' for i in NotificationService(self.database).inbox(6)['items']))
        with self.database.transaction() as session: session.delete(session.get(EquipmentCustodian,self.faculty))
        with self.assertRaises(PermissionError): self.service.decide(6,key,True)

    def test_missing_custodian_blocks_submission_without_partial_data(self):
        with self.database.transaction() as session: session.delete(session.get(EquipmentCustodian,self.faculty))
        with self.assertRaises(EquipmentError): self.request()
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(BorrowRequest)),0)

    def test_idempotent_submission_returns_same_request_and_rejects_mutation(self):
        identity=uuid.uuid4().hex;first=self.request(submission_key=identity)
        self.assertEqual(first,self.request(submission_key=identity))
        with self.assertRaises(EquipmentError): self.request(quantity=2,submission_key=identity)

    def test_overlap_and_adjacent_reservations(self):
        key=self.request(2);self.service.decide(6,key,True)
        adjacent=self.request(2,actor=4,start=START+timedelta(days=3))
        self.service.decide(6,adjacent,True)
        self.assertEqual(self.service.detail(4,adjacent)['status'],'Approved')

    def test_overdue_held_loan_blocks_future_and_staff_sees_affected_reservation(self):
        key=self.request(2);future=self.request(2,actor=4,start=START+timedelta(days=4))
        self.service.decide(6,key,True);self.service.decide(6,future,True);self.handover(key)
        with mock.patch('web.equipment_service.datetime') as clock:
            clock.now.return_value=START+timedelta(days=4,hours=1)
            self.assertTrue(self.service.detail(1,key)['overdue'])
            self.assertTrue(all(u['attention'] for u in self.service.inventory(6,self.faculty)['units']))
            with self.assertRaises(EquipmentError): self.service.handover(6,future,'Cannot override outstanding loans')
        self.assertFalse(self.service.recommend(4,self.faculty,[{'typeId':self.type_id,'quantity':1}],START+timedelta(days=10),START+timedelta(days=11))['feasible'])

    def test_extensions_respect_future_reservations_and_policy(self):
        key=self.request(2);future=self.request(2,actor=4,start=START+timedelta(days=4))
        self.service.decide(6,key,True);self.service.decide(6,future,True);self.handover(key)
        extension=self.service.request_extension(1,key,START+timedelta(days=5),'More experiment time')
        with self.assertRaises(EquipmentError): self.service.decide_extension(6,key,extension,True)
        self.service.decide_extension(6,key,extension,False)
        self.service.cancel(4,future)
        extension=self.service.request_extension(1,key,START+timedelta(days=5),'Reservation cancelled')
        self.service.decide_extension(6,key,extension,True)
        self.assertEqual(self.service.detail(1,key)['due'],START+timedelta(days=5))
        history=[event['message'] for event in self.service.detail(1,key)['history']]
        self.assertTrue(any('Due date at collection: '+(START+timedelta(days=3)).isoformat() in message for message in history))
        self.assertTrue(any('Previous due: '+(START+timedelta(days=3)).isoformat() in message
                            and 'current due: '+(START+timedelta(days=5)).isoformat() in message for message in history))

    def test_invalid_fields_and_unavailable_condition_fail_safely(self):
        for quantity in (0,-1,True,1.5,1001):
            with self.assertRaises(EquipmentError): self.request(quantity=quantity)
        with self.assertRaises(EquipmentError): self.request(due=START)
        with self.assertRaises(EquipmentError): self.request(due=START+timedelta(days=15))
        self.service.set_condition(6,self.units[0],'maintenance','Calibration')
        with self.assertRaises(EquipmentError): self.request(2)

    def test_backend_failure_rolls_back_decision_and_notifications(self):
        key=self.request()
        with mock.patch.object(self.service.gateway,'execute_equipment',side_effect=EngineIntegrationError('Engine unavailable')):
            with self.assertRaises(EngineIntegrationError): self.service.decide(6,key,True)
        self.assertEqual(self.service.detail(1,key)['status'],'Pending Approval')
        self.assertEqual(self.service.detail(1,key)['units'],[])

    def test_simultaneous_process_approvals_cannot_share_last_units(self):
        keys=[self.request(2),self.request(2,actor=4)]
        context=multiprocessing.get_context('spawn');queue=context.Queue()
        workers=[context.Process(target=approve_process,args=(self.url,k,queue)) for k in keys]
        for worker in workers:worker.start()
        for worker in workers:worker.join(60);self.assertEqual(worker.exitcode,0)
        self.assertCountEqual([queue.get(timeout=5) for _ in workers],['approved','unavailable'])
        queue.close();queue.join_thread()

    def test_database_prevents_incomplete_approval_and_cross_type_reservations(self):
        key=self.request()
        with self.assertRaises(IntegrityError),self.database.transaction() as session:
            session.get(BorrowRequest,key).status='Approved'
        self.assertEqual(self.service.detail(1,key)['status'],'Pending Approval')
        other_type=self.service.create_type(6,self.faculty,'Instruments','Different instrument','',{},7,'Desk')
        other_unit=self.service.add_unit(6,other_type,'FIC-OTHER-TYPE')
        with self.assertRaises(IntegrityError) as caught,self.database.transaction() as session:
            line=session.scalar(select(BorrowItem).where(BorrowItem.request_id==key))
            session.add(EquipmentReservation(item_id=line.id,type_id=self.type_id,unit_id=other_unit,start_at=START,due_at=START+timedelta(days=3)))
        self.assertEqual(caught.exception.orig.sqlstate,'23503')
        with self.assertRaises(IntegrityError),self.database.transaction() as session:
            line=session.scalar(select(BorrowItem).where(BorrowItem.request_id==key))
            session.add(EquipmentReservation(item_id=line.id,type_id=self.type_id,unit_id=self.units[0],start_at=START,due_at=START+timedelta(days=3)))
        self.assertEqual(len(inspect(self.database.engine).get_table_names()),54)  # 53 application + Alembic.

    def test_gateway_rejects_duplicate_or_foreign_engine_assets(self):
        with self.database.transaction(read_only=True) as session:
            snapshot=self.service._snapshot(session,1,self.faculty,[{'typeId':self.type_id,'quantity':2,'specifications':{}}],START,START+timedelta(days=1))
        result,_=self.service.gateway.execute_equipment(snapshot)
        result['items'][0]['unitIds']=[self.units[0],self.units[0]]
        with self.assertRaises(EngineIntegrationError): validate_equipment_result(result,snapshot)
