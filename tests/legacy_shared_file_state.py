"""Historical CSV coordination fixtures only; never import from application runtime."""

from contextlib import contextmanager
from pathlib import Path
import csv
import io
import json
import os
import tempfile
import time

if os.name == "nt":
    import msvcrt
else:
    import fcntl


from web.result_table_schema import INPUT_FILES, OUTPUT_HEADERS


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
    def read_engine_result(self):
        path = self.root / "engine-result.json"
        if not path.exists():
            return None
        document = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(document, dict) or not isinstance(document.get("snapshot"), dict)
                or not isinstance(document.get("result"), dict)
                or any(key not in document["snapshot"] for key in ("runId", "strategy", "requests", "spaces"))):
            raise SharedStateError("Invalid published JSON result. Run allocation again; no legacy fallback was used.")
        return document

    def publish_engine_result(self, snapshot, result, metadata):
        # One replacement publishes the input provenance and all result collections together.
        document = {"snapshot": snapshot, "result": result, "build": metadata}
        atomic_write(self.root / "engine-result.json", json.dumps(document, ensure_ascii=False, allow_nan=False).encode("utf-8"))

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
