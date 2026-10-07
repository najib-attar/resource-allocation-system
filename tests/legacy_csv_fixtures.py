"""Legacy CSV fixtures/validation for CLI and pre-JSON result-reader regressions."""

from pathlib import Path
import csv
import shutil
import tempfile

from web.shared_file_state import INPUT_FILES, OUTPUT_HEADERS, SharedStateError


def create_legacy_workspace(state):
    workspace = Path(tempfile.mkdtemp(prefix="run-", dir=state.root))
    data = workspace / "data"
    data.mkdir()
    for name in INPUT_FILES:
        source = state.data_dir / name
        if source.exists():
            shutil.copy2(source, data / name)
    return workspace


def validate_legacy_outputs(data):
    tables = {}
    for name, expected in OUTPUT_HEADERS.items():
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
            raise SharedStateError(f"Backend output {name} is missing or unusable: {error}") from error
    with (data / "requests.csv").open(encoding="utf-8-sig", newline="") as file:
        request_ids = {row["requestId"] for row in csv.DictReader(file)}
    for name in ("request_results.csv", "request_summaries.csv"):
        rows = tables[name]
        ids = [row["requestId"] for row in rows]
        if set(ids) != request_ids or len(ids) != len(request_ids):
            raise SharedStateError(f"Backend output {name} does not cover the input requests.")
        if any(row["status"] not in {"Pending", "Approved", "Rejected"} for row in rows):
            raise SharedStateError(f"Backend output {name} contains invalid statuses.")
    statuses = {row["requestId"]: row["status"] for row in tables["request_results.csv"]}
    if any(row["status"] != statuses[row["requestId"]] for row in tables["request_summaries.csv"]):
        raise SharedStateError("Backend request outputs disagree on status.")
    allocations = tables["allocations.csv"]
    summaries = tables["allocation_summaries.csv"]
    if [(row["allocationId"], row["requestId"]) for row in allocations] != [
            (row["allocationId"], row["requestId"]) for row in summaries]:
        raise SharedStateError("Backend allocation outputs disagree.")
    if any(row["requestId"] not in request_ids for row in allocations):
        raise SharedStateError("Backend output refers to a missing request.")
