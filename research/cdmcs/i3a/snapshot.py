"""Immutable synthetic calendar facts, not application authorization or scheduling."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class SnapshotError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise SnapshotError(message)


def integer(value, low, high, label):
    require(type(value) is int and low <= value <= high, f"Invalid {label}")
    return value


def identifier(value):
    require(isinstance(value, str) and 0 < len(value.encode("utf-8")) <= 256,
            "Identifier must contain 1-256 UTF-8 bytes")
    return value


def sequence(value, limit, label):
    require(isinstance(value, list) and len(value) <= limit, f"Invalid/bounded {label} list required")
    return value


def mapping(value, allowed, required=()):
    require(isinstance(value, dict), "Object required")
    require(set(value) <= set(allowed) and set(required) <= set(value), "Unknown or missing fields")
    return value


def instant(value, zone):
    require(isinstance(value, str) and "T" in value and len(value) <= 64, "Explicit ISO date and time required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(not parsed.second and not parsed.microsecond, "Times must be exact minutes; no rounding")
        if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
            wall = parsed.replace(tzinfo=None)
            choices = {wall.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
                       for fold in (0, 1)
                       if wall.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
                       .astimezone(zone).replace(tzinfo=None) == wall}
            require(len(choices) == 1, "Ambiguous or nonexistent local time")
            resolved = choices.pop()
            if parsed.tzinfo is not None:
                require(parsed.astimezone(timezone.utc) == resolved, "Offset disagrees with IANA timezone")
            parsed = resolved
        stamp = int(parsed.timestamp())
        require(0 <= stamp <= 4102444800 and stamp % 60 == 0, "Minute instant outside 1970-2100")
        return stamp
    except (ValueError, OverflowError, OSError) as error:
        raise SnapshotError(str(error)) from error


@dataclass(frozen=True)
class Interval:
    start: int
    end: int


@dataclass(frozen=True)
class Preference:
    base_rate: int
    bands: tuple
    preferred_break: int
    gap_weight: int
    nearby_limit: int
    source: str


@dataclass(frozen=True)
class Participant:
    id: str
    required: bool
    published_required: bool
    calendar_state: str
    published: tuple
    preference: Preference
    role_label: str


@dataclass(frozen=True)
class Commitment:
    id: str
    interval: Interval
    people: tuple
    resources: tuple


@dataclass(frozen=True)
class Snapshot:
    id: str
    zone: str
    anchor: int
    horizon: Interval
    duration: int
    organizer: str
    participants: tuple
    commitments: tuple
    resources: tuple
    candidate_mode: str
    grid_anchor: str
    explicit_starts: tuple
    preferred_start: int | None
    provenance: tuple
    unsupported: tuple


def unique_ids(values, label):
    result = tuple(identifier(value) for value in values)
    require(len(set(result)) == len(result), f"Duplicate {label}")
    return result


def parse_snapshot(value):
    root_fields = ("snapshot_version", "snapshot_id", "synthetic", "timezone", "utc_anchor", "horizon",
                   "duration_minutes", "organizer", "participants", "commitments", "required_resources",
                   "candidates", "provenance", "preferred_start", "unsupported_information")
    mapping(value, root_fields, root_fields[:-2])
    require(type(value["snapshot_version"]) is int and value["snapshot_version"] == 1, "Snapshot version must be 1")
    require(value["synthetic"] is True, "Only explicitly synthetic snapshots are permitted")
    require(isinstance(value["timezone"], str), "Explicit IANA timezone required")
    try:
        zone = ZoneInfo(value["timezone"])
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise SnapshotError("Unknown IANA timezone") from error

    def interval(raw):
        mapping(raw, ("start", "end"), ("start", "end"))
        result = Interval(instant(raw["start"], zone), instant(raw["end"], zone))
        require(result.start < result.end, "Interval must have start before end")
        return result

    anchor = instant(value["utc_anchor"], ZoneInfo("UTC"))
    raw_anchor = datetime.fromisoformat(value["utc_anchor"].replace("Z", "+00:00"))
    require(raw_anchor.tzinfo is not None and raw_anchor.utcoffset() == timedelta(0), "Explicit UTC anchor required")
    horizon = interval(value["horizon"])
    require(anchor <= horizon.start < horizon.end <= anchor + 32 * 86400, "Anchor/horizon must fit within 32 days")
    duration = integer(value["duration_minutes"], 1, 1440, "duration")
    require(duration * 60 <= horizon.end - horizon.start, "Duration exceeds horizon")
    participants = []
    for raw in sequence(value["participants"], 201, "participants"):
        mapping(raw, ("id", "required", "published_required", "calendar_state", "published", "preference", "role_label"),
                ("id", "required", "published_required", "calendar_state", "published", "preference"))
        require(type(raw["required"]) is bool and type(raw["published_required"]) is bool, "Boolean participant policies required")
        require(raw["calendar_state"] in ("known", "missing", "unresolved", "unsupported"), "Explicit calendar state required")
        preference = mapping(raw["preference"], ("base_rate", "rate_bands", "preferred_break", "gap_weight", "nearby_limit", "source"))
        bands = []
        for band in sequence(preference.get("rate_bands", []), 1024, "rate bands"):
            mapping(band, ("interval", "rate"), ("interval", "rate"))
            period = interval(band["interval"])
            require(anchor <= period.start < period.end <= horizon.end, "Rate band outside anchored horizon")
            bands.append((period, integer(band["rate"], 0, 10**8, "rate")))
        bands.sort(key=lambda item: item[0].start)
        require(all(a[0].end <= b[0].start for a, b in zip(bands, bands[1:])), "Overlapping preference bands")
        prepared = Preference(integer(preference.get("base_rate", 0), 0, 10**8, "base rate"), tuple(bands),
                              integer(preference.get("preferred_break", 0), 0, 1440, "preferred break"),
                              integer(preference.get("gap_weight", 0), 0, 100000, "gap weight"),
                              integer(preference.get("nearby_limit", 0), 0, 10080, "nearby limit"),
                              identifier(preference.get("source", "synthetic-neutral")))
        label = raw.get("role_label", "")
        require(isinstance(label, str) and len(label) <= 100, "Invalid descriptive role label")
        participants.append(Participant(identifier(raw["id"]), raw["required"], raw["published_required"],
                                        raw["calendar_state"], tuple(interval(item) for item in
                                        sequence(raw["published"], 1024, "published windows")), prepared, label))
    people = unique_ids([person.id for person in participants], "participants")
    organizer = identifier(value["organizer"])
    require(any(p.id == organizer and p.required for p in participants), "Organizer must be a required participant")
    require(sum(p.required for p in participants) <= 101 and sum(not p.required for p in participants) <= 100,
            "Production participant limits exceeded")
    commitments = []
    memberships = 0
    for raw in sequence(value["commitments"], 10000, "commitments"):
        mapping(raw, ("id", "interval", "people", "resources", "protected"),
                ("id", "interval", "people", "resources", "protected"))
        require(raw["protected"] is True, "I3a permits only protected fixed commitments")
        members = unique_ids(sequence(raw["people"], 201, "commitment people"), "commitment people")
        resources = unique_ids(sequence(raw["resources"], 256, "commitment resources"), "commitment resources")
        require(set(members) <= set(people), "Unknown commitment participant")
        require(members or resources, "Commitment requires a participant or resource")
        memberships += len(members) + len(resources)
        require(memberships <= 100000, "Commitment membership budget exceeded")
        commitments.append(Commitment(identifier(raw["id"]), interval(raw["interval"]), members, resources))
    unique_ids([item.id for item in commitments], "commitments")
    resources = unique_ids(sequence(value["required_resources"], 256, "resources"), "resources")
    candidates = mapping(value["candidates"], ("mode", "anchor_participant", "step_minutes", "starts"),
                         ("mode", "anchor_participant"))
    require(candidates["mode"] in ("production_grid", "explicit"), "Unknown candidate mode")
    grid_anchor = identifier(candidates["anchor_participant"])
    require(any(p.id == grid_anchor and p.required and p.published_required and p.id != organizer for p in participants),
            "Grid anchor must require published availability and differ from organizer")
    if candidates["mode"] == "production_grid":
        require(type(candidates.get("step_minutes")) is int and candidates["step_minutes"] == 15 and "starts" not in candidates,
                "Production grid has exactly 15-minute steps, not explicit starts")
        starts = ()
    else:
        require("step_minutes" not in candidates and "starts" in candidates, "Explicit candidates need starts only")
        starts = tuple(instant(item, zone) for item in sequence(candidates["starts"], 10000, "candidate starts"))
        require(len(set(starts)) == len(starts), "Duplicate candidate starts")
        require(all(horizon.start <= t and t + duration * 60 <= horizon.end for t in starts), "Candidate outside horizon")
    preferred = instant(value["preferred_start"], zone) if value.get("preferred_start") is not None else None
    provenance = value["provenance"]
    require(isinstance(provenance, dict) and 1 <= len(provenance) <= 30, "Explicit synthetic provenance required")
    require(all(isinstance(k, str) and isinstance(v, str) and 0 < len(k) <= 100 and len(v) <= 2000
                for k, v in provenance.items()), "Provenance must contain bounded strings")
    unsupported = tuple(identifier(item) for item in sequence(value.get("unsupported_information", []), 100, "unsupported information"))
    return Snapshot(identifier(value["snapshot_id"]), zone.key, anchor, horizon, duration, organizer,
                    tuple(participants), tuple(commitments), resources, candidates["mode"], grid_anchor,
                    starts, preferred, tuple(sorted(provenance.items())), unsupported)


def load_snapshot(raw):
    require(isinstance(raw, bytes) and len(raw) <= 16 * 1024 * 1024, "Snapshot exceeds 16 MiB")

    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "Duplicate JSON object key")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: require(False, "Nonfinite JSON number"))
        return parse_snapshot(value)
    except (ValueError, TypeError, KeyError, RecursionError, UnicodeError) as error:
        raise SnapshotError(str(error)) from error
