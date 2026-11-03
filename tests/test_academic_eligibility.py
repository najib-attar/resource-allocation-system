"""Actual PostgreSQL/engine evidence for the administrative eligibility boundary."""
from concurrent.futures import ThreadPoolExecutor
from unittest import mock
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from postgres_fixtures import ROOT
from test_professor_services import ProfessorFixture
from web.academic_eligibility import EligibilityError, EligibilityService
from web.allocation_workflow import execute_allocation
from web.engine_gateway import EngineGateway
from web.persistence.models import (Allocation, ApplicationState, EligibilityEvent, RequestEligibility,
    RequestSlot, ResourceRequest)
from web.persistence.repository import StaleRun, snapshot_from_session


class EligibilityGateTests(ProfessorFixture):
    def setUp(self):
        super().setUp()
        self.review = EligibilityService(self.database)

    def decision(self,key,approve=True,version=None):
        with self.database.transaction(read_only=True) as session:
            row=session.get(ResourceRequest,key)
            meta=session.get(RequestEligibility,key)
            revision=row.revision
            version=meta.version if version is None else version
        return self.review.decide(6,key,revision,version,approve,'Reviewed synthetic academic declarations.')

    def test_pending_and_rejected_requests_never_enter_any_repository_engine_snapshot(self):
        pending=self.academic_request()
        rejected=self.academic_request(day=2)
        eligible=self.academic_request(day=3)
        self.decision(rejected,False)
        self.decision(eligible)
        self.assertEqual([r['id'] for r in self.repository.snapshot()['requests']],[eligible])
        with self.database.transaction(read_only=True) as session:
            self.assertEqual([r['id'] for r in snapshot_from_session(session,'greedy')['requests']],[eligible])
        run,snapshot=self.repository.start_run()
        self.assertEqual([r['id'] for r in snapshot['requests']],[eligible])
        gateway=EngineGateway(ROOT)
        seen=[]
        original=gateway._execute
        def capture(value,*args):
            seen.extend(r['id'] for r in value['requests'])
            return original(value,*args)
        with mock.patch.object(gateway,'_execute',side_effect=capture):
            result=execute_allocation(self.repository,gateway)
        self.assertEqual(seen,[eligible])
        self.assertEqual([r['requestId'] for r in result['requestResults']],[eligible])
        self.assertNotIn(pending,seen)

    def test_review_is_not_allocation_and_all_roles_cannot_approve(self):
        key=self.academic_request()
        for actor in (1,2,3,7):
            with self.assertRaises(PermissionError):
                self.review.decide(actor,key,1,0,True,'Not authorized')
        self.decision(key)
        with self.database.transaction(read_only=True) as session:
            self.assertIsNone(session.get(ApplicationState,1).active_run_id)
            self.assertEqual(list(session.scalars(select(Allocation))),[])
            self.assertEqual(list(session.scalars(select(EligibilityEvent.actor_id).where(
                EligibilityEvent.request_id==key).order_by(EligibilityEvent.version)))[-1],6)

    def test_stale_decisions_concurrent_review_and_reason_validation(self):
        key=self.academic_request()
        with self.assertRaises(EligibilityError):self.review.decide(6,key,1,0,True,'')
        def decide(approve):
            try:return self.review.decide(6,key,1,0,approve,'Concurrent reviewer decision')
            except EligibilityError:return 'stale'
        with ThreadPoolExecutor(2) as pool:
            outcomes=list(pool.map(decide,(True,False)))
        self.assertEqual(outcomes.count('stale'),1)
        self.assertIn(outcomes[0] if outcomes[0]!='stale' else outcomes[1],('Eligible','Eligibility Rejected'))

    def test_material_parent_and_child_changes_invalidate_approval_at_database_boundary(self):
        key=self.academic_request()
        self.decision(key)
        with self.database.transaction() as session:
            session.get(ResourceRequest,key).title='Changed declaration'
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.get(ResourceRequest,key).revision,2)
            self.assertEqual(session.get(RequestEligibility,key).status,'Pending Eligibility Review')
        self.decision(key)
        with self.database.transaction() as session:
            slot=session.scalar(select(RequestSlot).where(RequestSlot.request_id==key))
            slot.start_minutes+=15
        self.assertEqual(self.repository.snapshot()['requests'],[])

    def test_changed_eligibility_invalidates_captured_input_and_inflight_publication(self):
        key=self.academic_request()
        self.decision(key)
        run,snapshot=self.repository.start_run()
        result,build=EngineGateway(ROOT).execute(snapshot)
        self.decision(key,False)
        with self.assertRaises(StaleRun):EngineGateway(ROOT).execute(snapshot)
        with self.assertRaises(StaleRun):self.repository.publish_run(run,result,build)
        with self.database.transaction(read_only=True) as session:
            self.assertIsNone(session.get(ApplicationState,1).active_run_id)

    def test_presentation_input_and_tampered_allocation_input_cannot_reach_engine(self):
        key=self.academic_request()
        raw,_,_=self.repository.read_view()
        with self.assertRaises(EligibilityError):EngineGateway(ROOT).execute(raw)
        snapshot=self.repository.snapshot()
        snapshot['requests']=raw['requests']
        with self.assertRaises(StaleRun):EngineGateway(ROOT).execute(snapshot)

    def test_direct_invalid_review_and_audit_rewrites_are_rejected_by_database(self):
        key=self.academic_request()
        with self.assertRaises(IntegrityError),self.database.transaction() as session:
            session.execute(update(RequestEligibility).where(RequestEligibility.request_id==key).values(
                status='Eligible',version=1,reviewed_revision=1,reviewer_id=2,reason='Self review',decided_at=text('now()')))
        with self.assertRaises(IntegrityError),self.database.transaction() as session:
            session.execute(text('UPDATE eligibility_event SET reason=:reason'),dict(reason='rewritten'))
