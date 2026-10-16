"""Add fictional equipment to a development database without overwriting inventory."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sqlalchemy.exc import SQLAlchemyError
from web.equipment_service import EquipmentError
from web.persistence.database import Database, DatabaseConfigurationError
from web.persistence.equipment_demo import seed_equipment_demo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--administrator', required=True, type=int, help='Existing authorized administration account ID in a fictional development database.')
    parser.add_argument('--seed', type=int, default=44)
    parser.add_argument('--size', choices=['moderate','large'], default='moderate')
    parser.add_argument('--confirm-development-database', action='store_true', required=True,
                        help='Explicitly acknowledge that DATABASE_URL selects a fictional development database, not production.')
    args = parser.parse_args()
    database = None
    try:
        database = Database()
        print(json.dumps(seed_equipment_demo(database, args.administrator, args.seed, args.size), indent=2))
        return 0
    except (EquipmentError, PermissionError, DatabaseConfigurationError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print('Database seed failed; no partial inventory committed. Check migrations and connectivity.', file=sys.stderr)
        return 1
    finally:
        if database:
            database.dispose()


if __name__ == '__main__':
    sys.exit(main())
