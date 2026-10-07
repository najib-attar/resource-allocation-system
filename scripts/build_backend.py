"""Build the authoritative backend artifact and its freshness manifest."""

from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys
import tempfile


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from web.backend_executable import (  # noqa: E402
    default_backend_path,
    file_sha256,
    manifest_path,
    source_files,
    source_fingerprint,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default=os.environ.get("CXX", "g++"),
                        help="Compiler executable path (not a shell command).")
    parser.add_argument("--output", help="Optional artifact path; relative to the project root.")
    args = parser.parse_args()
    output = Path(args.output) if args.output else default_backend_path(PROJECT_ROOT)
    if not output.is_absolute():
        output = PROJECT_ROOT / output
    output = output.resolve()

    try:
        before = source_fingerprint(PROJECT_ROOT)
        sources = [str(path) for path in source_files(PROJECT_ROOT) if path.suffix == ".cpp"]
        if not sources:
            raise RuntimeError("No C++ backend sources were found.")
        version = subprocess.run([args.compiler, "--version"], check=True,
                                 capture_output=True, text=True).stdout.strip()
        compiler = version.splitlines()[0] if version else args.compiler
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="backend-build-", dir=output.parent) as temporary:
            binary = Path(temporary) / output.name
            subprocess.run([args.compiler, "-std=c++17", *sources, "-o", str(binary)], check=True)
            if source_fingerprint(PROJECT_ROOT) != before:
                raise RuntimeError("C++ sources changed during compilation; rebuild before running.")
            metadata = {
                "schema_version": 1,
                "source_sha256": before,
                "binary_sha256": file_sha256(binary),
                "built_at": datetime.now(timezone.utc).isoformat(),
                "compiler": compiler,
            }
            metadata_file = Path(temporary) / "build.json"
            metadata_file.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
            os.replace(binary, output)
            os.replace(metadata_file, manifest_path(output))
        print(f"Backend built: {output}")
        print(f"Source SHA-256: {before}")
        return 0
    except (OSError, subprocess.CalledProcessError, RuntimeError) as error:
        print(f"Backend build failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
