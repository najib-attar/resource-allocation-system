"""Provision an existing university identity; never print or store plaintext passwords."""

import argparse
from getpass import getpass
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.exc import SQLAlchemyError
from web.account_service import AccountService
from web.persistence.database import Database, DatabaseConfigurationError
from web.persistence.repository import PersistenceError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--administrator", action="store_true", help="Explicitly grant technical dashboard administration.")
    parser.add_argument("--reset-password", action="store_true", help="Explicitly replace an existing account and revoke sessions.")
    args = parser.parse_args()
    password = getpass("Password (12-256 characters): ")
    if password != getpass("Confirm password: "):
        print("Passwords differ.", file=sys.stderr)
        return 1
    database = None
    try:
        database = Database()
        AccountService(database).provision(args.user_id, args.username, password,
                                           administrator=args.administrator, reset=args.reset_password)
        print("Account provisioned for the selected university identity.")
        return 0
    except (PersistenceError, DatabaseConfigurationError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print("Account operation failed; inspect database connectivity, migration and unique usernames.", file=sys.stderr)
        return 1
    finally:
        if database is not None:
            database.dispose()


if __name__ == "__main__":
    sys.exit(main())
