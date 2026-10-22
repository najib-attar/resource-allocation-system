"""Explicit fictional semester, confined to recurrence regression fixtures."""
from datetime import date
from test_room_requests import RoomFixture as BaseRoomFixture
from test_equipment import EquipmentFixture as BaseEquipmentFixture
from web.persistence.models import AcademicPeriod


class SemesterFixture:
    def setUp(self):
        super().setUp()
        with self.database.transaction() as session:
            period=AcademicPeriod(name='Fictional Spring 2030',start_date=date(2030,1,1),end_date=date(2030,6,30),timezone='Europe/Istanbul',is_semester=True)
            session.add(period);session.flush();self.semester=period.id


class RoomFixture(SemesterFixture,BaseRoomFixture):
    pass


class EquipmentFixture(SemesterFixture,BaseEquipmentFixture):
    pass
