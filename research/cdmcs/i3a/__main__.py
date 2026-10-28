"""Run offline synthetic comparisons and retain evidence outside the checkout."""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys

from .comparison import compare
from .execution import OfflineEngines, ROOT, strict_json
from .fixtures import expected_status, matrix


def external_destination(value):
    path = Path(value).resolve()
    if path == ROOT or ROOT in path.parents or path.exists():
        raise ValueError("Evidence destination must be new and outside the checkout")
    return path


def export(destination, reports, provenance, command):
    destination = external_destination(destination)
    destination.mkdir(parents=True, exist_ok=False)
    metadata = {"created_at": datetime.now(timezone.utc).isoformat(), "python": sys.version,
                "platform": platform.platform(), "tzdata": importlib.metadata.version("tzdata"),
                "command": command, "executables": provenance,
                "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "working_tree": subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, text=True),
                "sources": {}}
    for directory in (ROOT / "research/cdmcs/i3a", ROOT / "research/cdmcs/i1", ROOT / "src"):
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path.suffix in (".py", ".cpp", ".h", ".hpp", ".txt", ".md", ".json"):
                metadata["sources"][path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    files = []
    for index, report in enumerate(reports):
        name = f"case-{index:03d}.json"
        raw = (json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")
        (destination / name).write_bytes(raw)
        files.append({"file": name, "sha256": hashlib.sha256(raw).hexdigest(),
                      "snapshot_id": report.get("snapshot_id", report["input"].get("snapshot_id") if isinstance(report["input"], dict) else None),
                      "status": report["status"], "complete": report["complete"],
                      "candidate_count": report.get("candidate_count"),
                      "feasible_count": {key: len(value) for key, value in report.get("feasible_sets", {}).items()},
                      "discrepancies": report["discrepancies"], "timings": report.get("timings")})
    (destination / "provenance.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    summary = {"cases": files, "explanation": "Equal means complete feasible-set equality on this explicit synthetic candidate universe only; rankings/objectives and process timings are separate."}
    (destination / "index.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--matrix", action="store_true")
    group.add_argument("--input", type=Path, help="One explicitly synthetic snapshot JSON")
    parser.add_argument("--cdmcs", type=Path, required=True)
    parser.add_argument("--cdmcs-sha256", required=True)
    parser.add_argument("--production", type=Path, help="Optional manifest-validated production artifact")
    parser.add_argument("--output", type=Path, required=True, help="New evidence directory outside checkout")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--warmups", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=20)
    args = parser.parse_args()
    try:
        destination = external_destination(args.output)
        if args.input:
            with args.input.open("rb") as stream:
                raw = stream.read(16 * 1024 * 1024 + 1)
            if len(raw) > 16 * 1024 * 1024:
                raise ValueError("Snapshot exceeds 16 MiB")
            values = [strict_json(raw.decode("utf-8"))]
        else:
            values = matrix()
        with OfflineEngines(args.cdmcs, args.cdmcs_sha256, args.production, args.timeout) as engines:
            reports = [compare(value, engines, args.repetitions, args.warmups) for value in values]
            summary = export(destination, reports, engines.provenance(), sys.argv)
        print(json.dumps({"output": str(destination), "cases": [{k: row[k] for k in ("snapshot_id", "status", "candidate_count", "feasible_count")} for row in summary["cases"]]}, indent=2))
        if args.matrix:
            return 1 if any(report["discrepancies"] or report["status"] != expected_status(value)
                            for value, report in zip(values, reports)) else 0
        return {"equal": 0, "discrepancy": 1, "input_engine_error": 2, "unsupported_comparison": 3}[reports[0]["status"]]
    except (ValueError, OSError, UnicodeError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
