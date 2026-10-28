"""Verified executable invocation only. No Flask initialization or persistence imports."""

import base64
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
from time import perf_counter_ns

from web.backend_executable import BackendExecutableError, file_sha256, resolve_backend_executable
from web.engine_gateway import EngineIntegrationError, validate_appointment_result


ROOT = Path(__file__).resolve().parents[3]
ERROR = "input_engine_error"
UNSUPPORTED = "unsupported_comparison"


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate output key")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("Nonfinite output number")
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except RecursionError as error:
        raise ValueError("Excessively nested JSON") from error


def _integer(value, low=0, high=2**63 - 1):
    return type(value) is int and low <= value <= high


def validate_cdmcs(result, request):
    def check(condition):
        if not condition:
            raise ValueError("Invalid CDMCS response or fixed-calendar permission semantics")
    check(isinstance(result, dict) and result.get("operation") == "cdmcs_schedule_v1"
          and result.get("model") == "V15_restricted_one_blocking_move")
    status = result.get("status")
    check(status in ("OK", "NO_FEASIBLE_PROPOSAL", "UNRESOLVED_CALENDAR"))
    count, returned = result.get("solutions_evaluated"), result.get("returned_count")
    check(_integer(count, 0, len(request["candidate_starts"])) and _integer(returned, 0, request["limit"]))
    rows = result.get("recommendations")
    check(isinstance(rows, list) and len(rows) == returned and returned == min(count, request["limit"]))
    check(type(result.get("truncated")) is bool and result["truncated"] == (count > returned))
    check((status == "OK") == (count > 0))
    seen, keys = set(), []
    for row in rows:
        check(isinstance(row, dict))
        start = row.get("start_minute")
        check(_integer(start) and start in request["candidate_starts"] and start not in seen)
        seen.add(start)
        check(_integer(row.get("end_minute")) and row["end_minute"] == start + request["duration"])
        check(_integer(row.get("total_cost"), -(2**63)) and _integer(row.get("fairness_max_burden")))
        check(row.get("moved_meeting_id") is None and row.get("replacement_start_minute") is None)
        check(row.get("proposal_status") == "DIRECT_PENDING_NORMAL_MEETING_APPROVAL")
        check(row.get("required_permissions") == {"new_meeting_extra_availability": [],
              "relocated_meeting_extra_availability": [], "relocation_participant_approval": []})
        keys.append((row["total_cost"], row["fairness_max_burden"], start))
    check(keys == sorted(keys))
    return UNSUPPORTED if status == "UNRESOLVED_CALENDAR" else ("feasible" if count else "infeasible")


def invoke(command, request, cwd, timeout, engine):
    record = {"engine": engine, "command": list(command), "request": request,
              "classification": ERROR, "stdout": "", "stderr": "", "exit_code": None,
              "payload": None, "error": None, "timings_ns": {}}
    begun = perf_counter_ns()
    try:
        raw = json.dumps(request, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError("Serialized request exceeds 16 MiB")
        encoded = perf_counter_ns()
        record["timings_ns"]["encode"] = encoded - begun
        with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, cwd=cwd) as process:
            launched = perf_counter_ns()
            record["timings_ns"]["launch"] = launched - encoded
            try:
                stdout, stderr = process.communicate(raw, timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
                record["error"] = f"Engine timed out after {timeout} seconds"
            record["exit_code"] = process.returncode
        communicated = perf_counter_ns()
        record["timings_ns"]["communicate"] = communicated - launched
        for label, data in (("stdout", stdout), ("stderr", stderr)):
            record[label] = data.decode("utf-8", errors="backslashreplace")
            if data.decode("utf-8", errors="replace").encode("utf-8") != data:
                record[label + "_base64"] = base64.b64encode(data).decode("ascii")
        if record["error"]:
            return record
        if len(stdout) > 16 * 1024 * 1024:
            raise ValueError("Engine output exceeds 16 MiB")
        payload = strict_json(stdout.decode("utf-8"))
        record["payload"] = payload
        if record["exit_code"] != 0:
            raise ValueError(f"Engine exited with {record['exit_code']}")
        if engine == "production":
            validate_appointment_result(payload, request)
            if request["action"] == "recommend":
                starts = [row["start"] for row in payload["recommendations"]]
                if len(starts) != len(set(starts)) or len(starts) > request["limit"]:
                    raise ValueError("Duplicate/excessive production recommendations")
            record["classification"] = (UNSUPPORTED if payload["reasonCode"] == "UNRESOLVED_CALENDAR"
                                         else ("feasible" if payload["feasible"] else "infeasible"))
        else:
            record["classification"] = validate_cdmcs(payload, request)
        record["timings_ns"]["decode_validate"] = perf_counter_ns() - communicated
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, EngineIntegrationError) as error:
        record["error"] = str(error)
    finally:
        record["timings_ns"]["total"] = perf_counter_ns() - begun
    return record


class OfflineEngines:
    """One owner for a disposable working directory and two pinned read-only CLIs."""

    def __init__(self, cdmcs_path, cdmcs_sha256, production_path=None, timeout=20):
        if type(timeout) not in (float, int) or not math.isfinite(timeout) or not 0 < timeout <= 120:
            raise ValueError("Engine timeout must be finite and at most 120 seconds")
        try:
            self.production = resolve_backend_executable(ROOT, str(production_path) if production_path else None)
        except BackendExecutableError as error:
            raise ValueError(str(error)) from error
        self.cdmcs = Path(cdmcs_path).resolve()
        if not self.cdmcs.is_file() or (os.name != "nt" and not os.access(self.cdmcs, os.X_OK)):
            raise ValueError("Explicit CDMCS executable is missing or not executable")
        if not isinstance(cdmcs_sha256, str) or len(cdmcs_sha256) != 64 or file_sha256(self.cdmcs) != cdmcs_sha256.lower():
            raise ValueError("CDMCS executable SHA-256 does not match the explicit expected hash")
        self.timeout = timeout
        self._temporary = None
        self.hashes = {"production": self.production.metadata["binary_sha256"], "cdmcs": cdmcs_sha256.lower()}

    def __enter__(self):
        self._temporary = tempfile.TemporaryDirectory(prefix="cdmcs-i3a-offline-")
        return self

    def __exit__(self, *args):
        self._temporary.cleanup()
        self._temporary = None

    def execute(self, engine, request):
        if engine not in self.hashes or self._temporary is None:
            raise ValueError("Use a known engine inside the OfflineEngines context")
        path = self.production.path if engine == "production" else self.cdmcs
        if file_sha256(path) != self.hashes[engine]:
            raise ValueError("Pinned executable changed during the experiment")
        command = [str(path)] + (["--appointments-json"] if engine == "production" else [])
        return invoke(command, request, self._temporary.name, self.timeout, engine)

    def provenance(self):
        cmake_files = {}
        for relative in ("CMakeCache.txt", "CMakeFiles/cdmcs_i1.dir/flags.make"):
            path = self.cdmcs.parent / relative
            if path.is_file():
                cmake_files[relative] = {"sha256": file_sha256(path), "text": path.read_text(encoding="utf-8")}
        return {"production_path": str(self.production.path), "production_build": self.production.metadata,
                "production_build_script_sha256": file_sha256(ROOT / "scripts/build_backend.py"),
                "cdmcs_path": str(self.cdmcs), "cdmcs_sha256": self.hashes["cdmcs"],
                "cdmcs_source_sha256": file_sha256(ROOT / "research/cdmcs/i1/src/cdmcs_i1.cpp"),
                "cdmcs_build_files": cmake_files,
                "note": "I1 binary pin and source hash are recorded separately; no embedded build attestation is claimed."}
