"""Explicit synthetic-only path measurements, not an optimizer speed benchmark."""

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import platform
from statistics import median
import subprocess
from time import perf_counter_ns
from unittest import mock

from research.cdmcs.i3a.fixtures import basic, period, stamp
from research.cdmcs.i3c.admission import synthetic_fixture
from research.cdmcs.i3c.runner import ShadowRunner
from web.backend_executable import file_sha256, resolve_backend_executable


def _windows_usage(process):
    import ctypes as c
    from ctypes import wintypes as w
    kernel, psapi = c.WinDLL("kernel32"), c.WinDLL("psapi")
    kernel.GetProcessTimes.argtypes = [w.HANDLE, *([c.POINTER(w.FILETIME)] * 4)]
    kernel.GetProcessTimes.restype = w.BOOL

    class Memory(c.Structure):
        _fields_ = [("cb", w.DWORD), ("faults", w.DWORD)] + [
            (name, c.c_size_t) for name in ("peak_rss", "rss", "peak_paged", "paged",
                "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile")]

    psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, c.POINTER(Memory), w.DWORD]
    psapi.GetProcessMemoryInfo.restype = w.BOOL
    created, exited, system, user = (w.FILETIME() for _ in range(4))
    cpu = None
    # CPython's Windows Popen retains its process handle while this object lives.
    handle = getattr(process, "_handle", None)
    if handle is not None and kernel.GetProcessTimes(int(handle), c.byref(created), c.byref(exited),
                                                    c.byref(system), c.byref(user)):
        cpu = sum((value.dwHighDateTime << 32) + value.dwLowDateTime for value in (system, user)) * 100
    memory = Memory()
    memory.cb = c.sizeof(memory)
    peak = memory.peak_rss if handle is not None and psapi.GetProcessMemoryInfo(
        int(handle), c.byref(memory), memory.cb) else None
    return cpu, peak


def fixture(count):
    value = basic()
    end = 15 * (count - 1) + value["duration_minutes"]
    value["horizon"] = period(0, end)
    value["participants"][1]["published"] = [period(0, end)]
    value["candidates"] = {"mode": "explicit", "anchor_participant": "professor-A",
                           "starts": [stamp(15 * index) for index in range(count)]}
    return synthetic_fixture(value)


def measure(runner, scope):
    from research.cdmcs.i3c import runner as module
    original_spawn = subprocess.Popen
    children, maximum_active = [], 0
    hashes = {key: {"calls": 0, "bytes": 0, "ns": 0} for key in ("runner", "resolver")}

    def spawn(*args, **kwargs):
        nonlocal maximum_active
        child = original_spawn(*args, **kwargs)
        children.append(child)
        maximum_active = max(maximum_active, sum(p.poll() is None for p in children))
        return child

    def hashing(key):
        def hashed(path):
            begun = perf_counter_ns()
            result = file_sha256(path)
            hashes[key]["calls"] += 1
            hashes[key]["bytes"] += Path(path).stat().st_size
            hashes[key]["ns"] += perf_counter_ns() - begun
            return result
        return hashed

    before = None
    if os.name != "nt":
        import resource
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
    begun = perf_counter_ns()
    with mock.patch("research.cdmcs.i3c.process.subprocess.Popen", new=spawn), \
         mock.patch.object(module, "file_sha256", new=hashing("runner")), \
         mock.patch("web.backend_executable.file_sha256", new=hashing("resolver")):
        result = runner.run(scope)
    elapsed = perf_counter_ns() - begun
    if (result.status != "match" or not result.complete or result.cdmcs_feasible != result.candidates
            or len(children) != 2 * result.candidates or maximum_active > 1):
        raise ValueError("Synthetic benchmark comparison failed")
    cpu, peak = None, None
    if os.name == "nt":
        usage = [_windows_usage(child) for child in children]
        if all(item[0] is not None for item in usage):
            cpu = sum(item[0] for item in usage)
        if all(item[1] is not None for item in usage):
            peak = max(item[1] for item in usage)
    else:
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu = round((after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime) * 10**9)
        # Linux maxrss is cumulative maximum across terminated children, not per trial.
        peak = after.ru_maxrss * 1024
    return {"result": asdict(result), "wall_ns": elapsed, "processes": len(children),
            "max_active_children": maximum_active, "child_cpu_ns": cpu, "peak_child_rss_bytes": peak,
            "peak_memory_scope": "trial child maximum" if os.name == "nt" else "experiment cumulative child maximum",
            "hashing": hashes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cdmcs", required=True)
    parser.add_argument("--cdmcs-sha256", required=True)
    parser.add_argument("--production", required=True)
    parser.add_argument("--candidates", type=int, nargs="+", default=[1, 8, 32, 128])
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    args = parser.parse_args()
    if (not 1 <= args.repetitions <= 5 or not 0 <= args.warmups <= 2
            or len(args.candidates) > 8 or any(not 1 <= n <= 256 for n in args.candidates)
            or 2 * sum(args.candidates) * (args.repetitions + args.warmups) > 10000):
        parser.error("Benchmark exceeds its explicit experiment budget")
    try:
        runner = ShadowRunner(args.cdmcs, args.cdmcs_sha256, production_path=args.production, enabled=True)
        provenance = {"platform": platform.platform(), "python": platform.python_version(),
            "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            "working_tree": subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], text=True),
            "source_sha256": {name: file_sha256(Path(__file__).with_name(name))
                              for name in ("benchmark.py", "admission.py", "serialization.py", "runner.py", "process.py")},
            "cdmcs_sha256": file_sha256(args.cdmcs),
            "production": resolve_backend_executable(".", args.production).metadata}
        rows = []
        for count in args.candidates:
            scope = fixture(count)
            for _ in range(args.warmups):
                measure(runner, scope)
            trials = [measure(runner, scope) for _ in range(args.repetitions)]
            rows.append({"candidate_count": count, "trials": trials,
                         "median_wall_ns": median(row["wall_ns"] for row in trials)})
        print(json.dumps({"provenance": provenance, "rows": rows,
            "methodology": "One professor; fixed all-feasible synthetic calendars; sequential same-interval paired singletons; 2N child invocations. Explicit build flags are in build metadata/logs. Child CPU includes native parsing, scheduling and serialization, not scheduling alone. Popen time is partial startup only. Peak memory may be unavailable; Linux is cumulative including setup children. Timings are path measurements under possibly concurrent host load, not an algorithmic speedup claim."}, indent=2))
        return 0
    except (ValueError, OSError):
        parser.exit(2, "Synthetic benchmark failed; no calendar diagnostics retained.\n")


if __name__ == "__main__":
    raise SystemExit(main())
