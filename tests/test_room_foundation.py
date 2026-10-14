"""Additive room schema integrity; no speculative ownership or academic dates."""

from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from postgres_fixtures import PostgresTestCase
from test_appointments import seed_appointments, START
from web.account_service import AccountService
from web.persistence.models import FacultyRoomApprover, RoomPolicy, RoomReservation, StudentRoomRequest


class RoomFoundationTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        self.faculty = seed_appointments(self.database)
        AccountService(self.database).provision(6, 'faculty-admin', 'Isolated-fictional-password', administrator=True)

    def record(self, **values):
        from datetime import timedelta
        fields = dict(organizer_id=1, resource_id=301, faculty_id=self.faculty, approver_id=6,
                      category='study', purpose='Group study', attendee_count=5, required_features=[],
                      start_at=START, end_at=START+timedelta(hours=1), duration_minutes=60)
        fields.update(values)
        return StudentRoomRequest(**fields)

    def test_additive_schema_has_no_automatic_bookable_rooms_or_reservations(self):
        self.assertIn('room_reservation', inspect(self.database.engine).get_table_names())
        with self.database.transaction(read_only=True) as session:
            self.assertIsNone(session.scalar(select(RoomPolicy)))
            self.assertIsNone(session.scalar(select(RoomReservation)))

    def test_faculty_ownership_and_categories_are_constrained(self):
        with self.assertRaises(IntegrityError), self.database.transaction() as session:
            session.add(RoomPolicy(resource_id=301, faculty_id=self.faculty, categories=['unapproved']))
        with self.database.transaction() as session:
            session.add(FacultyRoomApprover(faculty_id=self.faculty, user_id=6))
            session.add(RoomPolicy(resource_id=301, faculty_id=self.faculty, enabled=True))

    def test_pending_requests_reserve_nothing_and_cannot_have_reservations(self):
        from datetime import timedelta
        with self.database.transaction() as session:
            row = self.record()
            session.add(row)
            session.flush()
            key = row.id
        with self.assertRaises(IntegrityError), self.database.transaction() as session:
            session.add(RoomReservation(request_id=key, resource_id=301, start_at=START, end_at=START+timedelta(hours=1)))

    def test_confirmed_request_requires_exact_approval_and_commitments(self):
        with self.assertRaises(IntegrityError), self.database.transaction() as session:
            session.add(self.record(status='Confirmed', approved_revision=1, approved_by=6))
        with self.assertRaises(IntegrityError), self.database.transaction() as session:
            session.add(self.record(status='Confirmed'))
