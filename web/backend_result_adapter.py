from pathlib import Path
import csv
import re

try:
    from .shared_file_state import INPUT_FILES, OUTPUT_HEADERS, SharedFileState
    from .engine_result_projection import result_tables, suggestion_display
    from .engine_gateway import validate_result
except ImportError:
    from shared_file_state import INPUT_FILES, OUTPUT_HEADERS, SharedFileState
    from engine_result_projection import result_tables, suggestion_display
    from engine_gateway import validate_result


REQUEST_TYPE_LABELS = {
    "OneTime": "One-Time",
    "Recurring": "Recurring",
    "Exam": "Exam",
    "CommitteeMeeting": "Committee Meeting",
}

SCHEDULE_USER_ROLES = {
    "Student",
    "Instructor",
    "TeachingAssistant",
    "Staff",
    "Administrator",
}

SCHEDULE_DAYS = [1, 2, 3, 4, 5]
SCHEDULE_BLOCKS = [
    (hour * 60, (hour + 1) * 60)
    for hour in range(9, 17)
]

DAY_NAMES = {
    1: "Monday",
    2: "Tuesday",
    3: "Wednesday",
    4: "Thursday",
    5: "Friday",
    6: "Saturday",
    7: "Sunday",
}


class BackendResultAdapter:
    """Adapts structured engine results, with legacy CSV display compatibility."""

    def __init__(self, data_dir, raw_data_files):
        self.data_dir = Path(data_dir)
        self.raw_data_files = list(raw_data_files)
        self._tables = None
        self._texts = None
        self.generation_dir = None
        self.engine_result = None

    def pin(self, state=None):
        """Read live inputs and resolve the published generation once, under the lock."""
        if state is None:
            with SharedFileState(self.data_dir).locked() as state:
                return self.pin(state)
        pinned = BackendResultAdapter(self.data_dir, self.raw_data_files)
        document = state.read_engine_result()
        pinned.generation_dir = state.current_data_dir() if document is None else None
        result_reader = BackendResultAdapter(pinned.generation_dir or self.data_dir, self.raw_data_files)
        pinned._tables = {
            name: (result_reader if name in OUTPUT_HEADERS else self).read_csv_table(name)
            for name in (*INPUT_FILES, *(OUTPUT_HEADERS if document is None else ())) if name.endswith(".csv")
        }
        pinned._texts = {"config.txt": self.read_text_file("config.txt")}
        if document is not None:
            validate_result(document["result"], document["snapshot"])
            pinned.engine_result = document["result"]
            pinned._tables.update(result_tables(document["snapshot"], document["result"]))
        return pinned

    def list_raw_data_files(self):
        return list(self.raw_data_files)

    def read_csv_table(self, filename):
        if self._tables is not None:
            return self._tables[filename]
        csv_path = self.data_dir / filename

        if not csv_path.exists():
            return {
                "exists": False,
                "headers": [],
                "rows": [],
                "message": f"{filename} is not available yet.",
            }

        with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            headers = reader.fieldnames or []
            rows = list(reader)

        return {
            "exists": True,
            "headers": headers,
            "rows": rows,
            "message": "",
        }

    def read_text_file(self, filename):
        if self._texts is not None:
            return self._texts[filename]
        file_path = self.data_dir / filename
        if not file_path.exists():
            return {
                "exists": False,
                "content": "",
                "message": f"{filename} is not available yet.",
            }

        return {
            "exists": True,
            "content": file_path.read_text(encoding="utf-8-sig"),
            "message": "",
        }

    def count_optional_file(self, filename):
        table = self.read_csv_table(filename)
        if not table["exists"]:
            return "Not available"
        return len(table["rows"])

    def get_raw_data(self, selected_file):
        selected_file = (selected_file or "requests.csv").strip()
        valid_files = {item["filename"] for item in self.raw_data_files}
        if selected_file not in valid_files:
            selected_file = "requests.csv"

        selected_label = next(
            item["label"] for item in self.raw_data_files
            if item["filename"] == selected_file
        )

        if selected_file == "config.txt":
            text_file = self.read_text_file(selected_file)
            table = {
                "exists": text_file["exists"],
                "headers": [],
                "rows": [],
                "message": text_file["message"],
            }
            raw_text = text_file["content"]
        else:
            table = self.format_table_for_display(
                selected_file,
                self.read_csv_table(selected_file),
            )
            raw_text = ""

        return {
            "files": self.list_raw_data_files(),
            "selected_file": selected_file,
            "selected_label": selected_label,
            "table": table,
            "raw_text": raw_text,
        }

    def format_table_for_display(self, filename, table):
        display_table = {
            "exists": table["exists"],
            "headers": list(table["headers"]),
            "rows": [],
            "message": table["message"],
        }

        for row in table["rows"]:
            display_row = dict(row)

            if filename == "requests.csv" and "timeData" in display_row:
                display_row["timeData"] = format_time_data(display_row.get("timeData"))

            if filename == "request_results.csv":
                if "timeData" in display_row:
                    display_row["timeData"] = format_time_data(display_row.get("timeData"))
                if "timeInfo" in display_row:
                    display_row["timeInfo"] = format_time_data(display_row.get("timeInfo"))

            if filename == "allocations.csv":
                if "day" in display_row:
                    display_row["day"] = format_day_name(display_row.get("day"))
                if "startHour" in display_row:
                    display_row["startHour"] = format_time_part(display_row.get("startHour"))
                if "endHour" in display_row:
                    display_row["endHour"] = format_time_part(display_row.get("endHour"))

            display_table["rows"].append(display_row)

        return display_table

    def get_allocation_summary(self, strategy=""):
        requests_table = self.read_csv_table("requests.csv")
        results_table = self.read_csv_table("request_results.csv")
        allocations_table = self.read_csv_table("allocations.csv")
        spaces_table = self.read_csv_table("spaces.csv")
        users_table = self.read_csv_table("users.csv")
        participants_table = self.read_csv_table("request_participants.csv")

        results_by_request = index_by_field(results_table["rows"], "requestId")
        allocations_by_request = group_by_field(allocations_table["rows"], "requestId")
        spaces_by_id = index_by_field(spaces_table["rows"], "spaceId")
        users_by_id = index_by_field(users_table["rows"], "userId")
        participants_by_request = group_by_field(participants_table["rows"], "requestId")

        summaries = []

        for request_row in requests_table["rows"]:
            request_id = (request_row.get("requestId") or "").strip()
            result_row = results_by_request.get(request_id, {})
            user = users_by_id.get((request_row.get("userId") or "").strip(), {})
            requested_space_id = (request_row.get("spaceId") or "").strip()
            requested_space = spaces_by_id.get(requested_space_id, {})
            participant_count = safe_int(request_row.get("participantCount"))
            request_type = display_value(
                result_row.get("requestType") or request_row.get("requestType"),
                "Unknown",
            )
            committee_participants = build_committee_participant_display(
                participants_by_request.get(request_id, []),
                users_by_id,
            )
            status = display_value(result_row.get("status"), "Pending")

            assigned_rooms = []
            if status.lower() != "rejected":
                assigned_rooms = [
                    build_assigned_room(allocation, spaces_by_id)
                    for allocation in allocations_by_request.get(request_id, [])
                ]

            total_assigned = sum(room["assigned"] for room in assigned_rooms)
            capacities = [room["capacity"] for room in assigned_rooms]
            total_capacity = None

            if assigned_rooms and all(capacity is not None for capacity in capacities):
                total_capacity = sum(capacities)

            waste = None
            if total_capacity is not None and participant_count is not None:
                waste = total_capacity - participant_count

            if request_type == "Recurring" and participant_count is not None and assigned_rooms:
                assignment_display = f"{participant_count} per occurrence ({total_assigned} total)"
            else:
                assignment_display = (
                    f"{total_assigned} / {participant_count}"
                    if participant_count is not None
                    else str(total_assigned)
                )

            summaries.append(
                {
                    "request_id": request_id,
                    "request_type": request_type,
                    "request_type_label": request_type_label(request_type),
                    "is_exam": request_type == "Exam" or is_exam_request(request_row),
                    "is_committee": request_type == "CommitteeMeeting" or is_committee_request(request_row),
                    "title": display_value(
                        request_row.get("title") or result_row.get("title"),
                        "Untitled Request",
                    ),
                    "purpose": display_value(
                        request_row.get("purpose") or result_row.get("purpose")
                    ),
                    "course_code": display_value(
                        request_row.get("courseCode") or result_row.get("courseCode")
                    ),
                    "course_name": display_value(
                        request_row.get("courseName") or result_row.get("courseName")
                    ),
                    "exam_type": display_value(
                        request_row.get("examType") or result_row.get("examType")
                    ),
                    "committee_participants": committee_participants,
                    "participant_count": participant_count,
                    "participant_display": (
                        participant_count if participant_count is not None else "N/A"
                    ),
                    "can_split": display_value(
                        request_row.get("canSplitAcrossRooms")
                        or result_row.get("canSplitAcrossRooms"),
                        "false",
                    ),
                    "time_data": format_time_data(
                        request_row.get("timeData") or result_row.get("timeInfo")
                    ),
                    "raw_time_data": display_value(request_row.get("timeData"), ""),
                    "user_id": display_value(request_row.get("userId")),
                    "requester_name": display_value(user.get("name")),
                    "requester_role": display_value(user.get("role")),
                    "requested_space_id": display_value(requested_space_id),
                    "requested_space_name": display_value(requested_space.get("name")),
                    "requested_space_type": display_value(requested_space.get("type")),
                    "requested_space_building": display_value(requested_space.get("building")),
                    "required_feature": display_value(request_row.get("requiredFeature"), "None"),
                    "required_building": display_value(request_row.get("requiredBuilding"), "None"),
                    "status": status,
                    "status_class": status.lower(),
                    "rejection_reason": display_value(
                        result_row.get("rejectionReason"),
                        "",
                    ),
                    "meeting_suggestions": (
                        next((suggestion_display(group) for group in self.engine_result["suggestions"]
                              if str(group["requestId"]) == request_id), None)
                        if self.engine_result is not None else extract_meeting_suggestions(result_row.get("lifecycleHistory"))
                    ),
                    "assigned_rooms": assigned_rooms,
                    "total_assigned": total_assigned,
                    "assignment_display": assignment_display,
                    "total_capacity": (
                        total_capacity if total_capacity is not None else "N/A"
                    ),
                    "waste": waste if waste is not None else "N/A",
                }
            )

        return {
            "summaries": summaries,
            "strategy": strategy,
            "requests_available": requests_table["exists"],
            "results_available": results_table["exists"],
            "allocations_available": allocations_table["exists"],
        }

    def get_request_summary(self, request_id, strategy=""):
        request_id = str(request_id)
        summary_context = self.get_allocation_summary(strategy=strategy)

        for item in summary_context["summaries"]:
            if item["request_id"] == request_id:
                return item, summary_context

        return None, summary_context

    def get_schedule_context(self, schedule_type="user", selected_id=""):
        schedule_type = (schedule_type or "user").strip().lower()
        if schedule_type not in {"user", "space"}:
            schedule_type = "user"

        users_table = self.read_csv_table("users.csv")
        spaces_table = self.read_csv_table("spaces.csv")
        requests_table = self.read_csv_table("requests.csv")
        results_table = self.read_csv_table("request_results.csv")
        allocations_table = self.read_csv_table("allocations.csv")
        participants_table = self.read_csv_table("request_participants.csv")
        user_options = build_schedule_resource_options(
            users_table["rows"],
            "userId",
            ["name", "role"],
            SCHEDULE_USER_ROLES,
        )
        space_options = build_schedule_resource_options(
            spaces_table["rows"],
            "spaceId",
            ["name", "type", "building"],
        )
        requests_by_id = index_by_field(requests_table["rows"], "requestId")
        results_by_request = index_by_field(results_table["rows"], "requestId")
        participants_by_request = group_by_field(participants_table["rows"], "requestId")
        spaces_by_id = index_by_field(spaces_table["rows"], "spaceId")

        selected_id = (selected_id or "").strip()
        selected_resource = None
        schedule_rows = []
        event_file_available = True
        event_message = ""

        if schedule_type == "user":
            if not selected_id and user_options:
                selected_id = user_options[0]["id"]

            selected_resource = next(
                (option["row"] for option in user_options if option["id"] == selected_id),
                None,
            )
            busy_table = self.read_csv_table("user_busy_slots.csv")
            event_file_available = busy_table["exists"] or allocations_table["exists"]

            if not event_file_available:
                event_message = "No user busy-slot or allocation data available."

            events = build_user_schedule_events(
                selected_id,
                busy_table["rows"],
                allocations_table["rows"],
                requests_by_id,
                results_by_request,
                participants_by_request,
                spaces_by_id,
            )
            schedule_rows = build_weekly_schedule_grid(events, "busy")
        else:
            if not selected_id and space_options:
                selected_id = space_options[0]["id"]

            selected_resource = next(
                (option["row"] for option in space_options if option["id"] == selected_id),
                None,
            )
            event_file_available = allocations_table["exists"]

            if not event_file_available:
                event_message = "No allocation data available yet. Run allocation first."

            events = build_space_schedule_events(
                selected_id,
                allocations_table["rows"],
                requests_by_id,
                results_by_request,
            )
            schedule_rows = build_weekly_schedule_grid(events, "allocated")

        return {
            "schedule_type": schedule_type,
            "user_options": user_options,
            "space_options": space_options,
            "selected_id": selected_id,
            "selected_resource": selected_resource,
            "day_headers": [DAY_NAMES[day] for day in SCHEDULE_DAYS],
            "schedule_rows": schedule_rows,
            "event_file_available": event_file_available,
            "event_message": event_message,
            "users_available": users_table["exists"],
            "spaces_available": spaces_table["exists"],
        }


def display_value(value, fallback="N/A"):
    stripped = (value or "").strip()
    if not stripped or stripped == "None":
        return fallback
    return stripped


def request_type_label(request_type):
    return REQUEST_TYPE_LABELS.get(request_type, display_value(request_type))


def format_day_name(value):
    try:
        day = int(str(value).strip())
    except (TypeError, ValueError):
        return display_value(value)

    return DAY_NAMES.get(day, display_value(value))


def format_time_part(value):
    raw = (value or "").strip()
    if not raw:
        return "N/A"

    if ":" in raw:
        parts = raw.split(":")
        try:
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0
            return f"{hour:02d}:{minute:02d}"
        except ValueError:
            return raw

    try:
        hour = int(raw)
    except ValueError:
        return raw

    return f"{hour:02d}:00"


def format_time_segment(day, start, end):
    return f"{format_day_name(day)} {format_time_part(start)}-{format_time_part(end)}"


def format_time_data(time_data):
    raw = (time_data or "").strip()
    if not raw or raw == "None":
        return "N/A"

    segments = []
    for segment in raw.split(";"):
        pieces = [piece.strip() for piece in segment.split("-")]
        if len(pieces) != 3:
            segments.append(segment.strip())
            continue

        day, start, end = pieces
        segments.append(format_time_segment(day, start, end))

    return "; ".join(segments)


def format_slot_display(day, start, end):
    return format_time_segment(day, start, end)


def safe_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def parse_time_to_minutes(value):
    raw = (value or "").strip()
    if not raw:
        return None

    try:
        if ":" in raw:
            hour_token, minute_token = raw.split(":", 1)
            hour = int(hour_token)
            minute = int(minute_token)
        else:
            hour = int(raw)
            minute = 0
    except ValueError:
        return None

    if hour < 0 or minute < 0 or minute >= 60:
        return None

    return hour * 60 + minute


def format_minutes(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def time_ranges_overlap(start_a, end_a, start_b, end_b):
    return start_a < end_b and start_b < end_a


def is_exam_request(row):
    request_type = (row.get("requestType") or "").strip()
    purpose = (row.get("purpose") or "").strip()
    return request_type == "Exam" or purpose == "Exam"


def index_by_field(rows, field_name):
    indexed = {}

    for row in rows:
        key = (row.get(field_name) or "").strip()
        if key:
            indexed[key] = row

    return indexed


def group_by_field(rows, field_name):
    grouped = {}

    for row in rows:
        key = (row.get(field_name) or "").strip()
        if key:
            grouped.setdefault(key, []).append(row)

    return grouped


def is_committee_request(row):
    return (row.get("requestType") or "").strip() == "CommitteeMeeting"


def build_committee_participant_display(participant_rows, users_by_id):
    participants = []

    for participant_row in participant_rows:
        user_id = (participant_row.get("userId") or "").strip()
        user = users_by_id.get(user_id, {})
        participants.append(
            {
                "user_id": user_id,
                "name": display_value(user.get("name"), f"User {user_id}"),
                "role": display_value(participant_row.get("participantRole"), "Participant"),
                "user_role": display_value(user.get("role")),
            }
        )

    return participants


def extract_meeting_suggestion_text(lifecycle_history):
    history = (lifecycle_history or "").strip()
    if not history:
        return ""

    for event in history.split(" | "):
        event = event.strip()
        if event.startswith("Suggested least-change alternative times:"):
            return event
        if event.startswith("Suggested alternative times:"):
            return event
        if event == "No available alternative time found.":
            return event

    return ""


def extract_meeting_suggestions(lifecycle_history):
    suggestion_text = extract_meeting_suggestion_text(lifecycle_history)
    if not suggestion_text:
        return None

    if suggestion_text == "No available alternative time found.":
        return {
            "heading": "Suggested alternative times",
            "items": [],
            "empty_message": suggestion_text,
            "raw": suggestion_text,
        }

    heading, separator, body = suggestion_text.partition(":")
    if not separator:
        return {
            "heading": "Suggested alternative times",
            "items": [],
            "empty_message": "",
            "raw": suggestion_text,
        }

    items = []
    for part in body.split(";"):
        cleaned = part.strip()
        if not cleaned:
            continue

        cleaned = re.sub(r"^\d+\)\s*", "", cleaned)
        items.append(cleaned)

    return {
        "heading": heading.strip(),
        "items": items,
        "empty_message": "" if items else body.strip(),
        "raw": suggestion_text,
    }


def get_room_capacity(space):
    if not space:
        return None
    return safe_int(space.get("capacity"))


def build_assigned_room(allocation, spaces_by_id):
    space_id = (allocation.get("spaceId") or "").strip()
    space = spaces_by_id.get(space_id, {})
    capacity = get_room_capacity(space)

    return {
        "space_id": space_id,
        "name": display_value(allocation.get("spaceName") or space.get("name")),
        "type": display_value(allocation.get("spaceType") or space.get("type")),
        "building": display_value(allocation.get("building") or space.get("building")),
        "capacity": capacity,
        "capacity_display": capacity if capacity is not None else "N/A",
        "assigned": safe_int(allocation.get("assignedParticipants")) or 0,
        "time": format_slot_display(
            allocation.get("day"),
            allocation.get("startHour"),
            allocation.get("endHour"),
        ),
    }


def request_status_from_results(request_id, results_by_request):
    result_row = results_by_request.get(request_id, {})
    return (result_row.get("status") or "").strip()


def request_title_for_schedule(request_id, requests_by_id, results_by_request):
    request_row = requests_by_id.get(request_id, {})
    result_row = results_by_request.get(request_id, {})
    return display_value(
        request_row.get("title") or result_row.get("title"),
        f"Request {request_id}",
    )


def allocation_time_parts(allocation):
    day = safe_int(allocation.get("day"))
    start_minutes = parse_time_to_minutes(allocation.get("startHour"))
    end_minutes = parse_time_to_minutes(allocation.get("endHour"))

    if day not in DAY_NAMES or start_minutes is None or end_minutes is None:
        return None

    if start_minutes >= end_minutes:
        return None

    return day, start_minutes, end_minutes


def build_schedule_resource_options(rows, id_field, label_fields, role_filter=None):
    options = []

    for row in rows:
        if role_filter is not None and (row.get("role") or "").strip() not in role_filter:
            continue

        resource_id = (row.get(id_field) or "").strip()
        if not resource_id:
            continue

        labels = [
            (row.get(field) or "").strip()
            for field in label_fields
            if (row.get(field) or "").strip()
        ]
        label = " - ".join(labels) if labels else resource_id
        options.append({"id": resource_id, "label": label, "row": row})

    return options


def build_user_schedule_events(user_id,
                               busy_slots,
                               allocations,
                               requests_by_id,
                               results_by_request,
                               participants_by_request,
                               spaces_by_id):
    events = []
    seen_allocation_events = set()

    for slot in busy_slots:
        if (slot.get("userId") or "").strip() != user_id:
            continue

        day = safe_int(slot.get("day"))
        start_minutes = parse_time_to_minutes(slot.get("startTime"))
        end_minutes = parse_time_to_minutes(slot.get("endTime"))

        if day not in DAY_NAMES or start_minutes is None or end_minutes is None:
            continue

        if start_minutes >= end_minutes:
            continue

        events.append(
            {
                "day": day,
                "start": start_minutes,
                "end": end_minutes,
                "time": f"{format_minutes(start_minutes)}-{format_minutes(end_minutes)}",
                "label": "Busy",
                "detail": display_value(slot.get("reason"), "Busy"),
                "class_name": "busy",
                "request_id": "",
                "request_linkable": False,
            }
        )

    for allocation in allocations:
        request_id = (allocation.get("requestId") or "").strip()
        request_row = requests_by_id.get(request_id)

        if not request_id or not request_row:
            continue

        if request_status_from_results(request_id, results_by_request).lower() != "approved":
            continue

        time_parts = allocation_time_parts(allocation)
        if time_parts is None:
            continue

        relationship_labels = []
        if (request_row.get("userId") or "").strip() == user_id:
            relationship_labels.append("Requester")

        if is_committee_request(request_row):
            for participant in participants_by_request.get(request_id, []):
                if (participant.get("userId") or "").strip() != user_id:
                    continue

                participant_role = display_value(
                    participant.get("participantRole"),
                    "Participant",
                )
                if participant_role not in relationship_labels:
                    relationship_labels.append(participant_role)

        if not relationship_labels:
            continue

        allocation_key = (
            allocation.get("allocationId") or "",
            request_id,
            allocation.get("spaceId") or "",
            allocation.get("day") or "",
            allocation.get("startHour") or "",
            allocation.get("endHour") or "",
        )
        if allocation_key in seen_allocation_events:
            continue
        seen_allocation_events.add(allocation_key)

        day, start_minutes, end_minutes = time_parts
        space_id = (allocation.get("spaceId") or "").strip()
        space = spaces_by_id.get(space_id, {})
        space_name = display_value(
            allocation.get("spaceName") or space.get("name"),
            f"Space {space_id}" if space_id else "Allocated space",
        )
        title = request_title_for_schedule(
            request_id,
            requests_by_id,
            results_by_request,
        )

        events.append(
            {
                "day": day,
                "start": start_minutes,
                "end": end_minutes,
                "time": f"{format_minutes(start_minutes)}-{format_minutes(end_minutes)}",
                "label": f"Request {request_id}: {title}",
                "detail": (
                    f"{', '.join(relationship_labels)}; "
                    f"{space_name}; Approved"
                ),
                "class_name": "allocated",
                "request_id": request_id,
                "request_linkable": True,
            }
        )

    return events


def build_space_schedule_events(space_id, allocations, requests_by_id, results_by_request):
    events = []

    for allocation in allocations:
        if (allocation.get("spaceId") or "").strip() != space_id:
            continue

        time_parts = allocation_time_parts(allocation)
        if time_parts is None:
            continue

        day, start_minutes, end_minutes = time_parts
        request_id = display_value(allocation.get("requestId"))
        assigned = display_value(allocation.get("assignedParticipants"))
        has_request = request_id in requests_by_id or request_id in results_by_request
        title = request_title_for_schedule(
            request_id,
            requests_by_id,
            results_by_request,
        ) if has_request else "External booking"

        events.append(
            {
                "request_id": request_id,
                "request_linkable": has_request,
                "day": day,
                "start": start_minutes,
                "end": end_minutes,
                "time": f"{format_minutes(start_minutes)}-{format_minutes(end_minutes)}",
                "label": (
                    f"Request {request_id}"
                    if has_request
                    else f"Existing allocation {request_id}"
                ),
                "detail": (
                    f"{title}; assigned participants: {assigned}"
                    if has_request
                    else f"External booking; assigned participants: {assigned}"
                ),
                "class_name": "allocated",
            }
        )

    return events


def build_weekly_schedule_grid(events, occupied_class):
    schedule_rows = []

    for block_start, block_end in SCHEDULE_BLOCKS:
        day_cells = []

        for day in SCHEDULE_DAYS:
            overlapping_events = [
                event for event in events
                if event["day"] == day
                and time_ranges_overlap(
                    event["start"],
                    event["end"],
                    block_start,
                    block_end,
                )
            ]

            class_name = "free"
            if overlapping_events:
                event_classes = {
                    event.get("class_name", occupied_class)
                    for event in overlapping_events
                }
                class_name = "busy" if "busy" in event_classes else occupied_class

            day_cells.append(
                {
                    "events": overlapping_events,
                    "class_name": class_name,
                    "label": "Free" if not overlapping_events else "",
                }
            )

        schedule_rows.append(
            {
                "time": f"{format_minutes(block_start)}-{format_minutes(block_end)}",
                "days": day_cells,
            }
        )

    return schedule_rows
