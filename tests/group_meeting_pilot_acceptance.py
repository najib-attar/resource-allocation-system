"""Run the browser pilot, verify committed PostgreSQL records, and restart Flask."""

import argparse
from datetime import datetime, timedelta
import json
import multiprocessing
from pathlib import Path
import secrets
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread

from sqlalchemy import select
from werkzeug.serving import make_server

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_cdmcs_rehearsal import PEOPLE, rehearsal_server
from web.cdmcs_rehearsal import FlexibleMeeting, RehearsalFixture, register_rehearsal
from web.group_meeting_routes import register_group_meetings
from web.persistence.models import (
    GroupMeeting, GroupMeetingCommitment, GroupMeetingReschedule, RoomReservation, StudentRoomRequest,
)


def restarted_server(args, database_url, info, ready):
    from web.app import app, get_repository
    app.config.update(DATABASE_URL=database_url, SECRET_KEY=secrets.token_hex(32), DEBUG=False,
                      SESSION_COOKIE_SECURE=False, LOCAL_DEMO_DATASET="cdmcs-rehearsal")
    db = get_repository().database
    start, end = (datetime.fromisoformat(info[key]) for key in ("starts", "ends"))
    flexible = FlexibleMeeting(people=(1, 4), start=start + timedelta(hours=9), end=start + timedelta(hours=12),
        replacements=tuple(start + timedelta(hours=hour) for hour in (11, 12, 33, 34)))
    fixture = RehearsalFixture(db, args.engine.resolve(), args.engine_sha256.lower(),
        tuple(uid for uid, *_ in PEOPLE), start, end, (flexible,))
    register_rehearsal(app, fixture)
    register_group_meetings(app, fixture)
    with make_server("127.0.0.1", 0, app, threaded=True) as server:
        ready.send(server.server_port)
        ready.close()
        server.serve_forever()


def verify_commits(database):
    with database.transaction(read_only=True) as db:
        rows = {meeting.purpose: meeting for meeting in db.scalars(select(GroupMeeting))}
        expected = {
            "Pilot browser online group": ("Confirmed", 2, {1, 3, 4, 6}),
            "Pilot browser flexible original": ("Confirmed", 2, {1, 4}),
            "Pilot browser declined replacement": ("Declined", 1, set()),
            "Pilot browser accepted move": ("Confirmed", 1, {1, 4}),
            "Pilot browser physical group": ("Confirmed", 1, {1, 3}),
            "Pilot browser instructor room group": ("Confirmed", 2, {3, 5}),
            "Pilot browser one-to-many": ("Confirmed", 1, {1, 3, 4}),
            "Pilot browser many-to-one": ("Confirmed", 1, {1, 4, 5}),
        }
        assert set(rows) == set(expected)
        for purpose, (status, revision, members) in expected.items():
            meeting = rows[purpose]
            assert (meeting.status, meeting.revision) == (status, revision)
            commitments = list(db.scalars(select(GroupMeetingCommitment)
                .where(GroupMeetingCommitment.meeting_id == meeting.id)))
            assert {item.user_id for item in commitments} == members
            assert all((item.start_at, item.end_at) == (meeting.start_at, meeting.end_at) for item in commitments)
        online = rows["Pilot browser online group"]
        replacement = {item.status: item for item in db.scalars(select(GroupMeetingReschedule)
            .where(GroupMeetingReschedule.meeting_id == online.id))}
        assert set(replacement) == {"Declined", "Applied"}
        assert replacement["Applied"].start_at == online.start_at != replacement["Applied"].original_start_at
        physical = rows["Pilot browser instructor room group"]
        room = db.get(StudentRoomRequest, physical.room_request_id)
        assert room.organizer_id == 3 and room.approved_by == 6 and room.group_participant_ids == [3, 5]
        hold = db.scalars(select(RoomReservation).where(RoomReservation.request_id == room.id)).one()
        assert (hold.start_at, hold.end_at) == (physical.start_at, physical.end_at)
        physical_change = db.scalars(select(GroupMeetingReschedule)
            .where(GroupMeetingReschedule.meeting_id == physical.id)).one()
        assert physical_change.status == "Applied" and physical_change.room_request_id == room.id
        old_room = db.get(StudentRoomRequest, physical_change.original_room_request_id)
        assert old_room.status == "Cancelled"
        assert db.scalar(select(RoomReservation).where(RoomReservation.request_id == old_room.id)) is None
        print("Verified eight meeting rows, eighteen commitments, three replacement outcomes and atomic room release.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres-bin", required=True, type=Path)
    parser.add_argument("--engine", required=True, type=Path)
    parser.add_argument("--engine-sha256", required=True)
    parser.add_argument("--backend", type=Path)
    parser.add_argument("--course-archive", type=Path)
    parser.add_argument("--screenshots", required=True, type=Path)
    args = parser.parse_args()
    args.port = args.postgres_port = 0
    browser = ["node", str(ROOT / "tests/group_meeting_pilot_browser.cjs")]
    with TemporaryDirectory(prefix="cdmcs-final-browser-") as profile:
        args.output = Path(profile)
        with rehearsal_server(args) as (server, logins):
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                subprocess.run([*browser, str(logins), str(args.screenshots)], cwd=ROOT, check=True, timeout=300)
            finally:
                server.shutdown()
                thread.join(15)
            from web.app import get_repository
            database = get_repository().database
            verify_commits(database)
            info = json.loads(logins.read_text(encoding="utf-8"))
            context = multiprocessing.get_context("spawn")
            read, write = context.Pipe(duplex=False)
            child = context.Process(target=restarted_server, args=(args, database.url, info, write))
            child.start()
            write.close()
            try:
                if not read.poll(20):
                    raise RuntimeError("The restarted Flask process did not become ready.")
                info["url"] = f"http://127.0.0.1:{read.recv()}"
                logins.write_text(json.dumps(info), encoding="utf-8")
                subprocess.run([*browser, str(logins), str(args.screenshots), "--verify-restart"],
                               cwd=ROOT, check=True, timeout=90)
                verify_commits(database)
            finally:
                read.close()
                if child.is_alive():
                    child.terminate()
                child.join(15)


if __name__ == "__main__":
    main()
