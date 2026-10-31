"""Bounded stdin/stdout transport. Never retain diagnostics, payloads or paths in errors."""

from dataclasses import dataclass, field
import json
import os
import signal
import subprocess
import tempfile
import threading
from time import monotonic, perf_counter_ns

from research.cdmcs.i3a.execution import strict_json


class ProcessFailure(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__("Internal shadow process failed: " + code)


@dataclass(frozen=True, repr=False)
class ProcessResult:
    payload: dict = field(repr=False)
    launch_ns: int
    exchange_ns: int

    def __repr__(self):
        return "ProcessResult(payload withheld)"


def _windows_job(process, memory_bytes):
    # Assign before sending stdin: these pinned CLIs cannot evaluate until EOF.
    import ctypes as c
    from ctypes import wintypes as w
    kernel = c.WinDLL("kernel32", use_last_error=True)

    class Basic(c.Structure):
        _fields_ = [("process_time", c.c_int64), ("job_time", c.c_int64), ("flags", w.DWORD),
                    ("minimum", c.c_size_t), ("maximum", c.c_size_t), ("active", w.DWORD),
                    ("affinity", c.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]

    class IO(c.Structure):
        _fields_ = [(name, c.c_uint64) for name in ("read", "write", "other", "read_bytes", "write_bytes", "other_bytes")]

    class Extended(c.Structure):
        _fields_ = [("basic", Basic), ("io", IO), ("process_memory", c.c_size_t),
                    ("job_memory", c.c_size_t), ("peak_process", c.c_size_t), ("peak_job", c.c_size_t)]

    kernel.CreateJobObjectW.argtypes = [c.c_void_p, w.LPCWSTR]
    kernel.CreateJobObjectW.restype = w.HANDLE
    kernel.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
    kernel.SetInformationJobObject.restype = w.BOOL
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
    kernel.AssignProcessToJobObject.restype = w.BOOL
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.CloseHandle.restype = w.BOOL
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise ProcessFailure("LIMIT_SETUP")
    handle = None
    try:
        limits = Extended()
        # KILL_ON_JOB_CLOSE | PROCESS_MEMORY | ACTIVE_PROCESS (one child only).
        limits.basic.flags = 0x2000 | 0x100 | 0x8
        limits.basic.active = 1
        limits.process_memory = memory_bytes
        if not kernel.SetInformationJobObject(job, 9, c.byref(limits), c.sizeof(limits)):
            raise ProcessFailure("LIMIT_SETUP")
        handle = kernel.OpenProcess(0x100 | 0x1, False, process.pid)
        if not handle or not kernel.AssignProcessToJobObject(job, handle):
            raise ProcessFailure("LIMIT_SETUP")
    except BaseException:
        kernel.CloseHandle(job)
        raise
    finally:
        if handle:
            kernel.CloseHandle(handle)
    return lambda: kernel.CloseHandle(job)


def _limits(process, memory_bytes, timeout):
    if os.name == "nt":
        return _windows_job(process, memory_bytes)
    import resource
    if not hasattr(resource, "prlimit"):
        raise ProcessFailure("LIMIT_UNSUPPORTED")
    # Linux prlimit avoids unsafe preexec_fn in a threaded parent. Set before stdin.
    resource.prlimit(process.pid, resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    cpu = max(1, int(timeout) + 1)
    resource.prlimit(process.pid, resource.RLIMIT_CPU, (cpu, cpu))
    resource.prlimit(process.pid, resource.RLIMIT_CORE, (0, 0))
    return lambda: None


def _kill(process):
    if os.name == "nt":
        if process.poll() is None:
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def execute(command, request, *, timeout, memory_bytes, input_limit, output_limit):
    """No shell, environment overrides, raw logging, evidence records or file payloads."""
    try:
        deadline = monotonic() + timeout
        raw = json.dumps(request, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        if len(raw) > input_limit:
            raise ProcessFailure("INPUT_LIMIT")
        # An empty disposable cwd prevents accidental shared runtime file access.
        with tempfile.TemporaryDirectory(prefix="cdmcs-i3c-") as cwd:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise ProcessFailure("TIMEOUT")
            return _communicate(command, raw, cwd, remaining, memory_bytes, output_limit)
    except ProcessFailure:
        raise
    except (OSError, ValueError, TypeError, UnicodeError, MemoryError):
        raise ProcessFailure("PROCESS_IO") from None


def _communicate(command, raw, cwd, timeout, memory_bytes, output_limit):
    process = None
    close_limits = lambda: None
    threads, errors, output = [], [], bytearray()
    begun = perf_counter_ns()
    deadline = monotonic() + timeout
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, cwd=cwd, shell=False, start_new_session=os.name != "nt")
        launched = perf_counter_ns()
        close_limits = _limits(process, memory_bytes, timeout)

        def read(stream, retain):
            size = 0
            try:
                while chunk := stream.read(4096):
                    size += len(chunk)
                    if size > output_limit:
                        errors.append("OUTPUT_LIMIT")
                        _kill(process)
                        break
                    if retain:
                        output.extend(chunk)
            except OSError:
                errors.append("PROCESS_IO")

        def write():
            try:
                process.stdin.write(raw)
                process.stdin.close()
            except (OSError, ValueError):
                # Early process exit is checked below, not misclassified infeasible.
                pass

        for target, args in ((read, (process.stdout, True)), (read, (process.stderr, False)), (write, ())):
            thread = threading.Thread(target=target, args=args, daemon=True)
            try:
                thread.start()
            except RuntimeError:
                raise ProcessFailure("THREAD_START") from None
            # Only successfully started threads may be joined during cleanup.
            threads.append(thread)
        while process.poll() is None or any(t.is_alive() for t in threads):
            if monotonic() >= deadline:
                raise ProcessFailure("TIMEOUT")
            if errors:
                raise ProcessFailure(errors[0])
            for thread in threads:
                thread.join(0.005)
        if errors:
            raise ProcessFailure(errors[0])
        if process.returncode:
            raise ProcessFailure("ENGINE_EXIT")
        try:
            payload = strict_json(output.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError()
        except (ValueError, UnicodeError, TypeError):
            raise ProcessFailure("MALFORMED_RESPONSE") from None
        if monotonic() > deadline:
            raise ProcessFailure("TIMEOUT")
        return ProcessResult(payload, launched - begun, perf_counter_ns() - launched)
    except ProcessFailure:
        raise
    except (OSError, ValueError, MemoryError):
        raise ProcessFailure("LIMIT_OR_PROCESS_FAILURE") from None
    finally:
        if process is not None:
            _kill(process)
            close_limits()
            process.wait()
            for thread in threads:
                thread.join(2)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()
