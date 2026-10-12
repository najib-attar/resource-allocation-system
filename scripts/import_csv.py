"""Validate/import existing inputs without overwriting files or populated databases."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.exc import SQLAlchemyError
from web.persistence.database import Database, DatabaseConfigurationError
from web.persistence.importer import ImportValidationError, import_csv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parent.parent / "data")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    database = None
    try:
        database = Database()
        print(json.dumps(import_csv(database, args.data_dir, args.dry_run), ensure_ascii=False, indent=2))
    except (ImportValidationError, DatabaseConfigurationError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print("Database import failed and was rolled back. Check connectivity, migrations and integrity constraints.", file=sys.stderr)
        return 1
    finally:
        if database is not None:
            database.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
