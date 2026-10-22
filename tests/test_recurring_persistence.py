import os
import uuid
from datetime import timedelta
from unittest import mock

from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from postgres_fixtures import ROOT
from test_room_requests import RoomFixture, START
from web.calendar_service import university_zone
from web.persistence.models import Base, ReservationOccurrence, ReservationSeries, RoomReservation, StudentRoomRequest
from web.recurrence import expand_recurrence


class RecurringPersistenceTests(RoomFixture):
    def add_series(self, *, incomplete=False):
        key=self.request_room()
        local=START.astimezone(university_zone())
        expanded=expand_recurrence({'startDate':local.date().isoformat(),
            'endDate':(local.date()+timedelta(days=7)).isoformat(),'weekdays':[local.isoweekday()],
            'startTime':local.strftime('%H:%M')},60)
        with self.database.transaction() as session:
            row=ReservationSeries(room_request_id=key,start_date=expanded['startDate'],end_date=expanded['endDate'],
                start_minutes=expanded['startMinutes'],duration_minutes=60,weekdays=expanded['weekdays'],
                timezone=expanded['timezone'],submission_key=uuid.uuid4().hex,fingerprint='a'*64)
            session.add(row);session.flush()
            intervals=expanded['intervals'][:1] if incomplete else expanded['intervals']
            session.add_all(ReservationOccurrence(series_id=row.id,ordinal=i,start_at=a,end_at=b)
                for i,(a,b) in enumerate(intervals,1))
            return key,row.id

    def test_complete_pending_series_has_stable_occurrences_and_no_hold(self):
        key,series=self.add_series()
        with self.database.transaction(read_only=True) as session:
            rows=list(session.scalars(select(ReservationOccurrence).where(ReservationOccurrence.series_id==series).order_by(ReservationOccurrence.ordinal)))
            self.assertEqual(len(rows),2)
            self.assertEqual(rows[1].start_at-rows[0].start_at,timedelta(days=7))
            self.assertEqual({r.status for r in rows},{'Proposed'})
            self.assertEqual(session.get(StudentRoomRequest,key).status,'Pending Faculty Approval')
        self.assertEqual(self.totals(),(0,0))

    def test_missing_occurrence_is_rejected_at_commit(self):
        with self.assertRaises(IntegrityError):self.add_series(incomplete=True)

    def test_pending_series_cannot_claim_confirmed_reservations(self):
        key,series=self.add_series()
        with self.assertRaises(IntegrityError),self.database.transaction() as session:
            occurrence=session.scalar(select(ReservationOccurrence).where(ReservationOccurrence.series_id==series))
            session.add(RoomReservation(request_id=key,resource_id=302,start_at=occurrence.start_at,end_at=occurrence.end_at,occurrence_id=occurrence.id))
        self.assertEqual(self.totals(),(0,0))

    def test_original_dates_and_series_association_cannot_be_rewritten(self):
        key,series=self.add_series()
        with self.assertRaises(IntegrityError),self.database.transaction() as session:
            session.get(ReservationSeries,series).end_date+=timedelta(days=7)
        with self.assertRaises(IntegrityError),self.database.transaction() as session:
            session.scalar(select(ReservationOccurrence).where(ReservationOccurrence.series_id==series)).start_at+=timedelta(days=1)
        with self.assertRaises(IntegrityError),self.database.transaction() as session:
            session.delete(session.get(ReservationSeries,series))

    def test_nonempty_downgrade_refuses_to_remove_history(self):
        self.add_series()
        with mock.patch.dict(os.environ,{'DATABASE_URL':self.url}),self.assertRaisesRegex(RuntimeError,'history'):
            command.downgrade(Config(str(ROOT/'alembic.ini')),'0048a')
        with self.database.transaction(read_only=True) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(ReservationSeries)),1)

    def test_migration_drift_and_empty_downgrade_preserve_one_time_records(self):
        key=self.request_room();self.rooms.decide(key,7,1,True)
        with mock.patch.dict(os.environ,{'DATABASE_URL':self.url}):
            configuration=Config(str(ROOT/'alembic.ini'))
            command.check(configuration)
            command.downgrade(configuration,'0048a')
            command.upgrade(configuration,'head')
            command.check(configuration)
        self.assertEqual(len(Base.metadata.tables),52)
        self.assertEqual(self.rooms.detail(key,1)['status'],'Confirmed')
        self.assertEqual(self.totals(),(1,1))
