"""Thin authenticated appointment/form routes; application logic lives in services."""

from datetime import date, datetime, time, timedelta, timezone

from flask import Blueprint, abort, g, jsonify, redirect, render_template, request, url_for
from sqlalchemy import select

from .appointment_service import AppointmentError, AppointmentService, REASONS
from .calendar_service import CalendarError, local_instant, university_zone
from .personal_schedule_service import PersonalScheduleService
from .persistence.models import LegacyCalendarBinding, AcademicPeriod, BusySlot, ResourceRequest


def create_appointment_blueprint(database_provider, gateway_provider):
    blueprint = Blueprint("appointments", __name__, url_prefix="/appointments")

    def service():
        return AppointmentService(database_provider(), gateway_provider())

    def student():
        if g.principal.role != "Student":
            abort(403, description="Only students may organize appointments.")
        return g.principal.user_id

    def professor():
        if g.principal.role != "Instructor":
            abort(403, description="Only professors may publish appointment hours.")
        return g.principal.user_id

    def integer(value):
        try:
            result = int(value)
            if result <= 0 or result > 2147483647:
                raise ValueError()
            return result
        except (ValueError, TypeError) as error:
            raise AppointmentError("Enter a valid positive identifier/duration.") from error

    def ids(key):
        return [integer(value) for value in request.form.getlist(key)]

    def revision():
        return integer(request.form.get("revision"))

    def day(value):
        try:
            return date.fromisoformat(value)
        except (ValueError, TypeError) as error:
            raise AppointmentError("Enter a valid calendar date.") from error

    def minutes(value):
        try:
            clock = time.fromisoformat(value)
            if clock.second or clock.microsecond or clock.tzinfo:
                raise ValueError()
            return clock.hour * 60 + clock.minute
        except (ValueError, TypeError) as error:
            raise AppointmentError("Enter a valid hour and minute.") from error

    def excluded():
        return [day(item.strip()).isoformat() for item in request.form.get("excludedDates", "").split(",") if item.strip()]

    @blueprint.app_template_filter("university_time")
    def university_time(value):
        return value.astimezone(university_zone()).strftime("%Y-%m-%d %H:%M")

    @blueprint.errorhandler(PermissionError)
    def unauthorized(error):
        return render_template("appointment_error.html", message=str(error)), 403

    @blueprint.errorhandler(CalendarError)
    def invalid(error):
        if request.endpoint == "appointments.times":
            return jsonify(error=str(error)), 409
        return render_template("appointment_error.html", message=str(error)), 409

    @blueprint.get("/")
    def index():
        return render_template("appointments.html", items=service().list_for(g.principal.user_id), zone=university_zone().key)

    @blueprint.route("/new", methods=["GET", "POST"])
    def new():
        actor = student()
        if request.method == "POST":
            proposed = local_instant(request.form.get("start"))
            if "appointmentDate" in request.form and proposed.astimezone(university_zone()).date() != day(request.form.get("appointmentDate")):
                raise AppointmentError("Select a time on the chosen appointment date.")
            appointment_id = service().submit(actor, ids("professorIds"), ids("invitedIds"), request.form.get("purpose", ""),
                integer(request.form.get("duration")), proposed, integer(request.form.get("facultyId")))
            return redirect(url_for("appointments.detail", appointment_id=appointment_id))
        directory = service().directory()
        return render_template("appointment_new.html", directory=directory, zone=university_zone().key,
                               today=datetime.now(university_zone()).date().isoformat())

    @blueprint.post("/times")
    def times():
        actor = student()
        single_date = "appointmentDate" in request.form
        first = day(request.form.get("appointmentDate") if single_date else request.form.get("fromDate"))
        last = first if single_date else day(request.form.get("untilDate"))
        if not date(1970, 1, 1) <= first <= last < date(2100, 1, 1):
            raise AppointmentError("Search dates must be between 1970 and 2099, with the end on or after the start.")
        zone = university_zone()
        start = local_instant(datetime.combine(first, time()), zone)
        end = local_instant(datetime.combine(last + timedelta(days=1), time()), zone)
        preferred = local_instant(request.form["preferredStart"]) if request.form.get("preferredStart") else None
        result, _ = service().evaluate(actor, ids("professorIds"), ids("invitedIds"), integer(request.form.get("duration")),
                    max(start, datetime.now(timezone.utc).replace(second=0, microsecond=0) + timedelta(minutes=1)), end,
                    preferred=preferred, faculty=integer(request.form.get("facultyId")), limit=100 if single_date else None)
        values = [{**item, "localStart": datetime.fromtimestamp(item["start"], timezone.utc).astimezone(zone).strftime("%Y-%m-%dT%H:%M"),
                   "label": f"{datetime.fromtimestamp(item['start'], timezone.utc).astimezone(zone):%Y-%m-%d %H:%M} - {datetime.fromtimestamp(item['end'], timezone.utc).astimezone(zone):%H:%M}"}
                  for item in result["recommendations"]]
        return jsonify(items=values, reason=REASONS.get(result["reasonCode"], "Feasible times ranked by available invitees, preferred-time distance, then chronology."))

    @blueprint.get("/<int:appointment_id>")
    def detail(appointment_id):
        return render_template("appointment_detail.html", item=service().detail(appointment_id, g.principal.user_id), zone=university_zone().key)

    @blueprint.post("/<int:appointment_id>/decision")
    def decision(appointment_id):
        professor()
        action = request.form.get("decision")
        if action not in {"approve", "decline"}:
            raise AppointmentError("Select approve or decline.")
        service().decide(appointment_id, g.principal.user_id, revision(), action == "approve")
        return redirect(url_for("appointments.detail", appointment_id=appointment_id))

    @blueprint.post("/<int:appointment_id>/cancel")
    def cancel(appointment_id):
        service().cancel(appointment_id, g.principal.user_id, revision())
        return redirect(url_for("appointments.detail", appointment_id=appointment_id))

    @blueprint.post("/<int:appointment_id>/reschedule")
    def reschedule(appointment_id):
        student()
        service().reschedule(appointment_id, g.principal.user_id, revision(), local_instant(request.form.get("start")))
        return redirect(url_for("appointments.detail", appointment_id=appointment_id))

    @blueprint.post("/<int:appointment_id>/decline-invitation")
    def decline(appointment_id):
        student()
        service().decline_invitation(appointment_id, g.principal.user_id)
        return redirect(url_for("appointments.detail", appointment_id=appointment_id))

    @blueprint.route("/availability", methods=["GET", "POST"])
    def availability():
        actor = professor()
        if request.method == "POST":
            action = request.form.get("action")
            if action == "hours":
                service().publish_hours(actor, integer(request.form.get("day")), minutes(request.form.get("startTime")),
                    minutes(request.form.get("endTime")), day(request.form.get("validFrom")), day(request.form.get("validUntil")), excluded())
            elif action == "remove-hours":
                service().remove_hours(actor, integer(request.form.get("id")))
            else:
                raise AppointmentError("Unknown office-hour action.")
            return redirect(url_for("appointments.availability"))
        return render_template("appointment_availability.html", values=service().availability_for(actor), zone=university_zone().key)

    @blueprint.route("/calendar", methods=["GET", "POST"])
    def calendar():
        actor = g.principal.user_id
        if request.method == "POST":
            action = request.form.get("action")
            if action == "block":
                service().block(actor, local_instant(request.form.get("start")), local_instant(request.form.get("end")), request.form.get("reason", ""))
            elif action == "unblock":
                service().unblock(actor, integer(request.form.get("id")))
            else:
                raise AppointmentError("Unknown calendar action.")
            return redirect(url_for("appointments.calendar"))
        schedule = PersonalScheduleService(database_provider()).load(actor, month=request.args.get("month"),
            week=request.args.get("week", request.args.get("from")))
        return render_template("appointment_calendar.html", schedule=schedule, zone=schedule["zone"])

    @blueprint.route("/calendar-setup", methods=["GET", "POST"])
    def bindings():
        if not g.principal.administrator:
            abort(403)
        if request.method == "POST":
            service().bind_legacy(request.form.get("periodName", ""), day(request.form.get("fromDate")), day(request.form.get("untilDate")),
                integer(request.form["busyId"]) if request.form.get("busyId") else None,
                integer(request.form["requestId"]) if request.form.get("requestId") else None,
                day(request.form["weekStart"]) if request.form.get("weekStart") else None, excluded())
            return redirect(url_for("appointments.bindings"))
        with database_provider().transaction(read_only=True) as session:
            periods = {row.id: row for row in session.scalars(select(AcademicPeriod))}
            values = [{"busyId": row.busy_slot_id, "requestId": row.request_id, "period": periods[row.period_id].name,
                       "fromDate": periods[row.period_id].start_date, "untilDate": periods[row.period_id].end_date,
                       "weekStart": row.week_start, "excluded": row.excluded_dates}
                      for row in session.scalars(select(LegacyCalendarBinding).order_by(LegacyCalendarBinding.id))]
            busy = [{"id": row.id, "userId": row.user_id, "day": row.day} for row in session.scalars(select(BusySlot))]
            requests = [{"id": row.id, "title": row.title} for row in session.scalars(select(ResourceRequest))]
        return render_template("appointment_bindings.html", values=values, busy=busy, requests=requests, zone=university_zone().key)

    return blueprint
