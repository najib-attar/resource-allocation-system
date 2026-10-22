"""Approved partial decisions, explicit academic bounds and reasoned priorities."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
import uuid
from unittest import mock

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from recurring_fixtures import EquipmentFixture, RoomFixture
from test_room_requests import START
from test_recurring_workflows import pattern
from web.calendar_service import CalendarError
from web.persistence.models import AcademicPeriod, BorrowItem, EquipmentReservation, ReservationOccurrence, ReservationPriorityOverride, ReservationSeries, StudentRoomRequest
from web.waiting_list_service import WaitingListService
from web.university_calendar import UniversityCalendarService
from web.notification_service import NotificationService
from auth_fixtures import authorized_client
from web import app as web_app


class RecurringRoomPolicyTests(RoomFixture):
    def series(self,actor=1,mode='partial'):
        return self.rooms.submit(actor,self.values(recurrence={**pattern(),'approvalMode':mode}),[],302,submission_key=uuid.uuid4().hex)

    def occurrences(self,key):return self.rooms.detail(key,1)['recurrence']['occurrences']

    def test_partial_approval_retains_pending_date_then_rejects_only_that_date(self):
        key=self.series();dates=self.occurrences(key)
        self.rooms.decide(key,7,1,True,occurrence_ids=[dates[0]['id']])
        self.assertEqual(self.totals(),(1,1))
        item=self.rooms.detail(key,1)
        self.assertEqual(item['recurrence']['summary'],'Partially Confirmed')
        self.assertEqual([o['status'] for o in item['recurrence']['occurrences']],['Reserved','Proposed'])
        self.rooms.decide(key,7,1,False,'Not approved by faculty',[dates[1]['id']])
        self.assertEqual([o['status'] for o in self.occurrences(key)],['Reserved','Rejected'])
        self.assertEqual(self.occurrences(key)[1]['decidedBy'],7)
        self.assertTrue(self.occurrences(key)[1]['decidedAt'])

    def test_all_required_mode_rejects_selected_date_approval(self):
        key=self.series(mode='all')
        with self.assertRaises(CalendarError):self.rooms.decide(key,7,1,True,occurrence_ids=[self.occurrences(key)[0]['id']])
        self.assertEqual(self.totals(),(0,0))

    def test_late_conflict_is_unavailable_and_does_not_prevent_other_date(self):
        key=self.series();other=self.request_room(actor=4,start=START+timedelta(days=7))
        self.rooms.decide(other,7,1,True)
        self.rooms.decide(key,7,1,True)
        self.assertEqual([o['status'] for o in self.occurrences(key)],['Reserved','Unavailable'])
        self.assertEqual(self.totals(),(2,2))

    def test_unapproved_date_is_not_a_confirmed_calendar_commitment(self):
        key=self.series();self.rooms.decide(key,7,1,True,occurrence_ids=[self.occurrences(key)[0]['id']])
        result=UniversityCalendarService(self.database).load(1,'month','2030-01-07',categories=['room'])
        events=[e for e in result['events'] if e['id'].startswith('room:'+str(key)+':')]
        self.assertEqual(sum(e['busy'] for e in events),1)
        self.assertEqual({e['state'] for e in events},{'pending','confirmed'})

    def test_missing_semester_blocks_only_recurrence(self):
        with self.assertRaisesRegex(CalendarError,'semester'):
            self.rooms.submit(1,self.values(recurrence={**pattern(),'periodId':999}),[],302,submission_key=uuid.uuid4().hex)
        self.assertIsInstance(self.request_room(),int)

    def test_series_cannot_cross_semester_or_rewrite_bound_dates(self):
        rule={**pattern(),'endDate':'2030-07-07'}
        with self.assertRaisesRegex(CalendarError,'semester'):self.rooms.recommend(1,self.values(recurrence=rule),[])
        self.series()
        with self.assertRaises(IntegrityError),self.database.transaction() as session:
            session.get(AcademicPeriod,self.semester).end_date=date(2030,1,8)

    def test_configured_quota_and_active_limit_are_enforced(self):
        waiting=WaitingListService(self.database,self.rooms.gateway)
        waiting.configure_reservations(6,{'room':{'maxWeeklyMinutes':30}},[])
        with self.assertRaisesRegex(CalendarError,'hours'):self.series()
        waiting.configure_reservations(6,{'room':{'maxActiveSeries':1}},[])
        self.series()
        with self.assertRaisesRegex(CalendarError,'active'):self.series()

    def test_priority_requires_authority_configured_level_reason_and_audit(self):
        key=self.series();waiting=WaitingListService(self.database,self.rooms.gateway)
        waiting.configure_reservations(6,{},[10])
        for actor,level,reason in ((1,10,'Student bypass'),(6,10,'Wrong faculty'),(7,11,'Unconfigured'),(7,10,'')):
            with self.subTest(actor=actor,level=level),self.assertRaises((PermissionError,CalendarError)):
                waiting.override_priority('room',key,actor,level,reason)
        waiting.override_priority('room',key,7,10,'Approved accessibility need')
        with self.database.transaction(read_only=True) as session:
            audit=session.scalar(select(ReservationPriorityOverride))
            self.assertEqual((audit.actor_id,audit.original_priority,audit.selected_priority,audit.room_request_id),(7,0,10,key))
            self.assertTrue(audit.created_at)
            self.assertEqual(session.get(StudentRoomRequest,key).priority,10)
        with self.assertRaises(IntegrityError),self.database.transaction() as session:
            session.get(StudentRoomRequest,key).priority=99
        with self.assertRaises(IntegrityError),self.database.transaction() as session:
            session.scalar(select(ReservationPriorityOverride)).reason='Rewrite history'

    def test_configured_override_reorders_shared_queue_without_changing_eligibility(self):
        from web.waiting_list_service import POLICY_VERSION
        waiting=WaitingListService(self.database,self.rooms.gateway)
        waiting.configure_notice(6,60);waiting.configure_reservations(6,{},[10])
        closures=[self.rooms.close_room(6,r,START,START+timedelta(hours=1),'Fixture closed') for r in (301,302,303)]
        keys=[waiting.join_room(actor,self.values(),[],self.other_faculty,POLICY_VERSION,True,uuid.uuid4().hex) for actor in (1,4)]
        for key in keys:waiting.review(key,7,True)
        detail=waiting.detail(keys[1],4)
        waiting.override_priority('room',detail['requestId'],7,10,'Explicit approved access priority')
        self.assertEqual(waiting.detail(keys[1],4)['position'],1)
        self.assertEqual(waiting.detail(keys[0],1)['position'],2)
        from web.persistence.models import RoomClosure
        with self.database.transaction(read_only=True) as session:closure=session.scalar(select(RoomClosure.id).where(RoomClosure.resource_id==302))
        self.rooms.reopen_room(6,closure)
        self.assertEqual(waiting.detail(keys[1],4)['status'],'Assigned')
        self.assertEqual(waiting.detail(keys[0],1)['status'],'Preapproved')

    def test_concurrent_creations_cannot_exceed_active_series_quota(self):
        waiting=WaitingListService(self.database,self.rooms.gateway)
        waiting.configure_reservations(6,{'room':{'maxActiveSeries':1}},[])
        def create(_):
            try:return self.series()
            except CalendarError:return None
        with ThreadPoolExecutor(2) as pool:keys=list(pool.map(create,range(2)))
        self.assertEqual(sum(k is not None for k in keys),1)

    def test_concurrent_partial_confirmation_reserves_exactly_one(self):
        keys=[self.series(actor=actor) for actor in (1,4)]
        selected={key:self.rooms.detail(key,1 if key==keys[0] else 4)['recurrence']['occurrences'][0]['id'] for key in keys}
        def decide(key):
            try:return self.rooms.decide(key,7,1,True,occurrence_ids=[selected[key]])
            except CalendarError:return 'retry'
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(decide,keys))
        self.assertEqual(results.count('Confirmed'),1)
        self.assertEqual(self.totals(),(1,1))

    def test_selected_date_form_authorization_notifications_and_csrf(self):
        client=self.configure_web();key=self.series();dates=self.occurrences(key)
        manager=authorized_client(web_app.app,7)
        data={'revision':'1','decision':'approve','selectedDates':'1','occurrenceIds':str(dates[0]['id'])}
        path=f'/rooms/{key}/decision'
        self.assertEqual(client.post(path,data=data).status_code,403)
        self.assertEqual(manager.client.post(path,data=data).status_code,400)
        self.assertEqual(manager.post(path,data=data).status_code,302)
        self.assertIn(b'Partially Confirmed',client.get(f'/rooms/{key}').data)
        self.assertEqual(NotificationService(self.database).inbox(1)['items'][0]['current_status'],'Partially Confirmed')
        self.assertEqual(authorized_client(web_app.app,4).get(f'/rooms/{key}').status_code,403)

    def test_reservation_policy_configuration_is_admin_only(self):
        self.configure_web();admin=authorized_client(web_app.app,6);student=authorized_client(web_app.app,1)
        payload={'action':'reservation-policy','room_maxWeeklyMinutes':'120','priorities':'10,20'}
        self.assertEqual(student.post('/waiting-lists/configuration',data=payload).status_code,403)
        self.assertEqual(admin.post('/waiting-lists/configuration',data=payload).status_code,302)
        self.assertEqual(admin.post('/waiting-lists/configuration',data={**payload,'room_maxWeeklyMinutes':'-1'}).status_code,409)
        self.assertIn(b'Academic semesters',admin.get('/waiting-lists/configuration').data)

    def test_cancel_last_confirmed_date_preserves_rejected_outcome(self):
        key=self.series();dates=self.occurrences(key)
        self.rooms.decide(key,7,1,True,occurrence_ids=[dates[0]['id']])
        self.rooms.decide(key,7,1,False,'Not authorized for that date',[dates[1]['id']])
        self.rooms.cancel_occurrence(key,1,1,dates[0]['id'])
        self.assertEqual([o['status'] for o in self.occurrences(key)],['Cancelled','Rejected'])
        self.assertEqual(self.totals(),(0,0))

    def test_partial_submission_persists_known_unavailable_date(self):
        other=self.request_room(actor=4,start=START+timedelta(days=7));self.rooms.decide(other,7,1,True)
        key=self.series()
        self.assertEqual([o['status'] for o in self.occurrences(key)],['Proposed','Unavailable'])

    def test_changed_policy_is_rechecked_at_final_approval(self):
        key=self.series();WaitingListService(self.database,self.rooms.gateway).configure_reservations(6,{'room':{'maxWeeklyMinutes':30}},[])
        with self.assertRaisesRegex(CalendarError,'hours'):self.rooms.decide(key,7,1,True)
        self.assertEqual(self.totals(),(0,0))


class RecurringEquipmentPolicyTests(EquipmentFixture):
    def series(self,mode='partial'):
        return self.service.submit(1,self.faculty,[{'typeId':self.type_id,'quantity':2}],START,START+timedelta(hours=2),
            'Separate weekly physical loans','',uuid.uuid4().hex,{**pattern(),'approvalMode':mode})

    def test_selected_approval_and_rejection_keep_exact_quantities(self):
        key=self.series();dates=self.service.detail(1,key)['recurrence']['occurrences']
        self.service.decide(6,key,True,occurrence_ids=[dates[0]['id']])
        item=self.service.detail(1,key)
        self.assertEqual(item['recurrence']['summary'],'Partially Confirmed')
        self.assertEqual(len(item['units']),2)
        self.service.decide(6,key,False,'Later date not approved',[dates[1]['id']])
        self.assertEqual([o['status'] for o in self.service.detail(1,key)['recurrence']['occurrences']],['Reserved','Rejected'])

    def test_late_stock_conflict_marks_only_unavailable_occurrence(self):
        key=self.series()
        other=self.request(actor=4,quantity=2,start=START+timedelta(days=7),due=START+timedelta(days=7,hours=2))
        self.service.decide(6,other,True)
        self.service.decide(6,key,True)
        self.assertEqual([o['status'] for o in self.service.detail(1,key)['recurrence']['occurrences']],['Reserved','Unavailable'])
        with self.database.transaction(read_only=True) as session:
            count=session.scalar(select(func.count()).select_from(EquipmentReservation).join(BorrowItem,BorrowItem.id==EquipmentReservation.item_id).where(BorrowItem.request_id==key))
            self.assertEqual(count,2)

    def test_all_required_cannot_be_silently_reduced_to_one_date(self):
        key=self.series('all');dates=self.service.detail(1,key)['recurrence']['occurrences']
        with self.assertRaises(CalendarError):self.service.decide(6,key,True,occurrence_ids=[dates[0]['id']])
        self.assertFalse(self.service.detail(1,key)['units'])

    def test_partial_equipment_decision_form_and_private_summary(self):
        client=self.configure_web();key=self.series();dates=self.service.detail(1,key)['recurrence']['occurrences']
        manager=authorized_client(web_app.app,6)
        response=manager.post(f'/equipment/{key}/decision',data={'decision':'approve','selectedDates':'1','occurrenceIds':str(dates[0]['id'])})
        self.assertEqual(response.status_code,302)
        self.assertIn(b'Partially Confirmed',client.get(f'/equipment/{key}').data)
        self.assertEqual(NotificationService(self.database).inbox(1)['items'][0]['current_status'],'Partially Confirmed')

    def test_database_cannot_partially_confirm_an_all_required_series(self):
        from web.persistence.models import BorrowRequest
        key=self.series('all')
        with self.assertRaises(IntegrityError),self.database.transaction() as session:
            row=session.get(BorrowRequest,key)
            occurrence=session.scalar(select(ReservationOccurrence).join(ReservationSeries).where(
                ReservationSeries.borrow_request_id==key).order_by(ReservationOccurrence.ordinal))
            result=self.service._match(session,1,self.faculty,self.service._needs(self.service._lines(session,key)),occurrence.start_at,occurrence.end_at)
            self.service._reserve(session,row,result,occurrence)

    def collect_first(self,key):
        dates=self.service.detail(1,key)['recurrence']['occurrences']
        self.service.decide(6,key,True,occurrence_ids=[dates[0]['id']])
        with mock.patch('web.equipment_service.datetime',wraps=datetime) as clock:
            clock.now.return_value=START+timedelta(minutes=5)
            self.service.handover(6,key,'Inspected physical units',dates[0]['id'])
        return dates

    def test_returned_partial_occurrence_does_not_prevent_later_approval(self):
        key=self.series();dates=self.collect_first(key)
        with mock.patch('web.equipment_service.datetime',wraps=datetime) as clock:
            clock.now.return_value=START+timedelta(minutes=45)
            self.service.return_units(6,key,self.units,'usable','Verified physical return')
        self.assertEqual([o['status'] for o in self.service.detail(1,key)['recurrence']['occurrences']],['Completed','Proposed'])
        client=self.configure_web()
        self.assertIn(b'Cancel remaining future pickups',client.get(f'/equipment/{key}').data)
        self.service.decide(6,key,True,occurrence_ids=[dates[1]['id']])
        self.assertEqual([o['status'] for o in self.service.detail(1,key)['recurrence']['occurrences']],['Completed','Reserved'])

    def test_extensions_recheck_semester_and_configured_weekly_quota(self):
        key=self.series();dates=self.collect_first(key)
        waiting=WaitingListService(self.database,self.service.gateway)
        waiting.configure_reservations(6,{'equipment':{'maxWeeklyMinutes':120}},[])
        with mock.patch('web.equipment_service.datetime',wraps=datetime) as clock:
            clock.now.return_value=START+timedelta(minutes=10)
            extension=self.service.request_extension(1,key,START+timedelta(hours=3),'Need more time',dates[0]['id'])
            with self.assertRaisesRegex(CalendarError,'hours'):self.service.decide_extension(6,key,extension,True)
            self.service.decide_extension(6,key,extension,False)
            extension=self.service.request_extension(1,key,START+timedelta(days=180),'After semester',dates[0]['id'])
            with self.assertRaisesRegex(CalendarError,'semester'):self.service.decide_extension(6,key,extension,True)

    def test_overdue_physical_possession_still_counts_as_an_active_series(self):
        key=self.series();dates=self.collect_first(key)
        self.service.cancel_occurrence(1,key,dates[1]['id'])
        waiting=WaitingListService(self.database,self.service.gateway)
        waiting.configure_reservations(6,{'equipment':{'maxActiveSeries':1}},[])
        rule={**pattern(),'startDate':'2030-01-21','endDate':'2030-01-28'}
        with mock.patch('web.reservation_policy.datetime',wraps=datetime) as clock:
            clock.now.return_value=START+timedelta(days=1)
            with self.assertRaisesRegex(CalendarError,'active'):
                self.service.submit(1,self.faculty,[{'typeId':self.type_id,'quantity':2}],START+timedelta(days=14),START+timedelta(days=14,hours=2),
                    'Later recurring proposal','',uuid.uuid4().hex,rule)

    def test_partial_equipment_preview_persists_unavailable_dates_without_reserving(self):
        other=self.request(actor=4,quantity=2,start=START+timedelta(days=7),due=START+timedelta(days=7,hours=2))
        self.service.decide(6,other,True);key=self.series()
        item=self.service.detail(1,key)
        self.assertEqual([o['status'] for o in item['recurrence']['occurrences']],['Proposed','Unavailable'])
        self.assertFalse(item['units'])
