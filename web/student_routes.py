"""Student-only navigation; dashboard queries live in a read-only service."""

from flask import Blueprint, abort, g, render_template, request

from .calendar_service import CalendarError
from .student_dashboard_service import StudentDashboardService


def create_student_blueprint(database_provider):
    blueprint = Blueprint("student", __name__, url_prefix="/student")

    @blueprint.errorhandler(CalendarError)
    def invalid_week(error):
        return render_template("appointment_error.html", message=str(error)), 400

    @blueprint.errorhandler(PermissionError)
    def unauthorized(error):
        return render_template("appointment_error.html", message=str(error)), 403

    @blueprint.get("/")
    def home():
        if g.principal.role != "Student":
            abort(403, description="Student access required.")
        home = StudentDashboardService(database_provider()).load(g.principal.user_id, week=request.args.get("week"), month=request.args.get("month"))
        return render_template("student_home.html", home=home)

    return blueprint
