"""Scope legacy projection in SQL without changing explicit calendar semantics."""

from collections import Counter
from datetime import date, timedelta

from sqlalchemy import delete, event

from test_appointments import AppointmentFixture, START
from web.allocation_workflow import execute_allocation
from web.calendar_service import epoch, legacy_intervals
from web.persistence.models import BusySlot, LegacyCalendarBinding
from web.persistence.repository import Repository, state_row


class CalendarLoadingTests(AppointmentFixture):
    def request(self, **changes):
        values = {'type': 'OneTime', 'requesterId': 3, 'spaceId': 301, 'participantCount': 3,
                  'title': 'Fictional university commitment', 'purpose': 'Teaching',
                  'slots': [{'day': 1, 'startMinutes': 600, 'endMinutes': 660}]}
        return Repository(self.database).save_request(values | changes)

    def busy(self, person, ordinal):
        with self.database.transaction() as session:
            row = BusySlot(user_id=person, source_order=ordinal, day=1,
                           start_minutes=600, end_minutes=660, reason='Fictional course')
            session.add(row)
            session.flush()
            return row.id

    def test_projection_loads_only_relevant_rows_with_bounded_queries(self):
        own, other = self.busy(1, 1), self.busy(4, 2)
        for key in (own, other):
            self.service.bind_legacy('Fictional January', date(2030, 1, 1), date(2030, 1, 31), busy_id=key)
        request = self.request()
        self.service.bind_legacy('Fictional February', date(2030, 2, 1), date(2030, 2, 28),
                                 request_id=request, week_start=date(2030, 2, 4))
        execute_allocation(Repository(self.database), self.service.gateway)
        loaded, queries = Counter(), []
        with self.database.transaction(read_only=True) as session:
            run = state_row(session).active_run_id
            event.listen(session, 'loaded_as_persistent', lambda _, row: loaded.update([type(row).__name__]))
            def record(_, __, statement, *args):
                if statement.lstrip().upper().startswith('SELECT'):
                    queries.append(statement)
            event.listen(self.database.engine, 'before_cursor_execute', record)
            try:
                values, unresolved = legacy_intervals(session, [1], START, START + timedelta(days=1), run)
            finally:
                event.remove(self.database.engine, 'before_cursor_execute', record)
        self.assertEqual(values, [{'userId': 1, 'start': epoch(START), 'end': epoch(START + timedelta(hours=1))}])
        self.assertEqual(unresolved, [])
        self.assertEqual(loaded, Counter({'BusySlot': 1, 'LegacyCalendarBinding': 1, 'AcademicPeriod': 1}),
                         f'{sum(loaded.values())} ORM rows, {len(queries)} SELECTs: {dict(loaded)}')
        self.assertLessEqual(len(queries), 3)

    def test_empty_people_does_not_load_unrelated_calendars(self):
        key = self.busy(1, 1)
        self.service.bind_legacy('Fictional term', date(2030, 1, 1), date(2030, 1, 31), busy_id=key)
        loaded = []
        with self.database.transaction(read_only=True) as session:
            event.listen(session, 'loaded_as_persistent', lambda _, row: loaded.append(row))
            self.assertEqual(legacy_intervals(session, [], START, START + timedelta(days=1)), ([], []))
        self.assertEqual(loaded, [])

    def test_required_members_active_run_and_bound_outside_horizon_remain_correct(self):
        request = self.request(type='CommitteeMeeting', requesterId=2,
            participants=[{'userId': 1, 'role': 'Member'}, {'userId': 3, 'role': 'Member'}])
        self.service.bind_legacy('Fictional planning week', date(2030, 1, 7), date(2030, 1, 31),
                                 request_id=request, week_start=date(2030, 1, 7))
        repository = Repository(self.database)
        for _ in range(2):
            result = execute_allocation(repository, self.service.gateway)
            self.assertEqual(result['requestResults'][0]['status'], 'Approved')
        with self.database.transaction() as session:
            run = state_row(session).active_run_id
            for actor in (1, 2, 3):
                values, unresolved = legacy_intervals(session, [actor], START, START + timedelta(days=1), run, True)
                self.assertEqual(values, [{'userId': actor, 'start': epoch(START),
                    'end': epoch(START + timedelta(hours=1)), 'title': 'Fictional university commitment'}])
                self.assertEqual(unresolved, [])
            self.assertEqual(legacy_intervals(session, [4], START, START + timedelta(days=1), run), ([], []))
            self.assertEqual(legacy_intervals(session, [1], START + timedelta(days=7), START + timedelta(days=8), run), ([], []))
            session.execute(delete(LegacyCalendarBinding).where(LegacyCalendarBinding.request_id == request))
            self.assertEqual(legacy_intervals(session, [1], START, START + timedelta(days=1), run), ([], [1]))
