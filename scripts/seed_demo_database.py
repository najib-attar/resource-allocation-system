"""Seed a NEW EMPTY development database with fictional inputs; never reset data."""

import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.exc import SQLAlchemyError
from web.allocation_workflow import execute_allocation
from web.engine_gateway import EngineGateway, EngineIntegrationError
from web.backend_executable import BackendExecutableError
from web.persistence.database import Database, DatabaseConfigurationError, DatabaseBusy
from web.persistence.demo import demo_snapshot, seed_demo_database
from web.persistence.repository import PersistenceError, Repository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=41)
    parser.add_argument("--size", choices=("moderate", "large"), default="moderate")
    parser.add_argument("--dry-run", action="store_true", help="Validate/count fictional inputs without connecting to PostgreSQL.")
    parser.add_argument("--run-allocation", action="store_true", help="Execute the real engine after successful seeding.")
    args = parser.parse_args()
    database = None
    try:
        if args.dry_run:
            snapshot, _ = demo_snapshot(args.seed, args.size)
            report = {"dryRun": True, "seed": args.seed, "size": args.size,
                      "counts": {key: len(snapshot[key]) for key in ("users", "spaces", "requests", "busySlots")}}
        else:
            database = Database()
            report = seed_demo_database(database, args.seed, args.size)
            if args.run_allocation:
                started = time.monotonic()
                result = execute_allocation(Repository(database), EngineGateway(Path(__file__).resolve().parent.parent))
                report["allocation"] = {"seconds": round(time.monotonic() - started, 3), "rows": len(result["allocations"]),
                                        "approved": sum(item["status"] == "Approved" for item in result["requestResults"]),
                                        "rejected": sum(item["status"] == "Rejected" for item in result["requestResults"])}
        print(json.dumps(report, indent=2))
        return 0
    except (DatabaseConfigurationError, DatabaseBusy, PersistenceError, EngineIntegrationError, BackendExecutableError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print("Database operation failed. No partial seed/results published; inspect connectivity/migrations. A completed seed remains pending if engine execution failed.", file=sys.stderr)
        return 1
    finally:
        if database is not None:
            database.dispose()


if __name__ == "__main__":
    sys.exit(main())
