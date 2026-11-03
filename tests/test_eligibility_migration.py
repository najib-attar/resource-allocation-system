"""Upgrade real pre-gate publications without guessing approval or deleting history."""
import os
import uuid
from unittest import mock
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, select
from postgres_fixtures import PostgresTestCase, ROOT
from web.account_service import AccountService
from web.academic_eligibility import EligibilityError, EligibilityService
from web.allocation_workflow import execute_allocation
from web.engine_gateway import EngineGateway
from web.persistence.models import (Allocation,AllocationRun,ApplicationState,RequestDecision,RequestEligibility,
    RequestSlot,Resource,Role,User)
from web.persistence.repository import Repository


class LegacyEligibilityMigrationTests(PostgresTestCase):
    migration_target='0050b'

    def setUp(self):
        super().setUp()
        with self.database.transaction() as session:
            session.add_all([Role(id=1,name='Instructor'),Role(id=2,name='Administrator')])
            session.flush()
            session.add_all([User(id=2,source_order=1,name='Legacy fictional instructor',primary_role_id=1),
                User(id=6,source_order=2,name='Legacy fictional administrator',primary_role_id=2),
                Resource(id=301,source_order=1,type='Classroom',name='Legacy classroom',capacity=20,building='Main')])
            session.flush()
            table=Table('resource_request',MetaData(),autoload_with=session.connection())
            session.execute(table.insert().values(id=1,submission_order=1,type='OneTime',requester_id=2,
                resource_id=301,participant_count=5,title='Legacy published teaching',purpose='Historical declaration',
                required_feature='',required_building='',revision=1))
            session.add(RequestSlot(request_id=1,ordinal=1,day=1,start_minutes=600,end_minutes=660))
        snapshot=dict(protocolVersion=1,runId=uuid.uuid4().hex,strategy='greedy',busySlots=[],
            users=[dict(id=2,name='Legacy fictional instructor',role='Instructor')],
            spaces=[dict(id=301,name='Legacy classroom',type='Classroom',capacity=20,building='Main',available=True,
                         features=dict(projector=False,whiteboard=False,computers=False))],
            requests=[dict(id=1,type='OneTime',requesterId=2,spaceId=301,participantCount=5,
                title='Legacy published teaching',purpose='Historical declaration',slots=[dict(day=1,startMinutes=600,endMinutes=660)])])
        result,build=EngineGateway(ROOT,allow_unbound_allocations=True).execute(snapshot)
        self.assertEqual(result['requestResults'][0]['status'],'Approved')
        with self.database.transaction() as session:
            run=AllocationRun(correlation_id=snapshot['runId'],input_revision=1,strategy='greedy',status='success',
                snapshot=snapshot,build=build,engine_version=result['engineVersion'])
            session.add(run);session.flush();self.old_run=run.id
            decision=result['requestResults'][0]
            session.add(RequestDecision(run_id=run.id,request_id=1,ordinal=1,status='Approved',reason='',payload=decision))
            session.flush()
            a=result['allocations'][0];slot=a['slot']
            session.add(Allocation(run_id=run.id,request_id=1,engine_id=a['allocationId'],resource_id=301,
                day=slot['day'],start_minutes=slot['startMinutes'],end_minutes=slot['endMinutes'],assigned_participants=a['assignedParticipants']))
            state=session.get(ApplicationState,1);state.input_revision=1;state.active_run_id=run.id
        AccountService(self.database).provision(6,'legacy-eligibility-admin','Synthetic-legacy-password',administrator=True)
        with mock.patch.dict(os.environ,{'DATABASE_URL':self.url}):command.upgrade(Config(str(ROOT/'alembic.ini')),'head')
        self.repo=Repository(self.database)
        self.review=EligibilityService(self.database)

    def assert_original(self):
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.get(ApplicationState,1).active_run_id,self.old_run)
            self.assertEqual(len(list(session.scalars(select(Allocation).where(Allocation.run_id==self.old_run)))),1)
            self.assertEqual(session.get(AllocationRun,self.old_run).status,'success')
            self.assertEqual(session.get(RequestDecision,(self.old_run,1)).status,'Approved')

    def test_upgrade_is_fail_closed_and_blocks_engine_without_changing_publication(self):
        self.assert_original()
        with self.database.transaction(read_only=True) as session:
            meta=session.get(RequestEligibility,1)
            self.assertEqual((meta.origin,meta.status,meta.reviewer_id),('Legacy','Pending Eligibility Review',None))
        self.assertEqual(self.review.list_for(6)['outstandingLegacy'],[1])
        gateway=mock.Mock()
        with self.assertRaises(EligibilityError):execute_allocation(self.repo,gateway)
        gateway.execute.assert_not_called()
        self.assert_original()
        # Re-running the upgrade neither grants approval nor rewrites old results.
        with mock.patch.dict(os.environ,{'DATABASE_URL':self.url}):command.upgrade(Config(str(ROOT/'alembic.ini')),'head')
        self.assert_original()

    def test_legacy_rejection_preserves_reservation_until_explicit_replacement(self):
        self.review.decide(6,1,1,0,False,'Legacy declaration is not eligible for future allocation.')
        self.assert_original()
        item=self.review.detail(6,1)
        self.assertEqual(item['status'],'Eligibility Rejected')
        self.assertTrue(item['publishedReservation'])
        self.assertEqual(self.review.list_for(6)['outstandingLegacy'],[])
        self.assertEqual(self.repo.snapshot()['requests'],[])
        execute_allocation(self.repo,EngineGateway(ROOT))
        with self.database.transaction(read_only=True) as session:
            self.assertNotEqual(session.get(ApplicationState,1).active_run_id,self.old_run)
            self.assertEqual(len(list(session.scalars(select(Allocation).where(Allocation.run_id==self.old_run)))),1)
            self.assertEqual(session.get(RequestDecision,(self.old_run,1)).status,'Approved')

    def test_legacy_approval_does_not_allocate_and_downgrade_refuses_history_loss(self):
        self.review.decide(6,1,1,0,True,'Explicitly reviewed the historical teaching declaration.')
        self.assert_original()
        self.assertEqual([r['id'] for r in self.repo.snapshot()['requests']],[1])
        with self.assertRaises(RuntimeError),mock.patch.dict(os.environ,{'DATABASE_URL':self.url}):
            command.downgrade(Config(str(ROOT/'alembic.ini')),'0050b')
        self.assert_original()
