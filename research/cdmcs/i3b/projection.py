"""Minimize calendar facts into the shared immutable DTO, without database access."""

from dataclasses import dataclass, field
import uuid
from zoneinfo import ZoneInfo

from research.cdmcs.i3a.snapshot import Commitment, Interval, Participant, Snapshot, integer


class ProjectionError(ValueError):
    """Static codes/messages only: never attach SQL parameters or calendar payloads."""

    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class UnsupportedProjection(ProjectionError):
    pass


@dataclass(frozen=True, repr=False)
class CalendarProjection:
    _snapshot: Snapshot = field(repr=False)
    calendar_revision: int

    def __repr__(self):
        return "CalendarProjection(read_only=True; private calendar withheld)"

    def summary(self):
        """Safe metadata only; not a free/busy endpoint or an authorization grant."""
        return {"projection_version": 1, "read_only": True,
                "calendar_revision": self.calendar_revision, "engine_execution_enabled": False}

    def internal_snapshot(self):
        """Restricted server-internal facts. Never log/export/send these to a client."""
        return self._snapshot


def project_facts(facts, revision, zone_name):
    """Accept the existing calendar_snapshot's facts, not titles or ORM entities."""
    try:
        allowed = {"protocolVersion", "operation", "runId", "action", "organizerId", "professorIds", "invitedIds",
                   "durationMinutes", "horizon", "published", "busy", "unresolvedIds", "preferredStart", "proposed", "limit"}
        if (not isinstance(facts, dict) or set(facts) - allowed or facts.get("operation") != "appointment"
                or type(facts.get("protocolVersion")) is not int or facts["protocolVersion"] != 1):
            raise ValueError()
        ZoneInfo(zone_name)
        integer(revision, 0, 2**63 - 1, "calendar revision")
        organizer = facts["organizerId"]
        required = tuple(facts["professorIds"])
        optional = tuple(facts["invitedIds"])
        people = (organizer, *required, *optional)
        if not required or len(required) > 100 or len(optional) > 100 or len(set(people)) != len(people):
            raise ValueError()
        for person in people:
            integer(person, 1, 2147483647, "participant")
        aliases = {person: "person-" + uuid.uuid4().hex for person in people}

        def interval(start, end):
            integer(start, 0, 4102444800, "start")
            integer(end, 0, 4102444800, "end")
            if start >= end or start % 60 or end % 60:
                raise ValueError()
            return Interval(start, end)

        horizon = interval(facts["horizon"]["start"], facts["horizon"]["end"])
        duration = integer(facts["durationMinutes"], 1, 1440, "duration")
        if horizon.end - horizon.start > 32 * 86400 or duration * 60 > horizon.end - horizon.start:
            raise ValueError()
        if len(facts["busy"]) > 10000 or len(facts["published"]) > 100000:
            raise ValueError()
        published = {person: [] for person in people}
        for row in facts["published"]:
            if row["userId"] not in required:
                raise ValueError()
            published[row["userId"]].append(interval(row["start"], row["end"]))
        unresolved = set(facts["unresolvedIds"])
        if not unresolved <= set(people):
            raise ValueError()
        participants = []
        for person in people:
            if len(published[person]) > 1024:
                raise ValueError()
            participants.append(Participant(id=aliases[person], required=person not in optional,
                published_required=person in required, calendar_state="unresolved" if person in unresolved else "known",
                published=tuple(published[person]), preference=None, role_label=""))
        commitments = []
        for index, row in enumerate(facts["busy"]):
            if row["userId"] not in aliases:
                raise ValueError()
            commitments.append(Commitment(f"busy-{index}", interval(row["start"], row["end"]),
                                          (aliases[row["userId"]],), ()))
        provenance = (("source", "authorized application calendar projection"),
                      ("calendar_revision", str(revision)), ("preferences", "unavailable; no costs invented"),
                      ("commitments", "protected per-person busy facts; no relocation identity"),
                      ("read_strategy", "PostgreSQL repeatable read, read only; ORM autoflush disabled"))
        preferred = facts.get("preferredStart")
        if preferred is not None:
            integer(preferred, 0, 4102444800, "preferred start")
            if preferred % 60:
                raise ValueError()
        mode, starts = "production_grid", ()
        if facts.get("action") == "validate":
            proposed = interval(facts["proposed"]["start"], facts["proposed"]["end"])
            if proposed.end - proposed.start != duration * 60 or not horizon.start <= proposed.start < proposed.end <= horizon.end:
                raise ValueError()
            mode, starts = "explicit", (proposed.start,)
        elif facts.get("action") != "recommend":
            raise ValueError()
        snapshot = Snapshot(id="projection-" + uuid.uuid4().hex, zone=zone_name, anchor=horizon.start,
            horizon=horizon, duration=duration, organizer=aliases[organizer], participants=tuple(participants),
            commitments=tuple(commitments), resources=(), candidate_mode=mode, grid_anchor=aliases[required[0]],
            explicit_starts=starts, preferred_start=preferred, provenance=provenance, unsupported=(),
            origin="authorized_calendar")
        return CalendarProjection(snapshot, revision)
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ProjectionError("INVALID_CALENDAR_FACTS", "Calendar facts are incomplete, unsupported or out of bounds.") from None
