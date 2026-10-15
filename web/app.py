from pathlib import Path
import os
import threading
import uuid
import sys
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "web"

from sqlalchemy.exc import SQLAlchemyError

from flask import Flask, g, has_request_context, redirect, render_template, request, url_for

try:
    from .allocation_workflow import execute_allocation
    from .database_result_adapter import DatabaseResultAdapter
    from .persistence.database import Database, DatabaseBusy, DatabaseConfigurationError
    from .persistence.repository import Repository, PersistenceError, SubmissionConflict
    from .backend_executable import BackendExecutableError, resolve_backend_executable
    from .engine_gateway import EngineGateway, EngineIntegrationError
    from .input_validation import parse_time_slots, integer
    from .backend_result_adapter import (
        REQUEST_TYPE_LABELS,
        build_committee_participant_display,
        display_value,
        format_time_data,
        index_by_field,
        safe_int,
    )
except ImportError:
    from allocation_workflow import execute_allocation
    from database_result_adapter import DatabaseResultAdapter
    from persistence.database import Database, DatabaseBusy, DatabaseConfigurationError
    from persistence.repository import Repository, PersistenceError, SubmissionConflict
    from backend_executable import BackendExecutableError, resolve_backend_executable
    from engine_gateway import EngineGateway, EngineIntegrationError
    from input_validation import parse_time_slots, integer
    from backend_result_adapter import (
        REQUEST_TYPE_LABELS,
        build_committee_participant_display,
        display_value,
        format_time_data,
        index_by_field,
        safe_int,
    )


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if not __package__:
    sys.path.insert(0, str(PROJECT_ROOT))

app = Flask(__name__)
from web.presentation import person_name
app.jinja_env.filters["person_name"] = person_name
from datetime import timedelta
app.jinja_env.globals["timedelta"] = timedelta
app.config.update(
    DATABASE_LOCK_TIMEOUT=float(os.environ.get("RESOURCE_ALLOCATION_DB_LOCK_TIMEOUT", "5")),
    BACKEND_TIMEOUT=float(os.environ.get("RESOURCE_ALLOCATION_ENGINE_TIMEOUT", "30")),
)
if any(not 0 < app.config[key] < float("inf") for key in ("DATABASE_LOCK_TIMEOUT", "BACKEND_TIMEOUT")):
    raise ValueError("Database lock and backend timeouts must be finite positive seconds.")

SUPPORTED_STRATEGIES = [
    {"value": "greedy", "label": "Greedy"},
    {"value": "priority", "label": "Priority"},
    {"value": "multi_room_exam_greedy", "label": "Multi-Room Exam Greedy"},
    {"value": "multi_room_exam_best_fit", "label": "Multi-Room Exam Best-Fit"},
    {"value": "shared_room_exam_best_fit", "label": "Shared-Room Exam Best-Fit"},
]

EXAM_TYPES = ["Midterm", "Final", "Quiz", "General"]
FEATURE_OPTIONS = ["None", "Projector", "Whiteboard", "Computers"]
PURPOSE_OPTIONS = [
    "Meeting",
    "Lecture",
    "Lab",
    "Exam",
    "Presentation",
    "Thesis Defense",
    "Project Review",
    "Committee Meeting",
    "General",
    "Other",
]
REQUEST_TYPE_OPTIONS = ["OneTime", "Recurring", "Exam", "CommitteeMeeting"]
COMMITTEE_PARTICIPANT_ROLES = {
    "Instructor",
    "TeachingAssistant",
    "Staff",
    "Administrator",
}
USER_ROLE_OPTIONS = [
    "All",
    "Student",
    "TeachingAssistant",
    "Instructor",
    "Staff",
    "Administrator",
]

FORM_DAY_OPTIONS = [
    {"value": str(day), "label": DAY_NAME}
    for day, DAY_NAME in [
        (1, "Monday"),
        (2, "Tuesday"),
        (3, "Wednesday"),
        (4, "Thursday"),
        (5, "Friday"),
    ]
]
FORM_START_MINUTES = 9 * 60
FORM_END_MINUTES = 17 * 60
FORM_STEP_MINUTES = 30
FORM_TIME_OPTIONS = [
    {
        "value": f"{minutes // 60:02d}:{minutes % 60:02d}",
        "label": f"{minutes // 60:02d}:{minutes % 60:02d}",
    }
    for minutes in range(FORM_START_MINUTES, FORM_END_MINUTES + 1, FORM_STEP_MINUTES)
]
RAW_DATA_FILES = [
    {"filename": "requests.csv", "label": "Raw Requests"},
    {"filename": "allocations.csv", "label": "Raw Allocations"},
    {"filename": "request_results.csv", "label": "Raw Request Results"},
    {"filename": "request_summaries.csv", "label": "Request Summaries"},
    {"filename": "allocation_summaries.csv", "label": "Allocation Summaries"},
    {"filename": "request_participants.csv", "label": "Request Participants"},
    {"filename": "user_busy_slots.csv", "label": "User Busy Slots"},
    {"filename": "users.csv", "label": "Users CSV"},
    {"filename": "spaces.csv", "label": "Spaces CSV"},
    {"filename": "config.txt", "label": "Strategy Config"},
]

_database_configuration_lock = threading.Lock()


def current_results():
    if has_request_context():
        if not hasattr(g, "backend_results"):
            g.backend_results = DatabaseResultAdapter(get_repository(), RAW_DATA_FILES)
        return g.backend_results
    return DatabaseResultAdapter(get_repository(), RAW_DATA_FILES)


def get_repository():
    configuration = (app.config.get("DATABASE_URL", os.environ.get("DATABASE_URL")), app.config["DATABASE_LOCK_TIMEOUT"])
    # This lock protects pool initialization only; PostgreSQL coordinates writes across workers.
    with _database_configuration_lock:
        cached = app.extensions.get("allocation_database")
        if cached is None or cached[0] != configuration:
            database = Database(configuration[0], configuration[1])
            if cached:
                cached[1].dispose()
            app.extensions["allocation_database"] = (configuration, database)
        return Repository(app.extensions["allocation_database"][1])


from web.security import init_security
init_security(app, lambda: get_repository().database)

from web.appointment_routes import create_appointment_blueprint
app.register_blueprint(create_appointment_blueprint(lambda: get_repository().database,
    lambda: EngineGateway(PROJECT_ROOT, app.config["BACKEND_TIMEOUT"], app.logger)))

from web.student_routes import create_student_blueprint
app.register_blueprint(create_student_blueprint(lambda: get_repository().database))

from web.room_request_routes import create_room_blueprint
app.config['ROOM_SELECTION_STRATEGY'] = os.environ.get('RESOURCE_ALLOCATION_ROOM_STRATEGY', 'best_fit')
app.register_blueprint(create_room_blueprint(lambda: get_repository().database,
    lambda: EngineGateway(PROJECT_ROOT, app.config['BACKEND_TIMEOUT'], app.logger),
    lambda: app.config['ROOM_SELECTION_STRATEGY']))

from web.notification_routes import create_notification_blueprint
app.register_blueprint(create_notification_blueprint(lambda: get_repository().database))

@app.before_request
def pin_database_view():
    if request.method in {"GET", "HEAD"} and request.endpoint not in {"static", "login", "logout"} and not (request.endpoint or "").startswith(("appointments.", "student.", "rooms.", "notifications.")):
        current_results()


@app.errorhandler(DatabaseBusy)
def database_busy(error):
    return str(error), 503, {"Retry-After": "2"}


@app.errorhandler(DatabaseConfigurationError)
@app.errorhandler(PersistenceError)
@app.errorhandler(EngineIntegrationError)
def application_error(error):
    app.logger.error("Application operation failed: %s", error)
    return f"Application operation failed: {error}", 503


@app.errorhandler(SQLAlchemyError)
def database_error(error):
    app.logger.error("Database operation failed (%s).", type(error).__name__)
    return "Database operation failed. Check PostgreSQL configuration and migrations; previous results remain active.", 503


@app.errorhandler(SubmissionConflict)
def submission_conflict(error):
    return str(error), 409


def current_strategy():
    return current_results().strategy


def update_strategy(strategy_name):
    get_repository().set_strategy(strategy_name)


def get_table(name):
    return current_results().get_table(name)


def get_page_message():
    status = request.args.get("status", "")
    text = request.args.get("message", "")

    if status in {"success", "error"} and text:
        return {
            "status": status,
            "text": text,
        }

    return None


def build_committee_participant_options(users):
    options = []

    for user in users:
        role = (user.get("role") or "").strip()
        user_id = (user.get("userId") or "").strip()

        if role not in COMMITTEE_PARTICIPANT_ROLES or not user_id:
            continue

        label_parts = [
            user_id,
            display_value(user.get("name")),
            f"({role})",
        ]
        options.append(
            {
                "userId": user_id,
                "name": display_value(user.get("name")),
                "role": role,
                "email": display_value(user.get("email"), ""),
                "label": " - ".join(label_parts[:2]) + f" {label_parts[2]}",
            }
        )

    return options


def get_request_row(request_id):
    request_id = str(request_id)

    for row in get_table("requests")["rows"]:
        if (row.get("requestId") or "").strip() == request_id:
            return row

    return None


def get_request_participant_rows(request_id):
    request_id = str(request_id)
    table = get_table("request_participants")

    return [
        row
        for row in table["rows"]
        if (row.get("requestId") or "").strip() == request_id
    ]


def get_building_options(spaces):
    buildings = {
        (space.get("building") or "").strip()
        for space in spaces
        if (space.get("building") or "").strip()
    }
    return ["None"] + sorted(buildings)


def normalize_optional_constraint(value):
    stripped = value.strip()
    return stripped if stripped else "None"


def strategy_label(strategy_value):
    labels = {
        strategy["value"]: strategy["label"]
        for strategy in SUPPORTED_STRATEGIES
    }
    return labels.get(strategy_value, strategy_value)


def build_user_specific_details(user):
    role = (user.get("role") or "").strip()
    detail_fields = []

    if role == "Student":
        detail_fields = [
            ("Student No", user.get("studentNo")),
            ("Program", user.get("program")),
            ("Year", user.get("yearLevel")),
        ]
    elif role == "TeachingAssistant":
        detail_fields = [
            ("Assistant Type", user.get("assistantType")),
            ("Office", user.get("officeRoom")),
        ]
    elif role == "Instructor":
        detail_fields = [
            ("Title", user.get("title")),
            ("Office", user.get("officeRoom")),
        ]
    elif role == "Staff":
        detail_fields = [
            ("Job Title", user.get("jobTitle")),
        ]
    elif role == "Administrator":
        detail_fields = [
            ("Admin Level", user.get("adminLevel")),
        ]

    details = [
        f"{label}: {value.strip()}"
        for label, value in detail_fields
        if (value or "").strip()
    ]

    return "; ".join(details) if details else "N/A"


def build_user_display_rows(rows):
    return [
        {
            "userId": display_value(row.get("userId")),
            "name": display_value(row.get("name")),
            "role": display_value(row.get("role")),
            "email": display_value(row.get("email")),
            "status": display_value(row.get("status")),
            "primaryUnit": display_value(row.get("primaryUnit")),
            "assignedRoles": display_value(row.get("assignedRoles")),
            "details": build_user_specific_details(row),
        }
        for row in rows
    ]


def parse_positive_int(form_data, field_name, label, errors):
    raw_value = form_data.get(field_name, "").strip()

    try:
        value = int(raw_value)
    except ValueError:
        errors.append(f"{label} must be a number.")
        return None

    if value <= 0:
        errors.append(f"{label} must be greater than zero.")
        return None

    return value


def parse_int_field(form_data, field_name, label, errors):
    raw_value = form_data.get(field_name, "").strip()

    try:
        return int(raw_value)
    except ValueError:
        errors.append(f"{label} must be a number.")
        return None


def parse_clock_time(form_data, time_field, hour_field, label, errors):
    raw_value = form_data.get(time_field, "").strip()
    if not raw_value:
        raw_value = form_data.get(hour_field, "").strip()

    if not raw_value:
        errors.append(f"{label} is required.")
        return None, ""

    if ":" in raw_value:
        parts = raw_value.split(":")
        if len(parts) != 2:
            errors.append(f"{label} must use HH:MM format.")
            return None, raw_value

        try:
            hour = int(parts[0])
            minute = int(parts[1])
        except ValueError:
            errors.append(f"{label} must use numeric HH:MM values.")
            return None, raw_value

        if hour < 0 or hour > 24 or minute < 0 or minute > 59:
            errors.append(f"{label} must be between 00:00 and 24:00.")
            return None, raw_value

        if hour == 24 and minute != 0:
            errors.append(f"{label} cannot be later than 24:00.")
            return None, raw_value

        return hour * 60 + minute, f"{hour:02d}:{minute:02d}"

    try:
        hour = int(raw_value)
    except ValueError:
        errors.append(f"{label} must be an hour or HH:MM value.")
        return None, raw_value

    if hour < 0 or hour > 24:
        errors.append(f"{label} hour must be between 0 and 24.")
        return None, raw_value

    return hour * 60, f"{hour:02d}:00"


def parse_time_fields(form_data, errors):
    day = parse_int_field(form_data, "day", "Day", errors)
    start_minutes, start_time = parse_clock_time(
        form_data, "startTime", "startHour", "Start time", errors
    )
    end_minutes, end_time = parse_clock_time(
        form_data, "endTime", "endHour", "End time", errors
    )

    if day is not None and day not in {1, 2, 3, 4, 5}:
        errors.append("Day must be Monday through Friday.")

    if start_minutes is not None:
        if start_minutes < FORM_START_MINUTES or start_minutes > FORM_END_MINUTES:
            errors.append("Start time must be between 09:00 and 17:00.")
        if start_minutes % FORM_STEP_MINUTES != 0:
            errors.append("Start time must use 30-minute increments.")

    if end_minutes is not None:
        if end_minutes < FORM_START_MINUTES or end_minutes > FORM_END_MINUTES:
            errors.append("End time must be between 09:00 and 17:00.")
        if end_minutes % FORM_STEP_MINUTES != 0:
            errors.append("End time must use 30-minute increments.")

    if start_minutes is not None and end_minutes is not None and start_minutes >= end_minutes:
        errors.append("Start time must be earlier than end time.")

    return day, start_time, end_time


def validate_request_form(form_data, users, spaces):
    errors = []
    user_ids = {(user.get("userId") or "").strip() for user in users}
    space_ids = {(space.get("spaceId") or "").strip() for space in spaces}
    selected_participant_ids = form_data.get("requiredParticipantIds", [])

    request_type = form_data.get("requestType", "").strip()
    user_id = form_data.get("userId", "").strip()
    space_id = form_data.get("spaceId", "").strip()
    participant_count = parse_positive_int(
        form_data, "participantCount", "Participant count", errors
    )
    title = form_data.get("title", "").strip()
    purpose = form_data.get("purpose", "").strip()
    time_data = ""

    if request_type not in REQUEST_TYPE_OPTIONS:
        errors.append("Request type must be OneTime, Recurring, Exam, or CommitteeMeeting.")

    if user_id not in user_ids:
        errors.append("Selected requester does not exist.")

    if space_id not in space_ids:
        errors.append("Selected space does not exist.")

    if not title:
        errors.append("Title is required.")

    if not purpose:
        errors.append("Purpose is required.")

    if request_type in {"OneTime", "Exam", "CommitteeMeeting"}:
        day, start_time, end_time = parse_time_fields(form_data, errors)
        if day is not None and start_time and end_time:
            time_data = f"{day}-{start_time}-{end_time}"
    elif request_type == "Recurring":
        time_data = form_data.get("timeData", "").strip()
        if not time_data:
            errors.append("Recurring time data is required.")

    course_code = ""
    course_name = ""
    exam_type = ""
    can_split = "false"

    if request_type == "Exam":
        course_code = form_data.get("courseCode", "").strip()
        course_name = form_data.get("courseName", "").strip()
        exam_type = form_data.get("examType", "").strip()
        can_split = form_data.get("canSplitAcrossRooms", "").strip()

        if not course_code:
            errors.append("Course code is required for exam requests.")

        if not course_name:
            errors.append("Course name is required for exam requests.")

        if exam_type not in EXAM_TYPES:
            errors.append("Exam type must be Midterm, Final, Quiz, or General.")

        if can_split not in {"true", "false"}:
            errors.append("Can split across rooms must be true or false.")

    participant_rows = []
    if request_type == "CommitteeMeeting":
        if isinstance(selected_participant_ids, str):
            selected_participant_ids = [selected_participant_ids]

        selected_participant_ids = [
            participant_id.strip()
            for participant_id in selected_participant_ids
            if participant_id.strip()
        ]

        if len(selected_participant_ids) != len(set(selected_participant_ids)):
            errors.append("Required participants must not be selected more than once.")

        if not selected_participant_ids:
            errors.append("At least one required committee participant must be selected.")

        for participant_id in selected_participant_ids:
            if participant_id not in user_ids:
                errors.append(f"Required participant {participant_id} does not exist.")
                continue

            participant_role = form_data.get(
                f"participantRole_{participant_id}",
                "",
            ).strip() or "Participant"

            participant_rows.append(
                {
                    "userId": participant_id,
                    "participantRole": participant_role,
                }
            )

        course_code = ""
        course_name = ""
        exam_type = ""
        can_split = "false"

    if errors:
        return None, [], errors

    row = {
        "requestType": request_type,
        "userId": user_id,
        "spaceId": space_id,
        "participantCount": str(participant_count),
        "requiredFeature": normalize_optional_constraint(
            form_data.get("requiredFeature", "")
        ),
        "requiredBuilding": normalize_optional_constraint(
            form_data.get("requiredBuilding", "")
        ),
        "timeData": time_data,
        "title": title,
        "purpose": purpose,
        "courseCode": course_code,
        "courseName": course_name,
        "examType": exam_type,
        "canSplitAcrossRooms": can_split,
    }

    try:
        request_record(row, participant_rows)
    except EngineIntegrationError as error:
        return None, [], [str(error)]

    return row, participant_rows, []


def request_record(row, participants):
    """Translate validated form values into a domain record, without choosing an ID."""
    item = {"type": row["requestType"], "requesterId": integer(row["userId"], "requester", 1),
            "spaceId": integer(row["spaceId"], "space", 1), "participantCount": integer(row["participantCount"], "participants", 1),
            "slots": parse_time_slots(row["timeData"])}
    for key in ("title", "purpose", "requiredFeature", "requiredBuilding"):
        item[key] = "" if row[key] == "None" else row[key]
    if item["type"] == "Exam":
        item["exam"] = {key: row[key] for key in ("courseCode", "courseName", "examType")}
        item["exam"]["canSplitAcrossRooms"] = row["canSplitAcrossRooms"] == "true"
    if item["type"] == "CommitteeMeeting":
        item["participants"] = [{"userId": integer(participant["userId"], "participant", 1),
                                  "role": participant["participantRole"]} for participant in participants]
    return item


def build_allocation_summary():
    return current_results().get_allocation_summary(strategy=current_strategy())


def get_request_summary(request_id):
    return current_results().get_request_summary(
        request_id,
        strategy=current_strategy(),
    )


def build_request_list_context():
    summary_context = build_allocation_summary()
    query = request.args.get("q", "").strip().lower()
    type_filter = request.args.get("type", "All").strip() or "All"
    status_filter = request.args.get("status", "All").strip() or "All"
    highlight_id = request.args.get("highlight", "").strip()

    items = list(summary_context["summaries"])
    items.sort(
        key=lambda item: safe_int(item.get("request_id")) or -1,
        reverse=True,
    )

    if type_filter != "All":
        items = [
            item for item in items
            if item["request_type"] == type_filter
        ]

    if status_filter != "All":
        items = [
            item for item in items
            if item["status"].lower() == status_filter.lower()
        ]

    if query:
        items = [
            item for item in items
            if query in item["request_id"].lower()
            or query in item["request_type"].lower()
            or query in item["title"].lower()
            or query in item["purpose"].lower()
            or query in item["requester_name"].lower()
            or query in item["time_data"].lower()
            or query in item["requested_space_name"].lower()
            or query in item["course_code"].lower()
            or query in item["course_name"].lower()
        ]

    status_options = ["All", "Pending", "Approved", "Rejected"]
    type_options = ["All"] + REQUEST_TYPE_OPTIONS

    return {
        "items": items,
        "query": request.args.get("q", "").strip(),
        "type_filter": type_filter,
        "status_filter": status_filter,
        "type_options": type_options,
        "status_options": status_options,
        "request_type_labels": REQUEST_TYPE_LABELS,
        "highlight_id": highlight_id,
        "requests_available": summary_context["requests_available"],
        "results_available": summary_context["results_available"],
    }


def build_schedule_context():
    return current_results().get_schedule_context(
        schedule_type=request.args.get("type", "user"),
        selected_id=request.args.get("id", ""),
    )


def count_records(name):
    return current_results().count_records(name)


def build_dashboard_context(run_result=None, strategy_message=None):
    requests_table = get_table("requests")
    results_table = get_table("request_results")
    allocations_table = get_table("allocations")
    results_by_request = index_by_field(results_table["rows"], "requestId")

    status_counts = {"Approved": 0, "Rejected": 0, "Pending": 0}
    committee_count = 0
    exam_count = 0

    for request_row in requests_table["rows"]:
        request_id = (request_row.get("requestId") or "").strip()
        request_type = (request_row.get("requestType") or "").strip()
        status = display_value(
            results_by_request.get(request_id, {}).get("status"),
            "Pending",
        )
        if status not in status_counts:
            status_counts[status] = 0
        status_counts[status] += 1

        if request_type == "CommitteeMeeting":
            committee_count += 1
        if request_type == "Exam":
            exam_count += 1

    stats = [
        {"label": "Total Requests", "value": len(requests_table["rows"])},
        {"label": "Approved", "value": status_counts.get("Approved", 0), "tone": "approved"},
        {"label": "Rejected", "value": status_counts.get("Rejected", 0), "tone": "rejected"},
        {"label": "Pending", "value": status_counts.get("Pending", 0), "tone": "pending"},
        {"label": "Allocations", "value": count_records("allocations")},
        {"label": "Committee Meetings", "value": committee_count},
        {"label": "Exam Requests", "value": exam_count},
    ]
    request_context = build_request_list_context()
    recent_requests = request_context["items"][:5]
    strategy = current_strategy()

    return {
        "strategy": strategy,
        "strategy_label": strategy_label(strategy),
        "strategies": SUPPORTED_STRATEGIES,
        "stats": stats,
        "recent_requests": recent_requests,
        "requests_available": requests_table["exists"],
        "results_available": results_table["exists"],
        "allocations_available": allocations_table["exists"],
        "run_result": run_result,
        "strategy_message": strategy_message,
    }


def run_backend_allocation():
    try:
        return execute_json_backend()
    except DatabaseBusy:
        raise
    except SQLAlchemyError as error:
        app.logger.error("Allocation publication failed (%s).", type(error).__name__)
        return {"status": "error", "message": "Database publication failed; previous results remain active.", "stdout": "", "stderr": ""}
    except (PersistenceError, DatabaseConfigurationError, EngineIntegrationError, BackendExecutableError) as error:
        app.logger.error("Allocation was not published: %s", error)
        return {"status": "error", "message": str(error), "stdout": "", "stderr": ""}


def execute_json_backend():
    # Validate before reading persistence too, preserving clear missing/stale-artifact errors.
    resolve_backend_executable(PROJECT_ROOT, os.environ.get("RESOURCE_ALLOCATION_BACKEND"))
    result = execute_allocation(get_repository(), EngineGateway(PROJECT_ROOT, app.config["BACKEND_TIMEOUT"], app.logger), app.logger)
    return {"status": "success", "message": "Allocation backend ran successfully. Results were updated.",
            "stdout": f"JSON run {result['runId']} completed ({result['engineVersion']}).", "stderr": ""}


def render_table_page(template_name, title, name, empty_message):
    table = current_results().format_table_for_display(name, get_table(name))
    return render_template(
        template_name,
        title=title,
        table=table,
        empty_message=empty_message,
        page_message=get_page_message(),
    )


@app.route("/")
def index():
    strategy_message = None
    message_status = request.args.get("strategy_status", "")
    message_text = request.args.get("strategy_message", "")

    if message_status in {"success", "error"} and message_text:
        strategy_message = {
            "status": message_status,
            "text": message_text,
        }

    return render_template(
        "index.html",
        **build_dashboard_context(strategy_message=strategy_message),
    )


@app.post("/run-allocation")
def run_allocation():
    run_result = run_backend_allocation()
    return redirect(
        url_for(
            "allocation_summary",
            run_status=run_result["status"],
            run_message=run_result["message"],
        )
    )


@app.post("/set-strategy")
def set_strategy():
    selected_strategy = request.form.get("strategy", "").strip()
    strategy_labels = {
        strategy["value"]: strategy["label"] for strategy in SUPPORTED_STRATEGIES
    }

    if selected_strategy not in strategy_labels:
        return redirect(
            url_for(
                "index",
                strategy_status="error",
                strategy_message="Invalid strategy selected. Config was not changed.",
            )
        )

    update_strategy(selected_strategy)
    return redirect(
        url_for(
            "index",
            strategy_status="success",
            strategy_message=f"Strategy saved: {strategy_labels[selected_strategy]}",
        )
    )


@app.route("/add-request", methods=["GET", "POST"])
def add_request():
    users_table = get_table("users")
    spaces_table = get_table("spaces")
    users = users_table["rows"]
    spaces = spaces_table["rows"]
    form_data = request.form.to_dict() if request.method == "POST" else {
        "requestType": request.args.get("type", "OneTime"),
        "submissionKey": uuid.uuid4().hex,
    }
    if request.method == "POST":
        form_data["requiredParticipantIds"] = request.form.getlist("requiredParticipantIds")
    errors = []

    if request.method == "POST":
        row, participant_rows, errors = validate_request_form(form_data, users, spaces)
        if not errors:
            request_id = get_repository().save_request(request_record(row, participant_rows),
                                                       submission_key=request.form.get("submissionKey") or None)
            if request.form.get("submitAction") == "save_run":
                run_result = run_backend_allocation()
                return redirect(url_for("request_detail", request_id=request_id,
                                        run_status=run_result["status"], run_message=run_result["message"]))
            return redirect(url_for("request_added", request_id=request_id))

    return render_template(
        "add_request.html",
        users=users,
        spaces=spaces,
        request_types=REQUEST_TYPE_OPTIONS,
        purpose_options=PURPOSE_OPTIONS,
        exam_types=EXAM_TYPES,
        day_options=FORM_DAY_OPTIONS,
        time_options=FORM_TIME_OPTIONS,
        request_type_labels=REQUEST_TYPE_LABELS,
        committee_participants=build_committee_participant_options(users),
        feature_options=FEATURE_OPTIONS,
        building_options=get_building_options(spaces),
        form_data=form_data,
        submission_key=form_data.get("submissionKey") or uuid.uuid4().hex,
        errors=errors,
    )


@app.route("/request-added/<request_id>")
def request_added(request_id):
    row = get_request_row(request_id)
    display_row = dict(row) if row else None
    participant_rows = get_request_participant_rows(request_id)
    users_by_id = index_by_field(get_table("users")["rows"], "userId")
    spaces_by_id = index_by_field(get_table("spaces")["rows"], "spaceId")
    requester = {}
    requested_space = {}

    if display_row and "timeData" in display_row:
        requester = users_by_id.get((display_row.get("userId") or "").strip(), {})
        requested_space = spaces_by_id.get((display_row.get("spaceId") or "").strip(), {})
        display_row["timeData"] = format_time_data(display_row.get("timeData"))

    return render_template(
        "request_added.html",
        request_id=request_id,
        request_row=display_row,
        requester=requester,
        requested_space=requested_space,
        committee_participants=build_committee_participant_display(
            participant_rows,
            users_by_id,
        ),
    )


@app.post("/run-allocation-now/<request_id>")
def run_allocation_now(request_id):
    run_result = run_backend_allocation()

    return redirect(
        url_for(
            "request_detail",
            request_id=request_id,
            run_status=run_result["status"],
            run_message=run_result["message"],
        )
    )


@app.route("/request/<request_id>")
def request_detail(request_id):
    run_message = None
    run_status = request.args.get("run_status", "")
    message_text = request.args.get("run_message", "")

    if run_status in {"success", "error"} and message_text:
        run_message = {
            "status": run_status,
            "text": message_text,
        }

    item, summary_context = get_request_summary(request_id)

    return render_template(
        "request_detail.html",
        item=item,
        request_id=str(request_id),
        run_message=run_message,
        requests_available=summary_context["requests_available"],
        results_available=summary_context["results_available"],
        allocations_available=summary_context["allocations_available"],
    )


@app.route("/add-exam", methods=["GET", "POST"])
def add_exam():
    return redirect(url_for("add_request", type="Exam"))


@app.route("/add-one-time", methods=["GET", "POST"])
def add_one_time():
    return redirect(url_for("add_request", type="OneTime"))


@app.route("/allocation-summary")
def allocation_summary():
    run_message = None
    run_status = request.args.get("run_status", "")
    message_text = request.args.get("run_message", "")

    if run_status in {"success", "error"} and message_text:
        run_message = {
            "status": run_status,
            "text": message_text,
        }

    return render_template(
        "allocation_summary.html",
        **build_allocation_summary(),
        highlight_id=request.args.get("highlight", ""),
        run_message=run_message,
    )


@app.route("/exam-summary")
def exam_summary():
    return redirect(url_for("allocation_summary"))


@app.route("/schedules")
def schedules():
    return render_template("schedules.html", **build_schedule_context())


@app.route("/users")
def users():
    table = get_table("users")
    selected_role = request.args.get("role", "All").strip() or "All"

    if selected_role not in USER_ROLE_OPTIONS:
        selected_role = "All"

    rows = table["rows"]
    if selected_role != "All":
        rows = [
            row for row in rows
            if (row.get("role") or "").strip() == selected_role
        ]

    return render_template(
        "users.html",
        title="Users",
        table=table,
        users=build_user_display_rows(rows),
        role_options=USER_ROLE_OPTIONS,
        selected_role=selected_role,
        empty_message="No users were found.",
        page_message=get_page_message(),
    )


@app.route("/spaces")
def spaces():
    return render_table_page("spaces.html", "Spaces", "spaces", "No spaces were found.")


@app.route("/requests")
def requests():
    return render_template("requests.html", **build_request_list_context())


@app.route("/raw-data")
def raw_data():
    return render_template(
        "raw_data.html",
        **current_results().get_raw_data(request.args.get("file", "requests.csv")),
        page_message=get_page_message(),
    )


@app.route("/allocations")
def allocations():
    return redirect(url_for("raw_data", file="allocations.csv"))


@app.route("/results")
def results():
    return redirect(url_for("raw_data", file="request_results.csv"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=os.environ.get("RESOURCE_ALLOCATION_DEBUG", "0") == "1")
