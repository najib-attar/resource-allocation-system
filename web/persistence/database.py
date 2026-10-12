"""Connection configuration and short-lived, explicit SQLAlchemy transactions."""

import math
import os
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, DBAPIError
from sqlalchemy.orm import sessionmaker


class DatabaseConfigurationError(RuntimeError):
    pass


class DatabaseBusy(RuntimeError):
    pass


def database_url(value=None):
    value = value if value is not None else os.environ.get("DATABASE_URL")
    if not value:
        raise DatabaseConfigurationError("DATABASE_URL is required. Configure PostgreSQL and run Alembic migrations; CSV fallback is disabled.")
    try:
        url = make_url(value)
    except (ArgumentError, ValueError) as error:
        # URL parsing has no database side effects; never echo a credential-bearing URL.
        raise DatabaseConfigurationError("DATABASE_URL is not a valid PostgreSQL URL.") from error
    if url.drivername not in {"postgresql", "postgresql+psycopg"}:
        raise DatabaseConfigurationError("DATABASE_URL must use PostgreSQL with psycopg 3.")
    return url.set(drivername="postgresql+psycopg")


class Database:
    def __init__(self, url=None, lock_timeout=5):
        self.url = database_url(url)
        self.lock_timeout = float(lock_timeout)
        if not math.isfinite(self.lock_timeout) or self.lock_timeout <= 0:
            raise DatabaseConfigurationError("Database lock timeout must be finite and positive.")
        self.engine = create_engine(self.url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def transaction(self, read_only=False):
        try:
            with self.sessions.begin() as session:
                if read_only:
                    session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
                else:
                    session.execute(text("SELECT set_config('lock_timeout', :timeout, true)"),
                                    {"timeout": f"{max(1, int(self.lock_timeout * 1000))}ms"})
                yield session
        except DBAPIError as error:
            if getattr(error.orig, "sqlstate", None) == "55P03":
                raise DatabaseBusy("Application data is busy. Retry shortly; no partial changes were saved.") from error
            raise

    def dispose(self):
        self.engine.dispose()
