"""Published course catalogue and permission-scoped personal and room timetables."""

from flask import Blueprint, Response, abort, g, render_template, request

from .calendar_files import course_calendar
from .calendar_service import CalendarError
from .course_service import CourseService


def create_course_blueprint(database_provider):
    blueprint = Blueprint("courses", __name__, url_prefix="/courses")

    @blueprint.after_request
    def private(response):
        response.headers["Cache-Control"] = "private, no-store"
        return response

    @blueprint.errorhandler(CalendarError)
    @blueprint.errorhandler(PermissionError)
    def unavailable(error):
        status = 403 if isinstance(error, PermissionError) else 400
        return render_template("workspace_error.html", status=status, message=str(error),
                               recovery=("courses.catalog", "course catalogue")), status

    @blueprint.get("/")
    def catalog():
        search = request.args.get("q", "").strip()
        if len(search) > 120:
            abort(400, description="Enter a course name, code or CRN of up to 120 characters.")
        entries = CourseService(database_provider()).catalog(search)
        return render_template("courses/catalog.html", entries=entries, search=search)

    @blueprint.get("/<int:course_id>")
    def detail(course_id):
        sections = CourseService(database_provider()).detail(g.principal.user_id, course_id)
        if not sections:
            abort(404, description="This course is unavailable in the catalogue.")
        return render_template("courses/detail.html", course=sections[0]["course"], sections=sections)

    @blueprint.get("/mine")
    def mine():
        principal = g.principal
        schedule = CourseService(database_provider()).personal(principal.user_id, principal.role, request.args.get("date"))
        return render_template("courses/mine.html", schedule=schedule, teaching=principal.role == "Instructor")

    @blueprint.get("/mine/calendar.ics")
    def download_week():
        principal = g.principal
        schedule = CourseService(database_provider()).personal(principal.user_id, principal.role, request.args.get("date"))
        if not schedule["classes"]:
            abort(404, description="There are no published classes in the selected week.")
        filename = f"campus-space-courses-{schedule['week']['dates'][0].isoformat()}.ics"
        return Response(course_calendar(schedule), content_type="text/calendar; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    @blueprint.get("/rooms")
    def rooms():
        entries = CourseService(database_provider()).rooms(g.principal.user_id)
        return render_template("courses/rooms.html", entries=entries)

    @blueprint.get("/rooms/<int:room_id>")
    def room(room_id):
        schedule = CourseService(database_provider()).room(g.principal.user_id, room_id, request.args.get("date"))
        return render_template("courses/room.html", schedule=schedule)

    return blueprint
