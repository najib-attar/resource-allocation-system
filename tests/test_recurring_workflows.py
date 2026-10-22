from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import uuid
import multiprocessing
from unittest import mock

from sqlalchemy import func, select

from test_room_requests import RoomFixture, START
from test_equipment import EquipmentFixture
from web.calendar_service import CalendarError, university_zone
from web.equipment_service import EquipmentError
from web.persistence.database import DatabaseBusy
from web.persistence.database import Database
from web.engine_gateway import EngineGateway
from postgres_fixtures import ROOT
from web.room_request_service import RoomRequestService
from web.persistence.models import ReservationSeries, RoomReservation, StudentRoomRequest


def pattern(end_days=7,days=None):
    local=START.astimezone(university_zone())
    return {'startDate':local.date().isoformat(),'endDate':(local.date()+timedelta(days=end_days)).isoformat(),
            'weekdays':days or [local.isoweekday()],'startTime':local.strftime('%H:%M')}


def approve_series_process(url,key,output):
    database=Database(url)
    try:output.put(RoomRequestService(database,EngineGateway(ROOT)).decide(key,7,1,True))
    except (CalendarError,DatabaseBusy):output.put('retry')
    finally:database.dispose()


class RecurringRoomWorkflowTests(RoomFixture):
    def series(self,actor=1,identity=None,**values):
        return self.rooms.submit(actor,self.values(recurrence=pattern(),**values),[],302,submission_key=identity or uuid.uuid4().hex)

    def test_same_room_all_dates_one_approval_and_idempotent_submission(self):
        identity=uuid.uuid4().hex
        key=self.series(identity=identity)
        self.assertEqual(self.series(identity=identity),key)
        self.assertEqual(self.totals(),(0,0))
        self.assertEqual(self.rooms.decide(key,7,1,True),'Confirmed')
        item=self.rooms.detail(key,1)
        self.assertEqual(len(item['recurrence']['occurrences']),2)
        self.assertEqual(self.totals(),(2,2))
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(set(session.scalars(select(RoomReservation.resource_id))),{302})

    def test_one_late_conflict_prevents_all_series_confirmation(self):
        key=self.series()
        other=self.request_room(actor=4,start=START+timedelta(days=7))
        self.rooms.decide(other,7,1,True)
        self.assertEqual(self.rooms.decide(key,7,1,True),'Needs Revision')
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(RoomReservation).where(RoomReservation.request_id==key)),0)
            self.assertEqual(session.get(StudentRoomRequest,key).status,'Needs Revision')

    def test_unavailable_date_is_explained_without_silent_room_substitution(self):
        other=self.request_room(actor=4,start=START+timedelta(days=7));self.rooms.decide(other,7,1,True)
        with self.assertRaises(CalendarError):self.series()
        result=self.rooms.recommend(1,self.values(recurrence=pattern()),[])
        self.assertTrue(all(c['roomId']!=302 for c in result['candidates']))

    def test_cancel_one_then_future_series_retains_occurrence_history(self):
        key=self.series();self.rooms.decide(key,7,1,True)
        item=self.rooms.detail(key,1);occ=item['recurrence']['occurrences'][1]['id']
        self.rooms.cancel_occurrence(key,1,1,occ)
        self.rooms.cancel_occurrence(key,1,1,occ)
        self.assertEqual(self.totals(),(1,1))
        self.rooms.cancel(key,1,1)
        item=self.rooms.detail(key,1)
        self.assertEqual(item['status'],'Cancelled')
        self.assertEqual([o['status'] for o in item['recurrence']['occurrences']],['Cancelled','Cancelled'])
        self.assertEqual(self.totals(),(0,0))

    def test_cancellation_never_erases_past_use(self):
        key=self.series();self.rooms.decide(key,7,1,True)
        with mock.patch('web.room_request_service.datetime') as clock:
            clock.now.return_value=START+timedelta(hours=2)
            self.rooms.cancel(key,1,1)
        self.assertEqual(self.totals(),(1,1))
        self.assertEqual(self.rooms.detail(key,1)['status'],'Confirmed')

    def test_foreign_actors_cannot_cancel_or_approve_series(self):
        key=self.series()
        with self.assertRaises(PermissionError):self.rooms.cancel(key,4,1)
        with self.assertRaises(PermissionError):self.rooms.decide(key,6,1,True)
        self.assertEqual(self.totals(),(0,0))

    def test_competing_series_confirm_only_one_complete_set(self):
        keys=[self.series(actor=actor) for actor in (1,4)]
        def approve(key):
            try:return self.rooms.decide(key,7,1,True)
            except (CalendarError,DatabaseBusy):return 'retry'
        with ThreadPoolExecutor(2) as workers:results=list(workers.map(approve,keys))
        self.assertEqual(results.count('Confirmed'),1)
        self.assertEqual(self.totals(),(2,2))

    def test_concurrent_identical_series_submissions_share_one_parent(self):
        identity=uuid.uuid4().hex
        with ThreadPoolExecutor(2) as workers:keys=list(workers.map(lambda _:self.series(identity=identity),range(2)))
        self.assertEqual(keys[0],keys[1])
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(ReservationSeries)),1)

    def test_independent_processes_cannot_double_book_the_series(self):
        keys=[self.series(actor=actor) for actor in (1,4)]
        context=multiprocessing.get_context('spawn');output=context.Queue()
        workers=[context.Process(target=approve_series_process,args=(self.url,key,output)) for key in keys]
        for worker in workers:worker.start()
        for worker in workers:worker.join(90);self.assertEqual(worker.exitcode,0)
        results=[output.get(timeout=5) for worker in workers]
        output.close();output.join_thread()
        self.assertEqual(results.count('Confirmed'),1);self.assertEqual(self.totals(),(2,2))

    def test_existing_eligible_room_queue_is_not_bypassed(self):
        from web.waiting_list_service import WaitingListService,POLICY_VERSION
        from web.persistence.models import RoomClosure
        key=self.series()
        for room in (301,302,303):self.rooms.close_room(6,room,START,START+timedelta(hours=1),'Temporary fixture closure')
        waiting=WaitingListService(self.database,self.rooms.gateway);waiting.configure_notice(6,60)
        entry=waiting.join_room(4,self.values(),[],self.other_faculty,POLICY_VERSION,True,uuid.uuid4().hex)
        waiting.review(entry,7,True)
        with self.database.transaction(read_only=True) as session:
            closure=session.scalar(select(RoomClosure.id).where(RoomClosure.resource_id==302))
        self.rooms.reopen_room(6,closure)
        self.assertEqual(waiting.detail(entry,4)['status'],'Assigned')
        self.assertEqual(self.rooms.decide(key,7,1,True),'Needs Revision')
        self.assertEqual(self.totals(),(1,1))

    def test_optional_professor_checks_remaining_dates_after_first_cancellation(self):
        key=self.rooms.submit(1,self.values(recurrence=pattern()),[2],302,submission_key=uuid.uuid4().hex)
        first=self.rooms.detail(key,1)['recurrence']['occurrences'][0]['id']
        self.rooms.cancel_occurrence(key,1,1,first)
        self.rooms.respond(key,2,1,True)
        self.assertEqual(self.rooms.detail(key,1)['invitations'][0]['status'],'Accepted')
        appointment=self.submit(organizer=4,start=START+timedelta(days=7))
        self.service.decide(appointment,2,1,True)
        with self.assertRaises(CalendarError):self.rooms.respond(key,2,1,True)
        self.assertEqual(self.rooms.decide(key,7,1,True),'Confirmed')
        self.assertEqual(self.totals(),(1,1))

    def test_explicit_academic_binding_blocks_only_its_actual_late_occurrence(self):
        from datetime import date
        from web.allocation_workflow import execute_allocation
        series=self.series()
        repo=self.academic(room=302,bound=False)
        key=repo.snapshot()['requests'][0]['id']
        self.service.bind_legacy('Explicit fictional second week',date(2030,1,14),date(2030,1,14),request_id=key,week_start=date(2030,1,14))
        execute_allocation(repo,self.rooms.gateway)
        self.assertEqual(self.rooms.decide(series,7,1,True),'Needs Revision')
        self.assertEqual(self.totals(),(0,0))


class RecurringEquipmentWorkflowTests(EquipmentFixture):
    def series(self,actor=1,quantity=1,identity=None):
        return self.service.submit(actor,self.faculty,[{'typeId':self.type_id,'quantity':quantity}],
            START,START+timedelta(hours=2),'Fictional weekly project','',identity or uuid.uuid4().hex,pattern())

    def at(self,when):
        patch=mock.patch('web.equipment_service.datetime')
        clock=patch.start();clock.now.return_value=when;self.addCleanup(patch.stop)
        return clock

    def test_series_reserves_all_quantities_without_duplicate_parent_requests(self):
        key=self.series(quantity=2)
        self.assertEqual(self.service.detail(1,key)['units'],[])
        self.service.decide(6,key,True)
        item=self.service.detail(1,key)
        self.assertEqual(len(item['recurrence']['occurrences']),2)
        self.assertEqual(len(item['units']),4)
        self.assertEqual(item['status'],'Approved')

    def test_one_unavailable_period_never_causes_partial_approval(self):
        key=self.series(quantity=2)
        other=self.request(2,actor=4,start=START+timedelta(days=7),due=START+timedelta(days=7,hours=2))
        self.service.decide(6,other,True)
        with self.assertRaises(EquipmentError):self.service.decide(6,key,True)
        item=self.service.detail(1,key)
        self.assertEqual(item['status'],'Pending Approval');self.assertEqual(item['units'],[])

    def test_each_pickup_and_verified_return_is_independent(self):
        key=self.series();self.service.decide(6,key,True)
        item=self.service.detail(1,key);first,second=item['recurrence']['occurrences']
        self.at(START+timedelta(minutes=10))
        self.service.handover(6,key,'Usable at pickup',first['id'])
        self.service.return_units(6,key,first['unitIds'],'usable','Physically returned')
        item=self.service.detail(1,key)
        self.assertEqual(item['status'],'Approved')
        self.assertEqual(item['recurrence']['occurrences'][0]['status'],'Completed')
        self.assertEqual(item['recurrence']['occurrences'][1]['status'],'Reserved')

    def test_unreturned_previous_occurrence_blocks_same_units_at_later_pickup(self):
        key=self.series(quantity=2);self.service.decide(6,key,True)
        first,second=self.service.detail(1,key)['recurrence']['occurrences']
        clock=self.at(START+timedelta(minutes=10));self.service.handover(6,key,'Usable',first['id'])
        clock.now.return_value=START+timedelta(days=7,minutes=10)
        with self.assertRaises(EquipmentError):self.service.handover(6,key,'Still not returned',second['id'])
        item=self.service.detail(1,key)
        self.assertEqual(item['status'],'Borrowed')
        self.assertTrue(all(u['handed'] is None for u in item['units'] if u['occurrenceId']==second['id']))

    def test_future_series_cancellation_never_releases_current_borrowed_units(self):
        key=self.series(quantity=2);self.service.decide(6,key,True)
        first,second=self.service.detail(1,key)['recurrence']['occurrences']
        self.at(START+timedelta(minutes=10));self.service.handover(6,key,'Usable',first['id'])
        self.service.cancel(1,key)
        item=self.service.detail(1,key)
        self.assertEqual(item['status'],'Borrowed')
        self.assertEqual(item['recurrence']['occurrences'][1]['status'],'Cancelled')
        self.assertTrue(all(not u['released'] for u in item['units'] if u['occurrenceId']==first['id']))

    def test_partial_and_damaged_returns_do_not_complete_the_series(self):
        key=self.series(quantity=2);self.service.decide(6,key,True)
        first,second=self.service.detail(1,key)['recurrence']['occurrences']
        self.at(START+timedelta(minutes=10));self.service.handover(6,key,'Usable',first['id'])
        self.service.return_units(6,key,[first['unitIds'][0]],'usable','Verified one unit')
        self.assertEqual(self.service.detail(1,key)['status'],'Partially Returned')
        self.service.return_units(6,key,[first['unitIds'][1]],'damaged','Verified damaged unit')
        self.assertEqual(self.service.detail(1,key)['status'],'Approved')

    def test_unchanged_series_retries_reuse_the_parent_and_changed_payload_fails(self):
        identity=uuid.uuid4().hex;key=self.series(identity=identity)
        self.assertEqual(self.series(identity=identity),key)
        with self.assertRaises(EquipmentError):self.series(quantity=2,identity=identity)

    def test_concurrent_identical_equipment_series_submission_is_idempotent(self):
        identity=uuid.uuid4().hex
        with ThreadPoolExecutor(2) as workers:keys=list(workers.map(lambda _:self.series(identity=identity),range(2)))
        self.assertEqual(keys[0],keys[1])

    def test_one_time_and_recurring_periods_compete_under_existing_inventory_locks(self):
        recurring=self.series(quantity=2);ordinary=self.request(2,actor=4,due=START+timedelta(hours=2))
        def approve(key):
            try:self.service.decide(6,key,True);return 'approved'
            except CalendarError:return 'unavailable'
        with ThreadPoolExecutor(2) as workers:results=list(workers.map(approve,[recurring,ordinary]))
        self.assertEqual(results.count('approved'),1)

    def test_existing_preapproved_equipment_queue_keeps_its_reservation(self):
        from web.waiting_list_service import WaitingListService,POLICY_VERSION
        series=self.series(quantity=2)
        blocker=self.request(2,actor=4,due=START+timedelta(hours=2));self.service.decide(6,blocker,True)
        waiting=WaitingListService(self.database,self.service.gateway);waiting.configure_notice(6,60)
        entry=waiting.join_equipment(5,self.faculty,[{'typeId':self.type_id,'quantity':2}],START,START+timedelta(hours=2),
            'Earlier eligible queue','',POLICY_VERSION,True,uuid.uuid4().hex)
        waiting.review(entry,6,True);self.service.cancel(4,blocker)
        self.assertEqual(waiting.detail(entry,5)['status'],'Assigned')
        with self.assertRaises(EquipmentError):self.service.decide(6,series,True)
        self.assertEqual(self.service.detail(1,series)['units'],[])
