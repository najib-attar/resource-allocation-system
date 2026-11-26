"""Inspect or serve the existing İTÜ profile without seeding or migrating it."""

import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.setup_local_demo import connection_url, prepare_settings, verify_itu_owner
from web.backend_executable import BackendExecutableError, resolve_backend_executable
from web.persistence.database import Database

PROFILE = "itu-bbf-fall-2026"


def profile_settings(directory):
    settings_path = directory / "settings.json"
    marker = directory / "postgres-data" / "local-demo-owner"
    if (directory.name != PROFILE or not settings_path.is_file() or not marker.is_file()
            or marker.parent.resolve().parent != directory):
        raise ValueError("Supply the existing initialized İTÜ demo directory.")
    settings = prepare_settings(settings_path, dataset="itu", port=55546, allow_create=False)
    if not settings["seeded"] or marker.read_text(encoding="utf-8") != settings["profileId"]:
        raise ValueError("The settings and PostgreSQL owner marker do not match.")
    return settings_path, settings


def inspect_database(database, settings_path, settings):
    verify_itu_owner(database, settings_path, settings)
    with database.transaction(read_only=True) as session:
        instance = session.execute(text("SELECT current_database(), inet_server_port()")).one()
        if instance != ("ras_itu_demo", 55546):
            raise ValueError("The PostgreSQL listener does not match the owned İTÜ profile.")
        revisions = frozenset(session.scalars(text("SELECT version_num FROM alembic_version")))
    return revisions


def required_revisions():
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    return frozenset(ScriptDirectory.from_config(config).get_heads())


@contextmanager
def serving_lock(directory):
    with (directory / "launcher.lock").open("a+b") as lock:
        try:
            if os.name == "nt":
                import msvcrt
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError("Close the other launcher for this demo before serving.") from None
        yield


@contextmanager
def existing_postgres(directory, pg_bin):
    if pg_bin is None:
        yield
        return
    program = pg_bin / ("pg_ctl.exe" if os.name == "nt" else "pg_ctl")
    data = directory / "postgres-data"
    command = [str(program), "-D", str(data)]
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("PG")}

    def server_identity():
        try:
            pid, path, started_at, port, *_ = (data / "postmaster.pid").read_text(encoding="utf-8").splitlines()
            if Path(path).resolve() == data and port == "55546" and int(pid) > 0 and int(started_at) > 0:
                return pid, started_at
        except (OSError, ValueError):
            pass
        return None

    status = subprocess.run([*command, "status"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            env=environment, timeout=15, check=False)
    if status.returncode not in (0, 3):
        raise ValueError("Cannot verify the existing PostgreSQL server state.")
    owned = None
    if status.returncode == 3:
        with (directory / "postgres.log").open("ab") as log:
            subprocess.run([*command, "-l", str(directory / "postgres.log"), "-o", "-p 55546 -h 127.0.0.1",
                            "-w", "-t", "20", "start"], stdout=log, stderr=log, env=environment, timeout=25, check=True)
        owned = server_identity()
        if owned is None:
            raise ValueError("Could not verify the started PostgreSQL process. Check the existing server locally.")
    try:
        yield
    finally:
        if owned is not None and server_identity() == owned:
            subprocess.run([*command, "-m", "fast", "-w", "-t", "20", "stop"], env=environment, timeout=25, check=True)


def serve(database, settings, port):
    backend = resolve_backend_executable(ROOT, os.environ.get("RESOURCE_ALLOCATION_BACKEND"))
    os.environ.update(RESOURCE_ALLOCATION_BACKEND=str(backend.path),
                      RESOURCE_ALLOCATION_TIMEZONE="Europe/Istanbul", FLASK_DEBUG="0")
    from web.app import app
    from werkzeug.serving import make_server

    app.config.update(DATABASE_URL=database.url, SECRET_KEY=settings["sessionSecret"], DEBUG=False,
                      SESSION_COOKIE_SECURE=False, LOCAL_DEMO_DATASET="itu")
    with make_server("127.0.0.1", port, app, threaded=True) as server:
        print(f"İTÜ demo ready at http://127.0.0.1:{server.server_port}. CDMCS optimization remains disabled.", flush=True)
        server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--serve", action="store_true", help="Use the regular scheduler after schema verification.")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--postgres-bin", type=Path, help="With --serve, start the existing owned cluster if stopped.")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or (args.postgres_bin is not None and not args.serve):
        parser.error("Use a valid web port and supply --postgres-bin only with --serve.")
    directory = args.state_dir.resolve()
    database = None
    try:
        settings_path, settings = profile_settings(directory)
        database = Database(connection_url(settings))
        if args.serve:
            with serving_lock(directory), existing_postgres(directory, args.postgres_bin):
                if inspect_database(database, settings_path, settings) != required_revisions():
                    raise ValueError("The profile needs a separately approved migration before this checkout can serve it.")
                serve(database, settings, args.port)
        else:
            revisions = inspect_database(database, settings_path, settings)
            print(f"Verified owned İTÜ profile on PostgreSQL port 55546, schema {', '.join(sorted(revisions))}.")
    except KeyboardInterrupt:
        return 0
    except (SQLAlchemyError, subprocess.SubprocessError, OSError):
        print("Cannot access the existing profile or PostgreSQL listener. Check its local settings and server status.", file=sys.stderr)
        return 1
    except (ValueError, BackendExecutableError) as error:
        print(error, file=sys.stderr)
        return 1
    finally:
        if database is not None:
            database.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
