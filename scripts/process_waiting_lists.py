"""Recheck consented/pre-approved queues, including expiry, using current PostgreSQL data."""

import argparse
import logging
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from web.engine_gateway import EngineGateway
from web.persistence.database import Database
from web.waiting_list_service import WaitingListService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind', choices=['room', 'equipment'])
    args = parser.parse_args()
    database = Database()
    try:
        WaitingListService(database, EngineGateway(ROOT)).refresh_all(args.kind)
    finally:
        database.dispose()
    print('Waiting lists rechecked. No unapproved request was reserved.')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
