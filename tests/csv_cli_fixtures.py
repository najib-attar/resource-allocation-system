"""Standalone CSV CLI output validation and legacy suggestion parity only."""

import csv
import re

from web.result_table_schema import OUTPUT_HEADERS

CSV_OUTPUT_HEADERS = {name + ".csv": headers for name, headers in OUTPUT_HEADERS.items()}


def validate_cli_outputs(data):
    tables = {}
    for name, expected in CSV_OUTPUT_HEADERS.items():
        try:
            with (data / name).open(encoding="utf-8-sig", newline="") as file:
                reader = csv.DictReader(file, strict=True)
                if reader.fieldnames != expected.split(","):
                    raise ValueError("unexpected CSV header")
                rows = list(reader)
                if any(None in row or any(value is None for value in row.values()) for row in rows):
                    raise ValueError("incomplete CSV row")
                tables[name] = rows
        except (OSError, UnicodeError, csv.Error, ValueError) as error:
            raise ValueError(f"Backend output {name} is missing or unusable: {error}") from error
    with (data / "requests.csv").open(encoding="utf-8-sig", newline="") as file:
        request_ids = {row["requestId"] for row in csv.DictReader(file)}
    for name in ("request_results.csv", "request_summaries.csv"):
        rows = tables[name]
        ids = [row["requestId"] for row in rows]
        if set(ids) != request_ids or len(ids) != len(request_ids):
            raise ValueError(f"Backend output {name} does not cover the input requests.")
        if any(row["status"] not in {"Pending", "Approved", "Rejected"} for row in rows):
            raise ValueError(f"Backend output {name} contains invalid statuses.")
    statuses = {row["requestId"]: row["status"] for row in tables["request_results.csv"]}
    if any(row["status"] != statuses[row["requestId"]] for row in tables["request_summaries.csv"]):
        raise ValueError("Backend request outputs disagree on status.")
    allocations = tables["allocations.csv"]
    summaries = tables["allocation_summaries.csv"]
    if [(row["allocationId"], row["requestId"]) for row in allocations] != [
            (row["allocationId"], row["requestId"]) for row in summaries]:
        raise ValueError("Backend allocation outputs disagree.")
    if any(row["requestId"] not in request_ids for row in allocations):
        raise ValueError("Backend output refers to a missing request.")



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
