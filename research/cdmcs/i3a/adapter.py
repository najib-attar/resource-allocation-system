"""One fixed-calendar normalization; serializers do not make scheduling decisions."""

from dataclasses import dataclass
from datetime import datetime
import hashlib
from zoneinfo import ZoneInfo

from .snapshot import Interval, Snapshot, SnapshotError


class UnsupportedComparison(ValueError):
    pass


@dataclass(frozen=True)
class Normalized:
    snapshot: Snapshot
    identifiers: tuple
    published: tuple
    busy: tuple
    candidates: tuple
    prefixes: tuple
    days: tuple
    unsupported: tuple


def merged(intervals):
    result = []
    for item in sorted(intervals, key=lambda row: (row.start, row.end)):
        if result and item.start <= result[-1].end:
            result[-1] = Interval(result[-1].start, max(item.end, result[-1].end))
        else:
            result.append(item)
    return tuple(result)


def normalize(snapshot):
    if not isinstance(snapshot, Snapshot):
        raise SnapshotError("Use parse_snapshot/load_snapshot before normalization")
    people = tuple(sorted(snapshot.participants, key=lambda p: p.id))
    required = [p for p in people if p.required]
    reasons = list(snapshot.unsupported)
    if snapshot.origin != "synthetic":
        reasons.append("Database-derived snapshots are not approved for engine execution in I3b")
    if any(p.preference is None for p in required):
        reasons.append("Prepared participant cost preferences are unavailable")
    if snapshot.resources:
        reasons.append("Production appointment protocol cannot enforce shared exclusive resources")
    for person in required:
        if person.calendar_state != "known":
            reasons.append(f"Mandatory calendar is {person.calendar_state}: {person.id}")
        if person.published_required != (person.id != snapshot.organizer):
            reasons.append(f"Publication policy is not representable in production appointment protocol: {person.id}")
    order = [snapshot.organizer, snapshot.grid_anchor]
    order.extend(sorted(p.id for p in people if p.id not in order))
    identifiers = tuple((name, i + 1) for i, name in enumerate(order))
    published = tuple((p.id, merged(p.published)) for p in people)
    if sum(len(windows) for name, windows in published if name != snapshot.organizer
           and any(p.id == name and p.required for p in people)) > 100000:
        reasons.append("Production published interval limit exceeded")
    by_person = {person.id: [] for person in people}
    for event in snapshot.commitments:
        start, end = max(snapshot.anchor, event.interval.start), min(snapshot.horizon.end, event.interval.end)
        if start < end:
            for name in event.people:
                by_person[name].append(Interval(start, end))
    busy = tuple((person.id, merged(by_person[person.id])) for person in people)
    if snapshot.candidate_mode == "production_grid":
        candidates = []
        for window in dict(published)[snapshot.grid_anchor]:
            first = max(window.start, snapshot.horizon.start)
            first += (900 - (first - window.start) % 900) % 900
            last = min(window.end, snapshot.horizon.end) - snapshot.duration * 60
            candidates.extend(range(first, last + 1, 900))
        if len(candidates) > 10000:
            raise SnapshotError("Candidate budget exceeded")
        candidates = tuple(candidates)
    else:
        candidates = tuple(sorted(snapshot.explicit_starts))
    horizon = (snapshot.horizon.end - snapshot.anchor) // 60
    if len(required) * (horizon + 1) > 3000000:
        reasons.append("I1 total preference-prefix entry limit exceeded")
    if sum(len(windows) for name, windows in busy if name in {p.id for p in required}) > 10000:
        reasons.append("I1 normalized baseline meeting limit exceeded")
    days, prefixes = (), []
    if not reasons:
        zone = ZoneInfo(snapshot.zone)
        days = tuple(datetime.fromtimestamp(snapshot.anchor + i * 60, zone).date().toordinal()
                     for i in range(horizon + 1))
        if any(a > b for a, b in zip(days, days[1:])):
            reasons.append("I1 cannot represent decreasing local civil dates")
        for person in required:
            preference = person.preference
            rates = [preference.base_rate] * horizon
            for interval, rate in preference.bands:
                start, end = (interval.start - snapshot.anchor) // 60, (interval.end - snapshot.anchor) // 60
                rates[start:end] = [rate] * (end - start)
            prefix = [0]
            for rate in rates:
                prefix.append(prefix[-1] + rate)
            if prefix[-1] > 10**12:
                reasons.append(f"I1 prefix cost bound exceeded: {person.id}")
            prefixes.append((person.id, tuple(prefix)))
    return Normalized(snapshot, identifiers, published, tuple(busy), candidates, tuple(prefixes), days, tuple(reasons))


def _supported(normalized):
    if normalized.unsupported:
        raise UnsupportedComparison("; ".join(normalized.unsupported))


def production_request(normalized, candidate=None):
    _supported(normalized)
    snapshot = normalized.snapshot
    ids = dict(normalized.identifiers)
    professors = sorted(ids[p.id] for p in snapshot.participants if p.required and p.id != snapshot.organizer)
    action = "recommend" if candidate is None else "validate"
    if candidate is not None and candidate not in normalized.candidates:
        raise SnapshotError("Validation candidate is not in the declared comparison universe")
    request = {"protocolVersion": 1, "operation": "appointment", "runId":
               hashlib.sha256(snapshot.id.encode()).hexdigest()[:24] + f":{action}:{candidate}",
               "action": action, "organizerId": ids[snapshot.organizer], "professorIds": professors,
               "invitedIds": sorted(ids[p.id] for p in snapshot.participants if not p.required),
               "unresolvedIds": sorted(ids[p.id] for p in snapshot.participants if p.calendar_state != "known"),
               "durationMinutes": snapshot.duration,
               "horizon": {"start": snapshot.horizon.start, "end": snapshot.horizon.end}, "limit": 100,
               "published": [{"userId": ids[name], "start": w.start, "end": w.end}
                             for name, windows in normalized.published for w in windows
                             if ids[name] in professors],
               "busy": [{"userId": ids[name], "start": w.start, "end": w.end}
                        for name, windows in normalized.busy for w in windows]}
    if candidate is not None:
        request["proposed"] = {"start": candidate, "end": candidate + snapshot.duration * 60}
    if snapshot.preferred_start is not None:
        request["preferredStart"] = snapshot.preferred_start
    return request


def cdmcs_request(normalized, candidates=None):
    _supported(normalized)
    snapshot = normalized.snapshot
    starts = normalized.candidates if candidates is None else tuple(candidates)
    if not starts or len(set(starts)) != len(starts) or any(t not in normalized.candidates for t in starts):
        raise SnapshotError("CDMCS needs nonempty distinct candidates from the declared universe")
    required = sorted((p for p in snapshot.participants if p.required), key=lambda p: p.id)
    publication, prefixes = dict(normalized.published), dict(normalized.prefixes)
    horizon = (snapshot.horizon.end - snapshot.anchor) // 60
    profiles = {}
    for person in required:
        windows = publication[person.id] if person.published_required else (Interval(snapshot.anchor, snapshot.horizon.end),)
        windows = [(max(w.start, snapshot.anchor), min(w.end, snapshot.horizon.end)) for w in windows]
        profiles[person.id] = {"rate_prefix": list(prefixes[person.id]),
                               "published": [[(a - snapshot.anchor) // 60, (b - snapshot.anchor) // 60]
                                             for a, b in windows if a < b], "exceptions": [],
                               "preferred_break": person.preference.preferred_break,
                               "gap_weight": person.preference.gap_weight,
                               "nearby_limit": person.preference.nearby_limit, "exception_fee": 0}
    existing = [{"id": f"busy:{i}:{j}", "start": (w.start - snapshot.anchor) // 60,
                 "duration": (w.end - w.start) // 60, "people": [name], "resources": [], "flexible": False}
                for i, (name, windows) in enumerate(normalized.busy) if name in profiles
                for j, w in enumerate(windows)]
    return {"operation": "cdmcs_schedule_v1", "horizon_minutes": horizon, "duration": snapshot.duration,
            "candidate_starts": [(t - snapshot.anchor) // 60 for t in starts], "replacement_starts": [],
            "required_people": [p.id for p in required], "required_resources": [], "existing": existing,
            "profiles": profiles, "local_day_index": list(normalized.days), "unresolved_people": [],
            "move_fixed_cost": 0, "move_participant_cost": 0, "delay_per_day": 0, "limit": 100}
