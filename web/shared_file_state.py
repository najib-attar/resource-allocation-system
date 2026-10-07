"""Single-machine CSV coordination. All writers must use the same OS lock."""

from contextlib import contextmanager
from pathlib import Path
import csv
import io
import json
import os
import shutil
import tempfile
import time
import uuid

if os.name == "nt":
    import msvcrt
else:
    import fcntl


INPUT_FILES = ("users.csv", "spaces.csv", "requests.csv", "user_busy_slots.csv",
               "request_participants.csv", "config.txt")
OUTPUT_HEADERS = {
    "allocations.csv": "allocationId,requestId,spaceId,spaceName,spaceType,building,day,startHour,endHour,assignedParticipants",
    "request_results.csv": "requestId,requestType,title,purpose,courseCode,courseName,examType,canSplitAcrossRooms,committeeParticipants,requesterName,requesterRole,priority,spaceName,spaceType,spaceBuilding,requiredBuilding,requiredFeature,participants,status,rejectionReason,timeInfo,lifecycleHistory",
    "request_summaries.csv": "requestId,requestType,title,purpose,requesterName,requesterRole,priority,status,rejectionReason,requiredParticipants,assignedParticipants,allocationCount,allocatedSpaces,requiredFeature,requiredBuilding,summaryText",
    "allocation_summaries.csv": "allocationId,requestId,requestTitle,requestPurpose,requestType,spaceName,spaceType,building,day,startTime,endTime,assignedParticipants,spaceCapacity",
}


class SharedStateError(RuntimeError):
    pass


class SharedStateBusy(SharedStateError):
    pass


@contextmanager
def process_lock(path, timeout=5.0):
    """Separate handles contend across threads and processes; never unlink this file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        # Windows permits byte-range locks beyond EOF. No initialization write may
        # race with another worker already holding that byte's lock.
        deadline = time.monotonic() + timeout
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as error:
                # Only contention is retryable, not permission/disk/handle errors.
                if error.errno not in {11, 13, 35, 36}:
                    raise
                if time.monotonic() >= deadline:
                    raise SharedStateBusy("Shared data is busy. Please retry shortly.") from error
                time.sleep(min(.05, max(0, deadline - time.monotonic())))
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def atomic_write(path, contents):
    """Replace one file on the same filesystem, leaving its previous value on failure."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".replace-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(contents)
            file.flush()
            os.fsync(file.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def csv_with_rows(path, headers, rows):
    contents = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    stream = io.StringIO(newline="")
    if contents:
        stream.write(contents)
        if not contents.endswith(("\n", "\r")):
            stream.write("\n")
    writer = csv.DictWriter(stream, fieldnames=headers, extrasaction="ignore")
    if not contents:
        writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


class SharedFileState:
    def __init__(self, data_dir, lock_timeout=5.0):
        self.data_dir = Path(data_dir)
        self.root = self.data_dir / ".runtime"
        self.pointer = self.root / "current.json"
        self.pending_save = self.root / "pending-save.json"
        self.lock_timeout = lock_timeout

    @contextmanager
    def locked(self):
        with process_lock(self.root / "shared.lock", self.lock_timeout):
            try:
                self.recover_save()
                yield self
            except (OSError, json.JSONDecodeError) as error:
                raise SharedStateError(f"Shared-file I/O failed: {error}. Retry; an interrupted save is recovered under the lock.") from error

    def recover_save(self):
        # A tiny roll-forward record prevents a crash between the two CSV replacements
        # from reusing an ID with unrelated participants. Recovery is idempotent.
        if self.pending_save.exists():
            record = json.loads(self.pending_save.read_text(encoding="utf-8"))
            for name in ("request_participants.csv", "requests.csv"):
                atomic_write(self.data_dir / name, record[name].encode("utf-8"))
            self.pending_save.unlink()

    def save_request(self, row, participants, request_headers, participant_headers):
        record = {
            "requests.csv": csv_with_rows(self.data_dir / "requests.csv", request_headers, [row]).decode("utf-8"),
            "request_participants.csv": csv_with_rows(
                self.data_dir / "request_participants.csv", participant_headers, participants
            ).decode("utf-8"),
        }
        atomic_write(self.pending_save, json.dumps(record).encode("utf-8"))
        self.recover_save()

    def write_strategy(self, strategy):
        atomic_write(self.data_dir / "config.txt", f"allocation_strategy={strategy}\n".encode("utf-8"))

    def current_data_dir(self):
        if not self.pointer.exists():
            return None
        try:
            generation = json.loads(self.pointer.read_text(encoding="utf-8"))["generation"]
            if not isinstance(generation, str) or not generation.startswith("generation-") or Path(generation).name != generation:
                raise ValueError("invalid generation name")
            directory = self.root / generation / "data"
            if not directory.is_dir():
                raise ValueError("published generation missing")
            return directory
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise SharedStateError("Published result pointer is invalid; refusing mixed/stale fallback.") from error

    def create_workspace(self):
        workspace = Path(tempfile.mkdtemp(prefix="run-", dir=self.root))
        data = workspace / "data"
        data.mkdir()
        for name in INPUT_FILES:
            source = self.data_dir / name
            if source.exists():
                shutil.copy2(source, data / name)
        return workspace

    def validate_outputs(self, workspace):
        data = workspace / "data"
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

    def publish(self, workspace, metadata):
        self.validate_outputs(workspace)
        generation = "generation-" + uuid.uuid4().hex
        atomic_write(workspace / "metadata.json", json.dumps(metadata).encode("utf-8"))
        destination = self.root / generation
        os.replace(workspace, destination)
        # This is the only operation that makes an entire generation visible.
        atomic_write(self.pointer, json.dumps({"generation": generation}).encode("utf-8"))
        return destination / "data"
