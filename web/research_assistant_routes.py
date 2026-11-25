"""Authenticated Research Assistant workspace and private task forms."""

from datetime import datetime
from uuid import uuid4

from flask import Blueprint, g, redirect, render_template, request, url_for

from .calendar_service import university_zone
from .research_assistant_service import ResearchAssistantService, ResearchTaskError, task_selection


def create_research_assistant_blueprint(database_provider):
    blueprint = Blueprint("research_assistant", __name__, url_prefix="/research-assistant")

    def service():
        return ResearchAssistantService(database_provider())

    def selection(values):
        try:
            page = int(values.get("page", "1"))
        except ValueError as error:
            raise ResearchTaskError("Choose a valid task page.") from error
        return task_selection(values.get("state", "open"), page)

    def revision():
        try:
            return int(request.form.get("revision", ""))
        except ValueError as error:
            raise ResearchTaskError("Open the planner and try again with a current task revision.") from error

    def render_board(state, page, **context):
        board = service().tasks(g.principal.user_id, state=state, page=page)
        return render_template("research_assistant_tasks.html", board=board,
            today=datetime.now(university_zone()).date(), submission_key=uuid4(), **context)

    def form_values():
        return {name: request.form.get(name, "") for name in ("title", "due_date")}

    @blueprint.after_request
    def private(response):
        response.headers["Cache-Control"] = "private, no-store"
        return response

    @blueprint.errorhandler(ResearchTaskError)
    @blueprint.errorhandler(PermissionError)
    def failed(error):
        status = error.status if isinstance(error, ResearchTaskError) else 403
        return render_template("workspace_error.html", message=str(error), status=status,
                               recovery=("research_assistant.home", "Research Assistant Home")), status

    @blueprint.get("/")
    def home():
        return render_template("research_assistant_home.html", home=service().home(g.principal.user_id))

    @blueprint.get("/tasks")
    def tasks():
        return render_board(*selection(request.args))

    @blueprint.post("/tasks")
    def create():
        state, page = selection(request.form)
        values = form_values()
        try:
            service().create(g.principal.user_id, request.form.get("submission_key", ""), **values)
        except ResearchTaskError as error:
            return render_board(state, page, message=str(error), form_values=values), error.status
        return redirect(url_for("research_assistant.tasks"), code=303)

    @blueprint.post("/tasks/<uuid:task_id>/edit")
    def edit(task_id):
        state, page = selection(request.form)
        values = form_values()
        try:
            service().edit(g.principal.user_id, task_id, revision(), **values)
        except ResearchTaskError as error:
            if error.status == 404:
                raise
            return render_board(state, page, message=str(error), edit_task_id=task_id, edit_values=values), error.status
        return redirect(url_for("research_assistant.tasks", state=state, page=page), code=303)

    @blueprint.post("/tasks/<uuid:task_id>/state")
    def set_state(task_id):
        state, page = selection(request.form)
        try:
            service().set_state(g.principal.user_id, task_id, revision(), request.form.get("target"))
        except ResearchTaskError as error:
            if error.status == 404:
                raise
            return render_board(state, page, message=str(error)), error.status
        return redirect(url_for("research_assistant.tasks", state=state, page=page), code=303)

    return blueprint
