"""Read-only, participant-scoped student home summaries from one database snapshot."""

from datetime import datetime, timezone

from sqlalchemy import and_, func, or_, select

from .calendar_service import aware, university_zone
from .personal_schedule_service import read_schedule, select_calendar
from .persistence.models import Appointment, AppointmentInvitation, AppointmentProfessor, Role, User, StudentRoomRequest, Resource


class StudentDashboardService:
    CARD_LIMIT = 4

    def __init__(self, database):
        self.database = database

    def load(self, actor, now=None, week=None, month=None):
        if type(actor) is not int or actor <= 0:
            raise PermissionError("Student access required.")
        zone = university_zone()
        now = aware(now or datetime.now(timezone.utc))
        selection = select_calendar(month, week, now)

        with self.database.transaction(read_only=True) as session:
            student = session.get(User, actor)
            if (student is None or student.status.casefold() != "active" or
                    session.get(Role, student.primary_role_id).name != "Student"):
                raise PermissionError("Student access required.")
            base = select(Appointment).outerjoin(AppointmentInvitation, and_(
                AppointmentInvitation.appointment_id == Appointment.id, AppointmentInvitation.user_id == actor))
            visible = or_(Appointment.organizer_id == actor, AppointmentInvitation.status == "Invited")
            upcoming = base.where(visible, Appointment.status == "Confirmed", Appointment.end_at > now)
            bookings = base.where(Appointment.organizer_id == actor, Appointment.status == "Confirmed", Appointment.end_at > now)
            pending = base.where(Appointment.organizer_id == actor, Appointment.status == "Pending Approval")
            invitations = base.where(AppointmentInvitation.status == "Invited", Appointment.end_at > now,
                                     Appointment.status.in_(("Pending Approval", "Confirmed")))

            def count(query):
                return session.scalar(select(func.count()).select_from(query.subquery()))

            def rows(query, limit):
                return list(session.scalars(query.order_by(Appointment.start_at, Appointment.id).limit(limit)))

            values = {"bookings": rows(bookings, self.CARD_LIMIT), "pending": rows(pending, self.CARD_LIMIT),
                      "invitations": rows(invitations, self.CARD_LIMIT), "next": rows(upcoming, 1)}
            counts = {"bookings": count(bookings), "pending": count(pending), "invitations": count(invitations)}
            selected_records = {row.id: row for group in values.values() for row in group}
            organizers = {row.organizer_id for row in selected_records.values()}
            names = {row.id: row.name for row in session.scalars(select(User).where(User.id.in_(organizers)))} if organizers else {}
            professors = {}
            if selected_records:
                query = select(AppointmentProfessor.appointment_id, User.name).join(
                    User, User.id == AppointmentProfessor.user_id).where(
                    AppointmentProfessor.appointment_id.in_(selected_records)).order_by(AppointmentProfessor.user_id)
                for appointment_id, name in session.execute(query):
                    professors.setdefault(appointment_id, []).append(name)

            def summary(row):
                return {"id": row.id, "purpose": row.purpose, "status": row.status,
                        "start": row.start_at.astimezone(zone), "end": row.end_at.astimezone(zone),
                        "professors": professors.get(row.id, []), "organizerName": names[row.organizer_id],
                        "organizedByMe": row.organizer_id == actor, "expired": row.end_at <= now,
                        "inProgress": row.start_at <= now < row.end_at}

            schedule = read_schedule(session, actor, selection)
            room_rows = list(session.execute(select(StudentRoomRequest,Resource.name).join(Resource,Resource.id == StudentRoomRequest.resource_id).where(
                StudentRoomRequest.organizer_id == actor,StudentRoomRequest.status.in_(['Pending Faculty Approval','Needs Revision','Confirmed']),
                or_(StudentRoomRequest.status != 'Confirmed',StudentRoomRequest.end_at > now)).order_by(StudentRoomRequest.start_at,StudentRoomRequest.id)))
            room_counts = {'confirmed':sum(row.status == 'Confirmed' for row,_ in room_rows),
                           'pending':sum(row.status != 'Confirmed' for row,_ in room_rows)}
            room_cards = [{'id':row.id,'purpose':row.purpose,'status':row.status,'roomName':name,
                           'start':row.start_at.astimezone(zone),'end':row.end_at.astimezone(zone)} for row,name in room_rows[:self.CARD_LIMIT]]
            return {"profile": {"name": student.name, "studentNo": student.student_no,
                                "program": student.program, "yearLevel": student.year_level},
                    "now": now.astimezone(zone), "zone": zone.key, "weekStart": schedule["weekStart"],
                    "weekEnd": schedule["weekEnd"], "days": schedule["days"], "counts": counts,
                    "calendarUnresolved": schedule["unresolved"], "schedule": schedule, 'roomCounts':room_counts,'roomCards':room_cards,
                    "nextMeeting": summary(values["next"][0]) if values["next"] else None,
                    **{key: [summary(row) for row in values[key]] for key in ("bookings", "pending", "invitations")}}
