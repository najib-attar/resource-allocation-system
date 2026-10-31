"""Disabled-by-default, synthetic-only, aggregate internal fixed-calendar comparisons."""

from dataclasses import dataclass
import math
import os
from pathlib import Path
import threading
from time import monotonic

from research.cdmcs.i3a.adapter import _normalize_fixed_calendar
from research.cdmcs.i3a.execution import validate_cdmcs
from web.backend_executable import BackendExecutableError, file_sha256, resolve_backend_executable
from web.engine_gateway import EngineIntegrationError, validate_appointment_result

from .admission import admitted_snapshot
from .process import ProcessFailure, execute
from .serialization import candidate_requests


_SLOT = threading.BoundedSemaphore(1)
ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Budget:
    candidates: int = 256
    per_process_seconds: float = 5
    total_seconds: float = 120
    memory_bytes: int = 256 * 1024 * 1024
    input_bytes: int = 4 * 1024 * 1024
    output_bytes: int = 64 * 1024

    def __post_init__(self):
        for value, lo, hi in ((self.candidates, 1, 256), (self.memory_bytes, 64 * 1024**2, 1024**3),
                              (self.input_bytes, 1024, 4 * 1024**2), (self.output_bytes, 1024, 64 * 1024)):
            if type(value) is not int or not lo <= value <= hi:
                raise ValueError("Invalid internal shadow budget")
        for value, hi in ((self.per_process_seconds, 10), (self.total_seconds, 120)):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= hi:
                raise ValueError("Invalid internal shadow deadline")


@dataclass(frozen=True)
class ShadowResult:
    status: str
    code: str = ""
    complete: bool = False
    candidates: int = 0
    evaluated: int = 0
    cdmcs_feasible: int = 0
    production_feasible: int = 0
    discrepancies: int = 0
    # Aggregate wall times only, not candidate timestamps, ranking or raw diagnostics.
    launch_ns: int = 0
    exchange_ns: int = 0


class ShadowRunner:
    def __init__(self, cdmcs_path=None, cdmcs_sha256=None, *, production_path=None,
                 enabled=False, budget=None):
        if type(enabled) is not bool:
            raise ValueError("Explicit boolean enablement required")
        self.enabled = enabled
        self.budget = budget if budget is not None else Budget()
        if type(self.budget) is not Budget:
            raise ValueError("Invalid internal shadow budget")
        self._cdmcs = cdmcs_path
        self._sha = cdmcs_sha256
        self._production = production_path

    def run(self, value, *, compare=True):
        if not self.enabled:
            return ShadowResult("disabled", "DISABLED")
        if not _SLOT.acquire(blocking=False):
            return ShadowResult("busy", "CONCURRENCY_LIMIT")
        try:
            return self._run(value, compare)
        except ProcessFailure as error:
            return ShadowResult("engine_failure", error.code)
        except (ValueError, TypeError, KeyError, AttributeError, OSError, OverflowError, MemoryError,
                BackendExecutableError):
            # Never propagate dependency messages, source IDs or raw subprocess errors.
            return ShadowResult("input_error", "INVALID_SCOPE_OR_CONFIGURATION")
        finally:
            _SLOT.release()

    def _run(self, value, compare):
        deadline = monotonic() + self.budget.total_seconds
        if type(compare) is not bool:
            raise ValueError()
        snapshot = admitted_snapshot(value)
        # Pre-normalization budgets bound Python allocations, not just child memory.
        required = sum(p.required for p in snapshot.participants)
        windows = sum(len(p.published) for p in snapshot.participants)
        memberships = sum(len(c.people) + len(c.resources) for c in snapshot.commitments)
        if (len(snapshot.participants) > 32 or len(snapshot.commitments) > 2000 or windows > 2048
                or memberships > 10000 or required * ((snapshot.horizon.end - snapshot.anchor) // 60 + 1) > 200000):
            return ShadowResult("unsupported", "NORMALIZATION_BUDGET")
        if any(c.resources for c in snapshot.commitments):
            return ShadowResult("unsupported", "RESOURCE_SEMANTICS")
        normalized = _normalize_fixed_calendar(snapshot)
        if normalized.unsupported:
            return ShadowResult("unsupported", "UNSUPPORTED_CALENDAR_OR_PREFERENCES")
        count = len(normalized.candidates)
        if count > self.budget.candidates:
            return ShadowResult("unsupported", "CANDIDATE_BUDGET")
        cdmcs = Path(self._cdmcs).resolve()
        if (not cdmcs.is_file() or not isinstance(self._sha, str) or len(self._sha) != 64
                or file_sha256(cdmcs) != self._sha.lower()
                or (os.name != "nt" and not os.access(cdmcs, os.X_OK))):
            raise ValueError()
        production = resolve_backend_executable(ROOT, self._production) if compare else None
        hashes = {"cdmcs": self._sha.lower()}
        if production:
            hashes["production"] = production.metadata["binary_sha256"]
        if monotonic() > deadline:
            raise ProcessFailure("RUN_DEADLINE")
        evaluated = feasible_c = feasible_p = discrepancies = launch = exchange = 0
        for candidate in normalized.candidates:
            outcomes = {}
            requests = candidate_requests(value, normalized, candidate, compare)
            if evaluated % 2:
                requests.reverse()
            for engine, args, request in requests:
                path = cdmcs if engine == "cdmcs" else production.path
                if file_sha256(path) != hashes[engine]:
                    raise ProcessFailure("EXECUTABLE_CHANGED")
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise ProcessFailure("RUN_DEADLINE")
                call = execute([str(path), *args], request,
                    timeout=min(remaining, self.budget.per_process_seconds), memory_bytes=self.budget.memory_bytes,
                    input_limit=self.budget.input_bytes, output_limit=self.budget.output_bytes)
                if monotonic() > deadline:
                    raise ProcessFailure("RUN_DEADLINE")
                launch += call.launch_ns
                exchange += call.exchange_ns
                try:
                    if engine == "cdmcs":
                        outcome = validate_cdmcs(call.payload, request)
                        if outcome not in {"feasible", "infeasible"}:
                            raise ValueError()
                    else:
                        validate_appointment_result(call.payload, request)
                        if call.payload["reasonCode"] in {"UNRESOLVED_CALENDAR", "INVALID_INTERVAL"}:
                            raise ValueError()
                        outcome = "feasible" if call.payload["feasible"] else "infeasible"
                except (ValueError, TypeError, KeyError, EngineIntegrationError):
                    raise ProcessFailure("INVALID_PROTOCOL") from None
                outcomes[engine] = outcome
            feasible_c += outcomes["cdmcs"] == "feasible"
            feasible_p += outcomes.get("production") == "feasible"
            discrepancies += compare and outcomes["cdmcs"] != outcomes["production"]
            evaluated += 1
        if monotonic() > deadline:
            raise ProcessFailure("RUN_DEADLINE")
        return ShadowResult("discrepancy" if discrepancies else "match" if compare else "cdmcs_only",
            complete=True, candidates=count, evaluated=evaluated, cdmcs_feasible=feasible_c,
            production_feasible=feasible_p, discrepancies=discrepancies, launch_ns=launch, exchange_ns=exchange)
