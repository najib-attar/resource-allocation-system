"""Resolve and validate the single configured C++ build artifact."""

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import os


class BackendExecutableError(RuntimeError):
    pass


@dataclass(frozen=True)
class BackendExecutable:
    path: Path
    metadata: dict


def default_backend_path(project_root):
    name = "allocation_system.exe" if os.name == "nt" else "allocation_system"
    return Path(project_root) / "build" / "backend" / name


def manifest_path(executable):
    return executable.with_name(executable.name + ".build.json")


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_files(project_root):
    source_root = Path(project_root) / "src"
    return sorted(
        (path for path in source_root.rglob("*")
         if path.is_file() and path.suffix in {".cpp", ".h", ".hpp"}),
        key=lambda path: path.relative_to(source_root).as_posix(),
    )


def source_fingerprint(project_root):
    paths = source_files(project_root)
    if not paths:
        return None
    digest = hashlib.sha256()
    for path in paths:
        name = path.relative_to(project_root).as_posix().encode("utf-8")
        digest.update(name + b"\0" + bytes.fromhex(file_sha256(path)))
    return digest.hexdigest()


def resolve_backend_executable(project_root, configured_path=None):
    root = Path(project_root).resolve()
    rebuild = "Rebuild with python scripts/build_backend.py."
    if configured_path is not None and not configured_path.strip():
        raise BackendExecutableError("RESOURCE_ALLOCATION_BACKEND must not be empty. " + rebuild)
    path = Path(configured_path) if configured_path is not None else default_backend_path(root)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()

    try:
        if not path.is_file():
            raise BackendExecutableError(f"Configured backend executable is missing: {path}. {rebuild}")
        if os.name != "nt" and not os.access(path, os.X_OK):
            raise BackendExecutableError(f"Configured backend is not executable: {path}.")
        metadata = json.loads(manifest_path(path).read_text(encoding="utf-8"))
        required = ("source_sha256", "binary_sha256", "built_at", "compiler")
        if (not isinstance(metadata, dict) or metadata.get("schema_version") != 1 or
                any(not isinstance(metadata.get(key), str) or not metadata[key] for key in required)):
            raise BackendExecutableError(f"Invalid backend build metadata for {path}. {rebuild}")
        if file_sha256(path) != metadata["binary_sha256"]:
            raise BackendExecutableError(f"Backend binary does not match its build metadata: {path}. {rebuild}")
        current_sources = source_fingerprint(root)
        if (root / "src").exists() and current_sources is None:
            raise BackendExecutableError(f"Cannot validate an empty C++ source tree. {rebuild}")
        if current_sources is not None and current_sources != metadata["source_sha256"]:
            raise BackendExecutableError(f"Backend is stale: C++ sources differ from the build at {path}. {rebuild}")
    except (OSError, ValueError) as error:
        raise BackendExecutableError(f"Cannot validate backend build at {path}: {error}. {rebuild}") from error

    return BackendExecutable(path, metadata)
