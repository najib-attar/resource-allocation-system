"""Synthetic persisted runs on both sides of one Istanbul calendar date."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from web.persistence.models import AllocationRun


def create_history(database):
    # 21:00 UTC on January 7 is midnight on January 8 in Istanbul.
    first = datetime(2030, 1, 7, 21, tzinfo=timezone.utc)
    end = first + timedelta(days=1)
    with database.transaction() as session:
        def insert(instant):
            run = AllocationRun(strategy='greedy', input_revision=0, status='failed',
                snapshot={'requests': []}, correlation_id=uuid4().hex, created_at=instant)
            session.add(run)
            session.flush()
            return run.id

        insert(first - timedelta(microseconds=1))
        matching = [insert(first)]
        matching.extend(insert(first + timedelta(hours=12)) for _ in range(24))
        matching.append(insert(end - timedelta(microseconds=1)))
        insert(end)
        return list(reversed(matching))
