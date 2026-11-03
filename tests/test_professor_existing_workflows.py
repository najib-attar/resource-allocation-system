"""Additional HTTP ownership/invalid-state coverage for existing professor controls."""
from datetime import timedelta
from sqlalchemy import select

from auth_fixtures import authorized_client
from test_appointments import START
from test_professor_services import ProfessorFixture
from web import app as web_app
from web.account_service import AccountService
from web.persistence.models import CalendarBlock, ProfessorAvailability, Role, User


class ProfessorExistingContractTests(ProfessorFixture):
    def hours_form(self, **changes):
        value = dict(action='hours', day='2', startTime='09:00', endTime='12:00',
                     validFrom='2030-01-01',validUntil='2030-01-31',excludedDates='2030-01-15')
        value.update(changes)
        return value

    def test_hour_publication_role_guard_and_session_ownership_for_all_five_roles(self):
        with self.database.transaction() as session:
            role = session.scalar(select(Role.id).where(Role.name=='TeachingAssistant'))
            session.add(User(id=9,source_order=9,name='Fictional hours-review TA',primary_role_id=role))
        AccountService(self.database).provision(9,'hours-review-ta','Fictional-isolated-password')
        before = self.service.availability_for(2)['hours']
        for actor in (1,7,9,6):
            client = authorized_client(web_app.app,actor)
            self.assertEqual(client.get('/appointments/availability').status_code,403)
            self.assertEqual(client.post('/appointments/availability',data=self.hours_form()).status_code,403)
        self.assertEqual(self.service.availability_for(2)['hours'],before)
        response = self.client.post('/appointments/availability',data=self.hours_form(userId='3',actor='3'))
        self.assertEqual(response.status_code,302)
        after = self.service.availability_for(2)['hours']
        self.assertEqual(len(after),len(before)+1)
        self.assertEqual(after[-1]['excluded_dates'],['2030-01-15'])
        self.assertEqual(len(self.service.availability_for(3)['hours']),1)
        self.assertEqual(self.client.client.post('/appointments/availability',data=self.hours_form()).status_code,400)

    def test_invalid_hours_boundaries_and_exclusions_never_persist(self):
        before = self.service.availability_for(2)['hours']
        cases = [dict(day='8'),dict(startTime='12:00',endTime='09:00'),dict(validUntil='2029-12-31'),
                 dict(validFrom='1969-01-01'),dict(validUntil='2033-01-01'),dict(excludedDates='invalid-date'),
                 dict(startTime='09:00:01'),dict(startTime='09:00+01:00')]
        for changes in cases:
            with self.subTest(changes=changes):
                self.assertEqual(self.client.post('/appointments/availability',data=self.hours_form(**changes)).status_code,409)
                self.assertEqual(self.service.availability_for(2)['hours'],before)

    def test_cross_user_hours_and_block_deletions_are_forbidden_and_private(self):
        self.service.block(3,START+timedelta(days=2),START+timedelta(days=2,hours=1),'Private professor peer block')
        with self.database.transaction(read_only=True) as session:
            hours_id = session.scalar(select(ProfessorAvailability.id).where(ProfessorAvailability.user_id==3))
            block_id = session.scalar(select(CalendarBlock.id).where(CalendarBlock.user_id==3))
        self.assertEqual(self.client.post('/appointments/availability',data=dict(action='remove-hours',id=hours_id)).status_code,403)
        self.assertEqual(self.client.post('/appointments/calendar',data=dict(action='unblock',id=block_id)).status_code,403)
        self.assertEqual(len(self.service.availability_for(3)['blocks']),1)
        self.assertEqual(len(self.service.availability_for(3)['hours']),1)
        page = self.client.get('/appointments/calendar?month=2030-01&week=2030-01-07')
        self.assertEqual(page.status_code,200)
        self.assertNotIn(b'Private professor peer block',page.data)

