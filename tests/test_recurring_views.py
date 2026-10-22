"""Recurring workflows use the existing authenticated routes and calendar sources."""
from copy import deepcopy
from datetime import timedelta
import uuid
import re
from unittest import mock

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from auth_fixtures import authorized_client
from test_room_requests import START
from recurring_fixtures import RoomFixture,EquipmentFixture
from test_recurring_workflows import pattern
from runtime_file_guard import forbid_runtime_files
from web import app as web_app
from web.calendar_service import CalendarError
from web.engine_gateway import EngineIntegrationError,validate_room_series_result,validate_equipment_series_result
from web.feedback_service import FeedbackService
from web.notification_service import NotificationService
from web.personal_schedule_service import PersonalScheduleService
from web.persistence.models import BorrowExtension,WaitingListEntry
from web.student_dashboard_service import StudentDashboardService
from web.university_calendar import UniversityCalendarService
from web.waiting_list_service import WaitingListService,POLICY_VERSION


class RecurringRoomViewsTests(RoomFixture):
    def series(self,**changes):
        return self.rooms.submit(1,self.values(recurrence=pattern(),**changes),[],302,submission_key=uuid.uuid4().hex)

    def test_flask_preview_submission_review_and_scoped_cancellation(self):
        client=self.configure_web()
        data=dict(category='study',purpose='Weekly project',count='5',duration='60',roomId='302',
            reservationMode='weekly',academicPeriod=str(self.semester),recurrenceStart='2030-01-07',recurrenceEnd='2030-01-14',
            recurrenceDays='1',recurrenceTime='10:00',submission_key=uuid.uuid4().hex)
        with forbid_runtime_files():
            self.assertEqual(client.get('/rooms/new').status_code,200)
            preview=client.post('/rooms/candidates',data=data)
            self.assertEqual(preview.status_code,200)
            self.assertEqual(len(preview.json['occurrences']),2)
            saved=client.post('/rooms/new',data=data)
            self.assertEqual(saved.status_code,302)
            self.assertIn(b'Complete recurring series',client.get(saved.location).data)
            key=int(saved.location.rsplit('/',1)[1])
            manager=authorized_client(web_app.app,7)
            self.assertEqual(manager.post(saved.location+'/decision',data={'revision':'1','decision':'approve'}).status_code,302)
            occurrence=self.rooms.detail(key,1)['recurrence']['occurrences'][1]['id']
            path=saved.location+'/occurrences/'+str(occurrence)+'/cancel'
            self.assertEqual(authorized_client(web_app.app,4).post(path,data={'revision':'1'}).status_code,403)
            self.assertEqual(client.client.post(path,data={'revision':'1'}).status_code,400)
            self.assertEqual(client.post(path,data={'revision':'1'}).status_code,302)
            self.assertEqual(self.totals(),(1,1))

    def test_later_week_home_and_calendars_follow_actual_reservations(self):
        key=self.series();self.rooms.decide(key,7,1,True)
        calendar=UniversityCalendarService(self.database)
        events=calendar.load(1,day='2030-01-14',view='week',now=START)['events']
        rooms=[e for e in events if e['category']=='room']
        self.assertEqual(len(rooms),1);self.assertTrue(rooms[0]['busy'])
        self.assertEqual(calendar.load(4,day='2030-01-14',view='week',now=START)['events'],[])
        schedule=PersonalScheduleService(self.database).load(1,week='2030-01-14',now=START)
        self.assertTrue(any(e.get('roomRequestId')==key for d in schedule['days'] for e in d['entries']))
        self.assertEqual(StudentDashboardService(self.database).load(1,now=START+timedelta(days=1))['roomCounts']['confirmed'],1)
        occurrence=self.rooms.detail(key,1)['recurrence']['occurrences'][1]['id']
        self.rooms.cancel_occurrence(key,1,1,occurrence)
        event=next(e for e in calendar.load(1,day='2030-01-14',view='week',now=START)['events'] if e['category']=='room')
        self.assertEqual(event['state'],'cancelled');self.assertFalse(event['busy'])
        self.assertEqual(StudentDashboardService(self.database).load(1,now=START+timedelta(days=1))['roomCounts']['confirmed'],0)

    def test_cancelled_first_date_is_not_proof_of_resource_use(self):
        key=self.series();self.rooms.decide(key,7,1,True)
        first=self.rooms.detail(key,1)['recurrence']['occurrences'][0]['id']
        self.rooms.cancel_occurrence(key,1,1,first)
        feedback=FeedbackService(self.database,clock=lambda:START+timedelta(hours=2))
        with self.assertRaises(CalendarError):feedback.context('room',key,1)

    def test_series_rejects_waiting_split_and_database_association(self):
        waiting=WaitingListService(self.database,self.rooms.gateway)
        with self.assertRaises(CalendarError):waiting.join_room(1,self.values(recurrence=pattern()),[],self.other_faculty,POLICY_VERSION,True,uuid.uuid4().hex)
        key=self.series()
        with self.assertRaises(IntegrityError),self.database.transaction() as session:
            session.add(WaitingListEntry(owner_id=1,faculty_id=self.other_faculty,room_request_id=key,
                submission_key=uuid.uuid4().hex,fingerprint='a'*64,queue_key='b'*64,policy_version=POLICY_VERSION,notice_minutes=60))

    def test_gateway_validates_full_occurrence_collection_and_notifications_are_idempotent(self):
        result,_,snapshot,_=self.rooms._evaluate(1,self.values(recurrence=pattern()),[])
        for field in ('runId','occurrences','feasible','protocolVersion'):
            invalid=deepcopy(result)
            if field=='runId':invalid[field]='foreign'
            if field=='occurrences':invalid[field]=invalid[field][:-1]
            if field=='feasible':invalid['occurrences'][1]['start']+=60
            if field=='protocolVersion':invalid[field]=2
            with self.assertRaises(EngineIntegrationError):validate_room_series_result(invalid,snapshot)
        identity=uuid.uuid4().hex
        key=self.rooms.submit(1,self.values(recurrence=pattern()),[],302,submission_key=identity)
        before=NotificationService(self.database).inbox(7)['unreadCount']
        self.rooms.submit(1,self.values(recurrence=pattern()),[],302,submission_key=identity)
        self.assertEqual(NotificationService(self.database).inbox(7)['unreadCount'],before)
        self.rooms.decide(key,7,1,False,'Revision required')
        self.assertEqual(self.rooms.detail(key,1)['status'],'Rejected');self.assertEqual(self.totals(),(0,0))


class RecurringEquipmentViewsTests(EquipmentFixture):
    def series(self):
        return self.service.submit(1,self.faculty,[{'typeId':self.type_id,'quantity':2}],START,
            START+timedelta(hours=2),'Weekly boards','',uuid.uuid4().hex,pattern())

    def test_flask_preview_complete_approval_and_one_occurrence_cancel(self):
        client=self.configure_web()
        data=dict(start='2030-01-07T10:00',due='2030-01-07T12:00',faculty=str(self.faculty),purpose='Weekly boards',
            reservationMode='weekly',academicPeriod=str(self.semester),recurrenceStart='2030-01-07',recurrenceEnd='2030-01-14',recurrenceDays='1',
            recurrenceTime='10:00',submission_key=uuid.uuid4().hex,action='recommend')
        data['qty_'+str(self.type_id)]='2'
        with forbid_runtime_files():
            preview=client.post('/equipment/catalog',data=data)
            self.assertEqual(preview.status_code,200);self.assertIn(b'Complete dated preview',preview.data)
            data['previewToken']=re.search(rb'name="previewToken" value="([^"]+)"',preview.data).group(1).decode()
            data['action']='submit';saved=client.post('/equipment/catalog',data=data)
            self.assertEqual(saved.status_code,302)
            manager=authorized_client(web_app.app,6)
            self.assertEqual(manager.post(saved.location+'/approve').status_code,302)
            key=int(saved.location.rsplit('/',1)[1]);item=self.service.detail(1,key)
            self.assertIn(b'Recurring pickups',client.get(saved.location).data)
            self.assertEqual(manager.post(saved.location+'/cancel-occurrence',data={'occurrenceId':item['recurrence']['occurrences'][1]['id']}).status_code,302)
            self.assertEqual(client.post(saved.location+'/handover',data={'condition':'Usable','occurrenceId':item['recurrence']['occurrences'][0]['id']}).status_code,403)
            data['action']='wait';self.assertEqual(client.post('/equipment/catalog',data=data).status_code,409)

    def test_calendar_pickups_and_due_dates_are_separate_nonbusy_reminders(self):
        key=self.series();self.service.decide(6,key,True)
        events=UniversityCalendarService(self.database).load(1,view='month',day='2030-01-07',now=START)['events']
        reminders=[e for e in events if e['category']=='equipment']
        self.assertEqual(len(reminders),4);self.assertTrue(all(e['reminder'] and not e['busy'] for e in reminders))
        self.assertEqual(UniversityCalendarService(self.database).load(4,day='2030-01-07',now=START)['events'],[])

    def test_extensions_cannot_overlap_next_occurrence_and_can_extend_selected_loan(self):
        key=self.series();self.service.decide(6,key,True)
        first,second=self.service.detail(1,key)['recurrence']['occurrences']
        with mock.patch('web.equipment_service.datetime') as clock:
            clock.now.return_value=START+timedelta(minutes=10)
            self.service.handover(6,key,'Usable',first['id'])
            ext=self.service.request_extension(1,key,START+timedelta(days=8),'Overlaps next pickup',first['id'])
            with self.assertRaises(CalendarError):self.service.decide_extension(6,key,ext,True)
            self.service.decide_extension(6,key,ext,False)
            ext=self.service.request_extension(1,key,START+timedelta(hours=3),'One additional hour',first['id'])
            self.service.decide_extension(6,key,ext,True)
        self.assertEqual(self.service.detail(1,key)['recurrence']['occurrences'][0]['due'],START+timedelta(hours=3))
        self.assertEqual(self.service.detail(1,key)['recurrence']['occurrences'][1]['due'],second['end'])

    def test_extension_occurrence_cannot_reference_another_series(self):
        first=self.series();second=self.series()
        foreign=self.service.detail(1,second)['recurrence']['occurrences'][0]['id']
        with self.assertRaises(IntegrityError),self.database.transaction() as session:
            session.add(BorrowExtension(request_id=first,occurrence_id=foreign,due_at=START+timedelta(hours=3),reason='Invalid association'))

    def test_gateway_rejects_partial_mismatched_and_ambiguous_series_results(self):
        with self.database.transaction(read_only=True) as session:
            snapshot=self.service._snapshot(session,1,self.faculty,[{'typeId':self.type_id,'quantity':1,'specifications':{}}],START,START+timedelta(hours=2))
        snapshot.update(operation='equipmentSeries',occurrences=[snapshot['proposed'],
            {k:v+7*86400 for k,v in snapshot['proposed'].items()}])
        result,_=self.service.gateway.execute_equipment_series(snapshot)
        for change in ('operation','dates','missing','aggregate','ambiguous'):
            invalid=deepcopy(result)
            if change=='operation':invalid['operation']='equipment'
            if change=='dates':invalid['occurrences'][1]['end']+=60
            if change=='missing':invalid['occurrences'].pop()
            if change=='aggregate':invalid['feasible']=False
            if change=='ambiguous':invalid['items']=invalid['occurrences'][0]['items']
            with self.subTest(change=change),self.assertRaises(EngineIntegrationError):validate_equipment_series_result(invalid,snapshot)
