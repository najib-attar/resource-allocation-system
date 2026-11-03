"""Bounded, read-only Instructor Home; existing services retain every mutation."""
from datetime import datetime, timezone

from sqlalchemy import func, select

from .calendar_service import aware, university_zone
from .personal_schedule_service import read_schedule, select_calendar
from .persistence.models import (Appointment, AppointmentProfessor, ProfessorAvailability, User,
    RequestEligibility, RequestDecision, ResourceRequest)
from .professor_service import ProfessorService
from .notification_service import NotificationService


class ProfessorDashboardService:
    LIMIT = 4

    def __init__(self, database):
        self.database = database

    def load(self, actor, now=None, week=None, month=None):
        now = aware(now or datetime.now(timezone.utc))
        zone = university_zone()
        selection = select_calendar(month, week, now)
        academic = ProfessorService(self.database)
        with self.database.transaction(read_only=True) as session:
            academic._instructor(session, actor)
            person = session.get(User, actor)
            query = select(Appointment, AppointmentProfessor.decision, User.name).join(
                AppointmentProfessor, AppointmentProfessor.appointment_id == Appointment.id).join(
                User, User.id == Appointment.organizer_id).where(
                AppointmentProfessor.user_id == actor, Appointment.end_at > now)
            confirmed = query.where(Appointment.status == 'Confirmed')
            pending = query.where(Appointment.status == 'Pending Approval', AppointmentProfessor.decision == 'Pending')

            def count(statement):
                return session.scalar(select(func.count()).select_from(statement.subquery()))

            def meetings(statement):
                return [dict(id=r.id, purpose=r.purpose, start=r.start_at, end=r.end_at,
                    status=r.status, decision=decision, organizer=name) for r, decision, name in session.execute(
                    statement.order_by(Appointment.start_at, Appointment.id).limit(self.LIMIT))]

            hours_query = select(ProfessorAvailability).where(ProfessorAvailability.user_id == actor,
                ProfessorAvailability.valid_until >= now.astimezone(zone).date())
            hours = [dict(id=r.id,day=r.day,start=r.start_minutes,end=r.end_minutes,
                validFrom=r.valid_from,validUntil=r.valid_until,excluded=r.excluded_dates)
                for r in session.scalars(hours_query.order_by(ProfessorAvailability.day,
                    ProfessorAvailability.start_minutes,ProfessorAvailability.id).limit(self.LIMIT))]
            run, changed = academic._publication(session)
            requests = academic._query(actor, run)
            cards = [academic._summary(*row) for row in session.execute(requests.order_by(
                ResourceRequest.submission_order.desc()).limit(self.LIMIT))]
            review_query = requests.where(RequestEligibility.status == 'Pending Eligibility Review')
            results = [academic._summary(*row) for row in session.execute(requests.where(
                RequestDecision.status.is_not(None)).order_by(ResourceRequest.submission_order.desc()).limit(self.LIMIT))]
            home = dict(name=person.name, now=now.astimezone(zone), zone=zone.key,
                pending=meetings(pending), confirmed=meetings(confirmed), hours=hours,
                academic=cards, results=results, inputsChanged=changed,
                counts=dict(pending=count(pending),confirmed=count(confirmed),hours=count(hours_query),
                    review=count(review_query)), schedule=read_schedule(session,actor,selection))
        # NotificationService owns source visibility and recipient scoping.
        home['inbox'] = NotificationService(self.database).inbox(actor,limit=3)
        return home
