"""Private room/equipment feedback against real PostgreSQL and engine fixtures."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import os
import multiprocessing
import re
import uuid
from unittest import mock

from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from auth_fixtures import authorized_client
from postgres_fixtures import ROOT
from test_appointments import START
from test_equipment import EquipmentFixture
from test_room_requests import RoomFixture
from web import app as web_app
from web.account_service import AccountService
from web.feedback_service import FeedbackError, FeedbackService
from web.room_request_service import RoomRequestError
from web.notification_service import NotificationService, publish_event
from web.persistence.database import Database
from web.persistence.models import (EquipmentUnit, FeedbackEvent, LoginAccount,
    Notification, OrganizationUnit, ResourceFeedback, Role, RoomClosure, RoomInvitation, User)


def submit_feedback_process(url, booking, identity, output):
    database=Database(url)
    try:
        output.put(FeedbackService(database,clock=lambda:START+timedelta(minutes=30)).submit(
            1,'room',booking,302,'problem','Same process-safe feedback',False,identity))
    except Exception as error:
        output.put(type(error).__name__)
    finally:
        database.dispose()


class FeedbackRoomTests(RoomFixture):
    def setUp(self):
        super().setUp()
        self.feedback = FeedbackService(self.database, clock=lambda: START+timedelta(minutes=30))

    def confirmed(self, participants=()):
        key = self.request_room(participantIds=list(participants))
        self.rooms.decide(key, 7, 1, True)
        return key

    def report(self, booking=None, actor=1, category='problem', description='Projector failed', key=None, urgent=False):
        return self.feedback.submit(actor, 'room', booking or self.confirmed(), 302, category,
            description, urgent, key or uuid.uuid4().hex)

    def review(self, key, status='Under Review', actor=7, response='Staff reviewed the resource.', action_key=None, revision=None):
        current = self.feedback.detail(key, actor)
        return self.feedback.update(key, actor, revision or current['revision'], status, 'high', response, action_key or uuid.uuid4().hex)

    def test_optional_active_issue_and_completed_general_feedback(self):
        key = self.confirmed()
        self.assertEqual(self.feedback.list_for(1), [])
        report = self.report(key, urgent=True)
        self.assertEqual(self.feedback.detail(report, 1)['priority'], 'urgent')
        with self.assertRaises(FeedbackError):self.report(key, category='general')
        self.feedback.clock = lambda: START+timedelta(hours=1)
        for category in ('general','improvement'):
            result = self.report(key, category=category, description='Optional after-use feedback')
            self.assertEqual(self.feedback.detail(result, 1)['category'], category)
        self.assertEqual(self.totals(), (1,1))
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(RoomClosure)),0)

    def test_no_pending_future_cancelled_or_fabricated_booking(self):
        pending = self.request_room()
        with self.assertRaises(FeedbackError):self.report(pending)
        self.rooms.decide(pending,7,1,True)
        self.feedback.clock=lambda:START-timedelta(seconds=1)
        with self.assertRaises(FeedbackError):self.report(pending)
        self.feedback.clock=lambda:START
        with self.assertRaises(PermissionError):self.report(pending,actor=4)
        with self.assertRaises(PermissionError):self.feedback.submit(1,'room',pending,301,'problem','Not the booked room',False,uuid.uuid4().hex)
        self.rooms.cancel(pending,1,1)
        with self.assertRaises(FeedbackError):self.report(pending)

    def test_explicit_group_members_can_report_privately_not_estimated_attendees(self):
        AccountService(self.database).provision(5,'feedback-five','Fictional-feedback-password')
        booking=self.confirmed(participants=(4,))
        first,second=self.report(booking),self.report(booking,actor=4,description='Different private problem')
        self.assertEqual(len(self.feedback.list_for(1)),1)
        self.assertEqual(len(self.feedback.list_for(4)),1)
        for actor,other in ((1,second),(4,first),(5,first)):
            with self.assertRaises(PermissionError):self.feedback.detail(other,actor)
        with self.assertRaises(PermissionError):self.report(booking,actor=5)
        self.assertEqual(len(self.feedback.list_for(7,'managed')),2)
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.get(RoomInvitation,(booking,4)).status,'Accepted')

    def test_participant_validation_and_revision_preserve_professor_flow(self):
        for values in ([1],[4,4],[2]):
            with self.assertRaises((PermissionError,RoomRequestError)):
                self.request_room(participantIds=values)
        with self.assertRaises(RoomRequestError):self.request_room(participantIds=[4],count=1)
        booking=self.request_room(invitees=(2,),participantIds=[4])
        self.rooms.respond(booking,2,1,True)
        self.rooms.decide(booking,7,1,True)
        self.assertEqual(self.rooms.detail(booking,4)['participants'][0]['id'],4)
        self.assertEqual(self.rooms.detail(booking,2)['invitations'][0]['status'],'Accepted')

    def test_staff_review_resolution_reopen_clarification_and_full_history(self):
        key=self.report()
        with self.assertRaises(FeedbackError):self.review(key,'Resolved')
        self.review(key)
        self.feedback.update(key,1,2,None,None,'Additional private detail',uuid.uuid4().hex,reply=True)
        self.review(key,'Resolved',response='A'*3999+'Z')
        current=self.feedback.detail(key,1)
        self.assertEqual((current['status'],current['revision']),('Resolved',4))
        self.assertTrue(current['history'][-1]['message'].endswith('Z'))
        with self.assertRaises(FeedbackError):self.feedback.update(key,1,4,None,None,'Late clarification',uuid.uuid4().hex,reply=True)
        self.review(key,'Under Review',response='Reopened because the fault returned')
        self.review(key,'Closed',response='Duplicate maintenance task completed')
        current=self.feedback.detail(key,1)
        self.assertEqual(len(current['history']),6)
        self.assertTrue(all(e['actor'] and e['at'] for e in current['history']))

    def test_reporter_unrelated_student_and_other_faculty_cannot_manage(self):
        key=self.report()
        for actor in (1,4,6):
            with self.assertRaises(PermissionError):self.feedback.update(key,actor,1,'Under Review','normal','Unauthorized',uuid.uuid4().hex)
        self.assertEqual(self.feedback.list_for(6,'managed'),[])
        self.assertEqual(self.feedback.list_for(7,'managed',kind='room',category='problem',status='Submitted',resource='room:302')[0]['id'],key)

    def test_retries_and_competing_updates_are_serialized(self):
        booking=self.confirmed();identity=uuid.uuid4().hex
        with ThreadPoolExecutor(2) as workers:
            keys=list(workers.map(lambda _:self.report(booking,key=identity),range(2)))
        self.assertEqual(keys[0],keys[1])
        with self.assertRaises(FeedbackError):self.report(booking,key=identity,description='Changed content')
        key=keys[0];action=uuid.uuid4().hex
        for _ in range(2):self.review(key,action_key=action,revision=1)
        self.assertEqual(len(self.feedback.detail(key,1)['history']),2)
        def decide(status):
            try:self.review(key,status,revision=2);return True
            except FeedbackError:return False
        with ThreadPoolExecutor(2) as workers:results=list(workers.map(decide,['Resolved','Closed']))
        self.assertEqual(sum(results),1)
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Notification).where(Notification.feedback_event_id.is_not(None))),3)

    def test_two_worker_processes_reuse_one_unchanged_submission(self):
        booking=self.confirmed();identity=uuid.uuid4().hex
        ctx=multiprocessing.get_context('spawn');output=ctx.Queue()
        workers=[ctx.Process(target=submit_feedback_process,args=(self.url,booking,identity,output)) for _ in range(2)]
        for worker in workers:worker.start()
        try:
            results=[output.get(timeout=90) for _ in workers]
            for worker in workers:worker.join(30);self.assertEqual(worker.exitcode,0)
            self.assertEqual(results[0],results[1]);self.assertIsInstance(results[0],int)
            self.assertEqual(len(self.feedback.list_for(1)),1)
        finally:
            for worker in workers:
                if worker.is_alive():worker.terminate();worker.join()
            output.close();output.join_thread()

    def test_booking_mutation_and_feedback_do_not_invert_parent_user_locks(self):
        from threading import Event
        from web.persistence.models import FacultyRoomApprover, StudentRoomRequest
        with self.database.transaction() as session:session.get(LoginAccount,2).administrator=True
        booking=self.request_room(invitees=(2,))
        self.rooms.respond(booking,2,1,True);self.rooms.decide(booking,7,1,True)
        identity=self.feedback._identity
        for source in ('booking','authority'):
            with self.subTest(source=source):
                parent_locked=Event();identity_seen=Event()
                def observed(session,actor,lock=False):
                    identity(session,actor,lock)
                    if source=='booking' or lock:identity_seen.set()
                def booking_write():
                    with self.database.transaction() as session:
                        query=select(StudentRoomRequest).where(StudentRoomRequest.id==booking) if source=='booking' else select(FacultyRoomApprover).where(FacultyRoomApprover.faculty_id==self.other_faculty)
                        session.scalar(query.with_for_update());parent_locked.set()
                        self.assertTrue(identity_seen.wait(10))
                        # Booking events and authority changes need user FK locks.
                        session.scalar(select(User.id).where(User.id==2).with_for_update(read=True,key_share=True))
                with mock.patch.object(self.feedback,'_identity',side_effect=observed),ThreadPoolExecutor(2) as workers:
                    mutation=workers.submit(booking_write)
                    self.assertTrue(parent_locked.wait(10))
                    submitted=workers.submit(self.report,booking,2)
                    mutation.result(timeout=15);key=submitted.result(timeout=15)
                self.assertEqual(self.feedback.detail(key,2)['status'],'Submitted')

    def test_room_manager_closure_scope_and_resource_history_are_preserved(self):
        key=self.report()
        directory=self.rooms.directory(7,configuration=True)
        self.assertEqual([r['id'] for r in directory['rooms']],[302])
        self.assertFalse(directory['canConfigure'])
        with self.assertRaises(PermissionError):self.rooms.close_room(7,301,START+timedelta(hours=1),START+timedelta(hours=2),'Wrong faculty')
        with self.assertRaises(RoomRequestError):self.rooms.close_room(7,302,START,START+timedelta(hours=1),'Cannot silently cancel')
        self.rooms.close_room(7,302,START+timedelta(hours=1),START+timedelta(hours=2),'Projector inspection')
        with self.database.transaction(read_only=True) as session:closure=session.scalar(select(RoomClosure.id))
        self.rooms.reopen_room(7,closure)
        detail=self.feedback.detail(key,1)
        self.assertEqual((detail['status'],detail['revision']),('Submitted',3))
        self.assertEqual(sum('Authorized resource action' in h['message'] for h in detail['history']),2)
        self.assertEqual(self.totals(),(1,1))

    def test_maintenance_notes_are_not_rebroadcast_between_group_reporters(self):
        booking=self.confirmed(participants=(4,))
        first,second=self.report(booking),self.report(booking,actor=4)
        private='PRIVATE_STAFF_NOTE_NOT_FOR_OTHER_REPORTERS'
        self.rooms.close_room(7,302,START+timedelta(hours=1),START+timedelta(hours=2),private)
        self.assertIn(private,self.rooms.directory(7,configuration=True)['closures'][0]['reason'])
        for key,actor in ((first,1),(second,4)):
            history=self.feedback.detail(key,actor)['history']
            self.assertIn('Dated closure added',history[-1]['message'])
            self.assertNotIn(private,history[-1]['message'])

    def test_staff_response_notification_failure_rolls_back_update(self):
        key=self.report()
        with mock.patch('web.feedback_service.publish_event',side_effect=RuntimeError('Notification unavailable')):
            with self.assertRaises(RuntimeError):self.review(key)
        detail=self.feedback.detail(key,1)
        self.assertEqual((detail['status'],detail['revision'],detail['response']),('Submitted',1,''))
        self.assertEqual(len(detail['history']),1)

    def test_accepted_professor_can_report_but_unanswered_invitation_cannot(self):
        booking=self.request_room(invitees=(2,))
        self.rooms.decide(booking,7,1,True)
        with self.assertRaises(PermissionError):self.report(booking,actor=2)
        self.rooms.respond(booking,2,1,True)
        self.assertEqual(self.feedback.detail(self.report(booking,actor=2),2)['reporterId'],2)

    def test_nonempty_feedback_downgrade_is_refused_without_losing_data(self):
        key=self.report()
        with mock.patch.dict(os.environ,{'DATABASE_URL':self.url}):
            with self.assertRaises(RuntimeError):command.downgrade(Config(str(ROOT/'alembic.ini')),'0047a')
        self.assertEqual(self.feedback.detail(key,1)['status'],'Submitted')

    def test_private_notifications_reassignment_and_missing_staff_history(self):
        key=self.report()
        staff_messages=[r for r in NotificationService(self.database).inbox(7)['items'] if r['kind']=='feedback']
        self.assertEqual(len(staff_messages),1)
        self.assertNotIn('Projector failed',staff_messages[0]['message'])
        self.assertFalse(any(r['kind']=='feedback' for r in NotificationService(self.database).inbox(4)['items']))
        self.review(key)
        self.assertEqual(len([r for r in NotificationService(self.database).inbox(1)['items'] if r['kind']=='feedback']),1)
        with self.database.transaction() as session:session.get(LoginAccount,7).enabled=False
        self.assertIn('not configured',self.feedback.detail(key,1)['staff'])
        with self.assertRaises(PermissionError):self.feedback.detail(key,7)

    def test_current_staff_replacement_revokes_old_report_and_receipt_access(self):
        key=self.report()
        self.rooms.configure_approver(6,self.other_faculty,6)
        with self.assertRaises(PermissionError):self.feedback.detail(key,7)
        self.assertEqual([r for r in NotificationService(self.database).inbox(7)['items'] if r['kind']=='feedback'],[])
        self.assertEqual(len(self.feedback.list_for(6,'managed')),1)
        parent=self.feedback.detail(key,6)['bookingId']
        self.assertEqual(self.rooms.detail(parent,6)['id'],parent)
        self.configure_web()
        self.assertEqual(authorized_client(web_app.app,6).get('/rooms/'+str(parent)).status_code,200)
        self.review(key,actor=6)
        with self.database.transaction(read_only=True) as session:self.assertEqual(session.get(ResourceFeedback,key).assigned_to_id,6)

    def test_bounded_validated_inputs_and_skip_create_no_feedback(self):
        booking=self.confirmed()
        for category,description,urgent,identity in [('rating','Text',False,uuid.uuid4().hex),('problem',' ',False,uuid.uuid4().hex),('problem','x'*4001,False,uuid.uuid4().hex),('general','Text',True,uuid.uuid4().hex),('problem','Text',False,'invalid')]:
            with self.assertRaises(FeedbackError):self.feedback.submit(1,'room',booking,302,category,description,urgent,identity)
        self.assertEqual(self.feedback.list_for(1),[])

    def test_notification_failure_rolls_back_entire_report(self):
        booking=self.confirmed()
        def fail(session,event,**kwargs):
            publish_event(session,event,**kwargs)
            raise RuntimeError('Injected failure after notification write')
        with mock.patch('web.feedback_service.publish_event',side_effect=fail):
            with self.assertRaises(RuntimeError):self.report(booking)
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(ResourceFeedback)),0)
            self.assertEqual(session.scalar(select(func.count()).select_from(FeedbackEvent)),0)

    def test_database_rejects_fabricated_associations_and_mutation(self):
        key=self.report()
        with self.assertRaises(IntegrityError),self.database.transaction() as session:session.get(ResourceFeedback,key).reporter_id=4
        with self.assertRaises(IntegrityError),self.database.transaction() as session:
            report=session.get(ResourceFeedback,key)
            session.add(ResourceFeedback(room_request_id=report.room_request_id,room_resource_id=302,room_revision=1,
                reporter_id=4,faculty_id=self.other_faculty,assigned_to_id=7,category='problem',description='Fabricated',submission_key=uuid.uuid4().hex,fingerprint='a'*64))

    def test_database_attendee_count_includes_explicit_group_members(self):
        from web.persistence.models import StudentRoomRequest
        booking=self.confirmed(participants=(4,))
        with self.assertRaises(IntegrityError),self.database.transaction() as session:
            session.get(StudentRoomRequest,booking).attendee_count=1
        self.assertEqual(self.rooms.detail(booking,1)['count'],5)

    def test_flask_form_csrf_privacy_escaping_and_notifications(self):
        booking=self.confirmed();self.configure_web()
        student,staff,other=authorized_client(web_app.app,1),authorized_client(web_app.app,7),authorized_client(web_app.app,4)
        with mock.patch('web.feedback_service.datetime') as clock:
            clock.now.return_value=START+timedelta(minutes=30)
            path='/feedback/new/room/'+str(booking)
            page=student.get(path);self.assertEqual(page.status_code,200)
            submission=re.search(r'name="submission_key" value="([^"]+)"',page.text).group(1)
            response=student.post(path,data={'resourceId':'302','category':'problem','description':'<script>private</script>','submission_key':submission})
            self.assertEqual(response.status_code,302);detail=response.location
            self.assertIn(b'&lt;script&gt;',student.get(detail).data)
            self.assertEqual(other.get(detail).status_code,403)
            page=staff.get(detail);self.assertEqual(page.status_code,200)
            action=re.search(r'name="action_key" value="([^"]+)"',page.text).group(1)
            self.assertEqual(staff.client.post(detail+'/update',data={}).status_code,400)
            self.assertEqual(staff.post(detail+'/update',data={'action':'review','revision':'1','status':'Under Review','priority':'urgent','response':'Inspection started','action_key':action}).status_code,302)
            self.assertIn('Private resource report',student.get('/notifications/feed').json['html'])
            self.assertEqual(student.get('/feedback/?scope=mine').status_code,200)
            self.assertEqual(staff.get('/feedback/?scope=managed&status=Under+Review').status_code,200)

    def test_migration_drift_and_safe_empty_downgrade(self):
        config=Config(str(ROOT/'alembic.ini'))
        with mock.patch.dict(os.environ,{'DATABASE_URL':self.url}):
            command.check(config)
            command.downgrade(config,'0047a')
            command.upgrade(config,'head')
        with self.database.transaction(read_only=True) as session:self.assertEqual(session.scalar(text('SELECT version_num FROM alembic_version')),'0048a')


class FeedbackEquipmentTests(EquipmentFixture):
    def setUp(self):
        super().setUp()
        self.feedback=FeedbackService(self.database,clock=lambda:START+timedelta(hours=2))

    def loan(self, quantity=1):
        key=self.request(quantity);self.service.decide(6,key,True);self.handover(key)
        return key

    def report(self, booking, reservation=None, category='problem', actor=1):
        context=self.feedback.context('equipment',booking,actor)
        return self.feedback.submit(actor,'equipment',booking,reservation or context['resources'][0]['id'],category,'Fictional device problem',False,uuid.uuid4().hex)

    def test_approved_but_not_collected_cannot_report(self):
        key=self.request();self.service.decide(6,key,True)
        with self.assertRaises(FeedbackError):self.feedback.context('equipment',key,1)
        self.assertEqual(self.feedback.list_for(1),[])

    def test_active_loan_problem_and_verified_return_feedback(self):
        key=self.loan();report=self.report(key)
        self.assertEqual(self.feedback.detail(report,6)['status'],'Submitted')
        with self.assertRaises(FeedbackError):self.report(key,category='general')
        self.service.intend_return(1,key)
        with self.assertRaises(FeedbackError):self.report(key,category='improvement')
        self.return_units(key,[self.units[0]],'usable','Verified physical return')
        report=self.report(key,category='general')
        self.assertEqual(self.feedback.detail(report,1)['category'],'general')

    def test_partial_return_is_checked_per_actual_unit(self):
        key=self.loan(2)
        self.return_units(key,[self.units[0]],'usable','One verified return')
        context=self.feedback.context('equipment',key,1)
        self.assertEqual(sorted(r['completed'] for r in context['resources']),[False,True])
        for row in context['resources']:
            if row['completed']:self.report(key,row['id'],'general')
            else:
                with self.assertRaises(FeedbackError):self.report(key,row['id'],'general')

    def test_unrelated_borrower_and_foreign_unit_rejected(self):
        key=self.loan()
        with self.assertRaises(PermissionError):self.feedback.context('equipment',key,4)
        other=self.request(actor=4);self.service.decide(6,other,True);self.handover(other)
        foreign=self.feedback.context('equipment',other,4)['resources'][0]['id']
        with self.assertRaises(PermissionError):self.report(key,foreign)

    def test_reporting_is_not_inventory_mutation_or_automatic_return(self):
        key=self.loan();report=self.report(key)
        self.feedback.update(report,6,1,'Under Review','high','Inspect device before reuse',uuid.uuid4().hex)
        with self.database.transaction(read_only=True) as session:self.assertEqual(session.get(EquipmentUnit,self.units[0]).condition,'usable')
        self.assertEqual(self.service.detail(1,key)['status'],'Borrowed')
        self.service.set_condition(6,self.units[0],'damaged','Custodian inspection decision')
        self.assertEqual(self.service.detail(1,key)['status'],'Borrowed')
        self.assertEqual(self.feedback.list_for(4,'managed'),[])

    def test_custodian_replies_resolves_and_report_survives_restart(self):
        key=self.loan();report=self.report(key)
        self.feedback.update(report,6,1,'Under Review','normal','Examining returned accessory',uuid.uuid4().hex)
        self.feedback.update(report,6,2,'Resolved','normal','Accessory replaced',uuid.uuid4().hex)
        reloaded=FeedbackService(self.database)
        self.assertEqual(reloaded.detail(report,1)['status'],'Resolved')
        self.assertEqual(len(reloaded.detail(report,1)['history']),3)

    def test_other_faculty_custodian_cannot_read_or_modify_private_reports(self):
        booking=self.loan();report=self.report(booking)
        with self.database.transaction() as session:
            faculty=OrganizationUnit(name='Fictional Other Faculty',unit_type='Faculty');session.add(faculty);session.flush();other=faculty.id
            role=session.scalar(select(Role.id).where(Role.name=='Staff'))
            session.add(User(id=7,source_order=7,name='Fictional Other Custodian',primary_role_id=role))
        AccountService(self.database).provision(7,'other-custodian','Fictional-other-password')
        self.service.assign_custodian(6,other,7)
        self.assertEqual(self.feedback.list_for(7,'managed'),[])
        with self.assertRaises(PermissionError):self.feedback.detail(report,7)
        with self.assertRaises(PermissionError):self.feedback.update(report,7,1,'Under Review','normal','Unrelated faculty',uuid.uuid4().hex)

    def test_equipment_form_and_condition_audit_are_private(self):
        booking=self.loan();self.configure_web()
        student,staff=authorized_client(web_app.app,1),authorized_client(web_app.app,6)
        with mock.patch('web.feedback_service.datetime') as clock:
            clock.now.return_value=START+timedelta(hours=2)
            path='/feedback/new/equipment/'+str(booking);page=student.get(path)
            self.assertEqual(page.status_code,200)
            identity=re.search(r'name="submission_key" value="([^"]+)"',page.text).group(1)
            resource=self.feedback.context('equipment',booking,1)['resources'][0]['id']
            created=student.post(path,data={'resourceId':str(resource),'category':'problem','description':'Faulty board','submission_key':identity})
            self.assertEqual(created.status_code,302);key=int(created.location.rstrip('/').split('/')[-1])
            self.assertEqual(staff.get(created.location).status_code,200)
            self.service.set_condition(6,self.units[0],'damaged','Verified custodian inspection')
            self.assertIn('Authorized resource action',self.feedback.detail(key,1)['history'][-1]['message'])
            self.assertNotIn('Verified custodian inspection',self.feedback.detail(key,1)['history'][-1]['message'])
            self.assertEqual(student.get(created.location).headers['Cache-Control'],'private, no-store')

    def test_failed_condition_notification_rolls_back_inventory_and_report_history(self):
        booking=self.loan();report=self.report(booking)
        with mock.patch('web.feedback_state.publish_event',side_effect=RuntimeError('Injected private notification failure')):
            with self.assertRaises(RuntimeError):self.service.set_condition(6,self.units[0],'damaged','Inspected faulty unit')
        with self.database.transaction(read_only=True) as session:self.assertEqual(session.get(EquipmentUnit,self.units[0]).condition,'usable')
        self.assertEqual(len(self.feedback.detail(report,1)['history']),1)
