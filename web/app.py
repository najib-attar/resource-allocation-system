from pathlib import Path
from contextlib import contextmanager
import csv
import os
import subprocess

from flask import Flask, g, has_request_context, redirect, render_template, request, url_for

try:
    from .shared_file_state import SharedFileState, SharedStateBusy, SharedStateError
    from .backend_executable import BackendExecutableError, resolve_backend_executable
    from .engine_gateway import EngineGateway, EngineIntegrationError, execution_snapshot
    from .backend_result_adapter import (
        BackendResultAdapter,
        build_committee_participant_display,
        display_value,
        format_time_data,
        index_by_field,
        safe_int,
    )
except ImportError:
    from shared_file_state import SharedFileState, SharedStateBusy, SharedStateError
    from backend_executable import BackendExecutableError, resolve_backend_executable
    from engine_gateway import EngineGateway, EngineIntegrationError, execution_snapshot
    from backend_result_adapter import (
        BackendResultAdapter,
        build_committee_participant_display,
        display_value,
        format_time_data,
        index_by_field,
        safe_int,
    )


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

app = Flask(__name__)
app.config.update(
    SHARED_FILE_LOCK_TIMEOUT=float(os.environ.get("RESOURCE_ALLOCATION_LOCK_TIMEOUT", "5")),
    BACKEND_TIMEOUT=float(os.environ.get("RESOURCE_ALLOCATION_ENGINE_TIMEOUT", "30")),
)
if any(not 0 < app.config[key] < float("inf") for key in ("SHARED_FILE_LOCK_TIMEOUT", "BACKEND_TIMEOUT")):
    raise ValueError("Shared-file lock and backend timeouts must be finite positive seconds.")

SUPPORTED_STRATEGIES = [
    {"value": "greedy", "label": "Greedy"},
    {"value": "priority", "label": "Priority"},
    {"value": "multi_room_exam_greedy", "label": "Multi-Room Exam Greedy"},
    {"value": "multi_room_exam_best_fit", "label": "Multi-Room Exam Best-Fit"},
    {"value": "shared_room_exam_best_fit", "label": "Shared-Room Exam Best-Fit"},
]

REQUEST_HEADERS = [
    "requestId",
    "requestType",
    "userId",
    "spaceId",
    "participantCount",
    "requiredFeature",
    "requiredBuilding",
    "timeData",
    "title",
    "purpose",
    "courseCode",
    "courseName",
    "examType",
    "canSplitAcrossRooms",
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
REQUEST_TYPE_LABELS = {
    "OneTime": "One-Time",
    "Recurring": "Recurring",
    "Exam": "Exam",
    "CommitteeMeeting": "Committee Meeting",
}
COMMITTEE_PARTICIPANT_ROLES = {
    "Instructor",
    "TeachingAssistant",
    "Staff",
    "Administrator",
}
REQUEST_PARTICIPANT_HEADERS = [
    "requestId",
    "userId",
    "participantRole",
]
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

backend_results = BackendResultAdapter(DATA_DIR, RAW_DATA_FILES)


def current_results():
    return getattr(g, "backend_results", backend_results) if has_request_context() else backend_results


def shared_state():
    return SharedFileState(DATA_DIR, app.config["SHARED_FILE_LOCK_TIMEOUT"])


@contextmanager
def shared_operation():
    if has_request_context() and getattr(g, "shared_state", None) is not None:
        yield g.shared_state
        return
    with shared_state().locked() as state:
        if has_request_context():
            g.shared_state = state
            g.backend_results = backend_results.pin(state)
        try:
            yield state
        finally:
            if has_request_context():
                g.shared_state = None


@app.before_request
def pin_result_generation():
    if request.method in {"GET", "HEAD"} and request.endpoint != "static":
        with shared_state().locked() as state:
            g.backend_results = backend_results.pin(state)


@app.errorhandler(SharedStateBusy)
def shared_data_busy(error):
    return str(error), 503, {"Retry-After": "2"}


@app.errorhandler(SharedStateError)
@app.errorhandler(EngineIntegrationError)
def shared_data_error(error):
    app.logger.error("Shared-file operation failed: %s", error)
    return f"Shared-file operation failed: {error}", 503


def read_config_strategy():
    config = current_results().read_text_file("config.txt")
    if not config["exists"]:
        return "greedy (default / config missing)"
    for line in config["content"].splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        if key.strip() == "allocation_strategy" and value.strip():
            return value.strip()

    return "greedy (default / config missing)"


def write_config_strategy(strategy_name):
    with shared_operation() as state:
        state.write_strategy(strategy_name)


def read_csv_table(filename):
    return current_results().read_csv_table(filename)


def get_page_message():
    status = request.args.get("status", "")
    text = request.args.get("message", "")

    if status in {"success", "error"} and text:
        return {
            "status": status,
            "text": text,
        }

    return None


def get_request_headers():
    requests_path = DATA_DIR / "requests.csv"

    if not requests_path.exists() or requests_path.stat().st_size == 0:
        return REQUEST_HEADERS

    with requests_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.reader(file)
        try:
            headers = next(reader)
        except StopIteration:
            return REQUEST_HEADERS

    return headers or REQUEST_HEADERS


def get_next_request_id():
    table = read_csv_table("requests.csv")
    max_request_id = 0

    for row in table["rows"]:
        try:
            request_id = int((row.get("requestId") or "").strip())
        except ValueError:
            continue

        max_request_id = max(max_request_id, request_id)

    return max_request_id + 1


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

    for row in read_csv_table("requests.csv")["rows"]:
        if (row.get("requestId") or "").strip() == request_id:
            return row

    return None


def get_request_participant_rows(request_id):
    request_id = str(request_id)
    table = read_csv_table("request_participants.csv")

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


def validate_exam_form(form_data, users, spaces):
    errors = []
    user_ids = {(user.get("userId") or "").strip() for user in users}
    space_ids = {(space.get("spaceId") or "").strip() for space in spaces}

    user_id = form_data.get("userId", "").strip()
    space_id = form_data.get("spaceId", "").strip()
    participant_count = parse_positive_int(
        form_data, "participantCount", "Participant count", errors
    )
    day, start_time, end_time = parse_time_fields(form_data, errors)
    title = form_data.get("title", "").strip()
    course_code = form_data.get("courseCode", "").strip()
    course_name = form_data.get("courseName", "").strip()
    exam_type = form_data.get("examType", "").strip()
    can_split = form_data.get("canSplitAcrossRooms", "").strip()

    if user_id not in user_ids:
        errors.append("Selected requester does not exist.")

    if space_id not in space_ids:
        errors.append("Selected reference space does not exist.")

    if not title:
        errors.append("Title is required.")

    if not course_code:
        errors.append("Course code is required.")

    if not course_name:
        errors.append("Course name is required.")

    if exam_type not in EXAM_TYPES:
        errors.append("Exam type must be Midterm, Final, Quiz, or General.")

    if can_split not in {"true", "false"}:
        errors.append("Can split across rooms must be true or false.")

    if errors:
        return None, errors

    row = {
        "requestId": str(get_next_request_id()),
        "requestType": "Exam",
        "userId": user_id,
        "spaceId": space_id,
        "participantCount": str(participant_count),
        "requiredFeature": normalize_optional_constraint(
            form_data.get("requiredFeature", "")
        ),
        "requiredBuilding": normalize_optional_constraint(
            form_data.get("requiredBuilding", "")
        ),
        "timeData": f"{day}-{start_time}-{end_time}",
        "title": title,
        "purpose": "Exam",
        "courseCode": course_code,
        "courseName": course_name,
        "examType": exam_type,
        "canSplitAcrossRooms": can_split,
    }

    return row, []


def validate_one_time_form(form_data, users, spaces):
    errors = []
    user_ids = {(user.get("userId") or "").strip() for user in users}
    space_ids = {(space.get("spaceId") or "").strip() for space in spaces}

    user_id = form_data.get("userId", "").strip()
    space_id = form_data.get("spaceId", "").strip()
    participant_count = parse_positive_int(
        form_data, "participantCount", "Participant count", errors
    )
    day, start_time, end_time = parse_time_fields(form_data, errors)
    title = form_data.get("title", "").strip()
    purpose = form_data.get("purpose", "").strip()

    if user_id not in user_ids:
        errors.append("Selected requester does not exist.")

    if space_id not in space_ids:
        errors.append("Selected space does not exist.")

    if not title:
        errors.append("Title is required.")

    if not purpose:
        errors.append("Purpose is required.")
    elif purpose not in PURPOSE_OPTIONS:
        errors.append("Purpose must be Meeting, Lecture, Lab, General, or Other.")

    if errors:
        return None, errors

    row = {
        "requestId": str(get_next_request_id()),
        "requestType": "OneTime",
        "userId": user_id,
        "spaceId": space_id,
        "participantCount": str(participant_count),
        "requiredFeature": normalize_optional_constraint(
            form_data.get("requiredFeature", "")
        ),
        "requiredBuilding": normalize_optional_constraint(
            form_data.get("requiredBuilding", "")
        ),
        "timeData": f"{day}-{start_time}-{end_time}",
        "title": title,
        "purpose": purpose,
        "courseCode": "",
        "courseName": "",
        "examType": "",
        "canSplitAcrossRooms": "false",
    }

    return row, []


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
        "requestId": str(get_next_request_id()),
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

    for participant_row in participant_rows:
        participant_row["requestId"] = row["requestId"]

    return row, participant_rows, []


def build_allocation_summary():
    return current_results().get_allocation_summary(strategy=read_config_strategy())


def get_request_summary(request_id):
    return current_results().get_request_summary(
        request_id,
        strategy=read_config_strategy(),
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


def count_optional_file(filename):
    return current_results().count_optional_file(filename)


def truncate_output(text, limit=3000):
    if not text:
        return ""

    if len(text) <= limit:
        return text

    return text[:limit] + "\n... output truncated for dashboard display ..."


def build_dashboard_context(run_result=None, strategy_message=None):
    requests_table = read_csv_table("requests.csv")
    results_table = read_csv_table("request_results.csv")
    allocations_table = read_csv_table("allocations.csv")
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
        {"label": "Allocations", "value": count_optional_file("allocations.csv")},
        {"label": "Committee Meetings", "value": committee_count},
        {"label": "Exam Requests", "value": exam_count},
    ]
    request_context = build_request_list_context()
    recent_requests = request_context["items"][:5]
    strategy = read_config_strategy()

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
        with shared_operation() as state:
            return execute_json_backend(state)
    except SharedStateBusy:
        raise
    except (SharedStateError, OSError, EngineIntegrationError, BackendExecutableError) as error:
        app.logger.error("Allocation was not published: %s", error)
        return {"status": "error", "message": str(error), "stdout": "", "stderr": ""}


def execute_json_backend(state):
    # Validate before reading persistence too, preserving clear missing/stale-artifact errors.
    resolve_backend_executable(PROJECT_ROOT, os.environ.get("RESOURCE_ALLOCATION_BACKEND"))
    strategy = read_config_strategy()
    if strategy == "greedy (default / config missing)":
        strategy = "greedy"
    snapshot = execution_snapshot(backend_results.pin(state), strategy)
    result, metadata = EngineGateway(PROJECT_ROOT, app.config["BACKEND_TIMEOUT"], app.logger).execute(snapshot)
    state.publish_engine_result(snapshot, result, metadata)
    return {"status": "success", "message": "Allocation backend ran successfully. Results were updated.",
            "stdout": f"JSON run {result['runId']} completed ({result['engineVersion']}).", "stderr": ""}


def render_csv_page(template_name, title, filename, empty_message):
    table = current_results().format_table_for_display(filename, read_csv_table(filename))
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

    write_config_strategy(selected_strategy)
    return redirect(
        url_for(
            "index",
            strategy_status="success",
            strategy_message=f"Strategy saved: {strategy_labels[selected_strategy]}",
        )
    )


@app.route("/add-request", methods=["GET", "POST"])
def add_request():
    users_table = read_csv_table("users.csv")
    spaces_table = read_csv_table("spaces.csv")
    users = users_table["rows"]
    spaces = spaces_table["rows"]
    form_data = request.form.to_dict() if request.method == "POST" else {
        "requestType": request.args.get("type", "OneTime"),
    }
    if request.method == "POST":
        form_data["requiredParticipantIds"] = request.form.getlist("requiredParticipantIds")
    errors = []

    if request.method == "POST":
        with shared_operation() as state:
            users = read_csv_table("users.csv")["rows"]
            spaces = read_csv_table("spaces.csv")["rows"]
            row, participant_rows, errors = validate_request_form(form_data, users, spaces)

            if not errors:
                state.save_request(row, participant_rows, get_request_headers(), REQUEST_PARTICIPANT_HEADERS)
                if request.form.get("submitAction") == "save_run":
                    run_result = run_backend_allocation()
                    return redirect(
                        url_for(
                            "request_detail",
                            request_id=row["requestId"],
                            run_status=run_result["status"],
                            run_message=run_result["message"],
                        )
                    )
                return redirect(url_for("request_added", request_id=row["requestId"]))

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
        errors=errors,
    )


@app.route("/request-added/<request_id>")
def request_added(request_id):
    row = get_request_row(request_id)
    display_row = dict(row) if row else None
    participant_rows = get_request_participant_rows(request_id)
    users_by_id = index_by_field(read_csv_table("users.csv")["rows"], "userId")
    spaces_by_id = index_by_field(read_csv_table("spaces.csv")["rows"], "spaceId")
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
    table = read_csv_table("users.csv")
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
    return render_csv_page("spaces.html", "Spaces", "spaces.csv", "No spaces were found.")


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
    app.run(host="127.0.0.1", port=5000, debug=True)
