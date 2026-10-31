"""Pure synthetic preparation; no engine execution, persistence or authorization."""

from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta, timezone
import json
from zoneinfo import ZoneInfo

from research.cdmcs.i3a.adapter import _candidate_starts, cdmcs_request, merged, normalize
from research.cdmcs.i3a.snapshot import Commitment, Interval, Preference, Snapshot, instant
from .contract import (PreferenceError, PreferenceUnavailable, check, envelope, label,
                       parse_policy, parse_preference, provenance, record)


@dataclass(frozen=True, repr=False)
class DelayReference:
    """One civil-date reference for the full universe, never a chunk-local origin."""
    universe: tuple
    timezone: str
    earliest_day: int
    weight: int
    version: int = 1

    def check_candidates(self, starts):
        check(type(starts) is tuple and starts and all(type(t) is int for t in starts), "INVALID_CANDIDATES")
        check(len(set(starts)) == len(starts) and set(starts) <= set(self.universe), "INVALID_CANDIDATES")
        if self.weight and datetime.fromtimestamp(min(starts), ZoneInfo(self.timezone)).date().toordinal() != self.earliest_day:
            raise PreferenceUnavailable("GLOBAL_DELAY_REFERENCE")


@dataclass(frozen=True, repr=False)
class CompiledPreferences:
    _document: str
    delay_reference: DelayReference
    provenance: tuple

    def to_request(self):
        """Fresh existing-v1 request for the FULL candidate universe; not a batch API."""
        return json.loads(self._document)

    def __repr__(self):
        return "CompiledPreferences(synthetic_only=True; calendar and costs withheld)"


def _interval(value, timezone):
    record(value, ("start", "end"))
    timezone = ZoneInfo(timezone)
    result = Interval(instant(value["start"], timezone), instant(value["end"], timezone))
    check(result.start < result.end, "INVALID_CONTEXT_INTERVAL")
    return result


def _context(value, snapshot, required, candidates, padding):
    envelope(value, ("context_version", "synthetic", "state", "coverage", "complete_for",
                     "left_boundary", "right_boundary", "commitments", "provenance"), "context_version")
    check(value["state"] in ("complete", "missing", "unknown", "unsupported"), "INVALID_CONTEXT_STATE")
    if value["state"] != "complete":
        raise PreferenceUnavailable("COST_CONTEXT_" + value["state"].upper())
    coverage = _interval(value["coverage"], snapshot.zone)
    check(type(value["complete_for"]) is list and len(value["complete_for"]) <= 32, "CONTEXT_MEMBERSHIP")
    covered = tuple(label(p) for p in value["complete_for"])
    check(len(set(covered)) == len(covered) and set(covered) <= {p.id for p in snapshot.participants}, "CONTEXT_MEMBERSHIP")
    if not required <= set(covered):
        raise PreferenceUnavailable("MISSING_COST_CONTEXT")
    check(value["left_boundary"] in ("open", "calendar_start")
          and value["right_boundary"] in ("open", "calendar_end"), "INVALID_CONTEXT_BOUNDARY")
    source = provenance(value["provenance"])
    if coverage.start > snapshot.horizon.start or coverage.end < snapshot.horizon.end:
        raise PreferenceUnavailable("COST_CONTEXT_COVERAGE")
    # One extra minute includes neighbors exactly at the cutoff under half-open reads.
    if padding is not None and ((value["left_boundary"] == "open" and coverage.start > min(candidates) - (padding + 1) * 60)
                    or (value["right_boundary"] == "open"
                        and coverage.end < max(candidates) + snapshot.duration * 60 + (padding + 1) * 60)):
        raise PreferenceUnavailable("MISSING_NEIGHBOR_CONTEXT")
    if coverage.end - coverage.start > 32 * 86400 or len(required) * ((coverage.end - coverage.start) // 60 + 1) > 200000:
        raise PreferenceUnavailable("COST_CONTEXT_BUDGET")
    rows = value["commitments"]
    check(type(rows) is list and len(rows) <= 2000, "CONTEXT_MEETING_BUDGET")
    people = {p.id for p in snapshot.participants}
    events, ids, memberships = [], set(), 0
    for row in rows:
        record(row, ("id", "interval", "people", "resources", "protected"))
        check(row["protected"] is True, "PROTECTED_CALENDAR_REQUIRED")
        check(type(row["resources"]) is list, "INVALID_RESOURCES")
        if row["resources"]:
            raise PreferenceUnavailable("RESOURCE_SEMANTICS")
        check(type(row["people"]) is list and 0 < len(row["people"]) <= 32, "CONTEXT_MEMBERSHIP")
        members = tuple(sorted(label(p) for p in row["people"]))
        check(len(set(members)) == len(members) and set(members) <= people, "CONTEXT_MEMBERSHIP")
        memberships += len(members)
        check(memberships <= 10000, "CONTEXT_MEMBERSHIP_BUDGET")
        identity = label(row["id"])
        check(identity != "NEW" and identity not in ids, "INVALID_CONTEXT_ID")
        ids.add(identity)
        interval = _interval(row["interval"], snapshot.zone)
        if not coverage.start <= interval.start < interval.end <= coverage.end:
            raise PreferenceUnavailable("UNCLIPPED_EVENT_CONTEXT_REQUIRED")
        events.append(Commitment(identity, interval, members, ()))
    events = tuple(sorted(events, key=lambda e: (e.interval.start, e.id)))
    original = {e.id: e for e in snapshot.commitments if required.intersection(e.people)}
    supplied = {e.id: e for e in events}
    for identity, event in original.items():
        other = supplied.get(identity)
        if (other is None or other.interval != event.interval or set(other.people) != set(event.people)
                or event.resources):
            raise PreferenceUnavailable("INCONSISTENT_COST_CONTEXT")
    for event in events:
        if (required.intersection(event.people) and event.interval.start < snapshot.horizon.end
                and event.interval.end > snapshot.horizon.start and event.id not in original):
            raise PreferenceUnavailable("INCONSISTENT_COST_CONTEXT")
    # The v1 optimizer requires a conflict-free baseline. Do not merge real events:
    # merging touching meetings would erase the existing zero-gap objective term.
    for person in required:
        calendar = [e for e in events if person in e.people]
        if any(a.interval.end > b.interval.start for a, b in zip(calendar, calendar[1:])):
            raise PreferenceUnavailable("OVERLAPPING_COST_CONTEXT")
    return coverage, events, source


def _profile(spec, policy, coverage):
    zone = ZoneInfo(spec.timezone)
    first = datetime.fromtimestamp(coverage.start, zone).date()
    last = datetime.fromtimestamp(coverage.end - 60, zone).date()
    if spec.first > first or spec.last < last:
        raise PreferenceUnavailable("PREFERENCE_EFFECTIVE_COVERAGE")
    # Validate supplied endpoints, not boundaries erased by merging or introduced
    # by midnight splitting. Include an overnight window beginning the prior day.
    current = first - timedelta(days=1)
    while current <= last:
        for weekday, start, end in spec.source_windows:
            if current.isoweekday() != weekday or (current < first and end <= 1440):
                continue
            for minute in (start, end):
                wall = datetime.combine(current, time()) + timedelta(minutes=minute)
                # Recurring wall endpoints can lie outside the bounded cost
                # calendar; only scheduling instants need the epoch-range guard.
                choices = set()
                for fold in (0, 1):
                    utc = wall.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
                    if utc.astimezone(zone).replace(tzinfo=None) == wall:
                        choices.add(utc)
                if len(choices) != 1:
                    raise PreferenceUnavailable("AMBIGUOUS_OR_NONEXISTENT_PREFERENCE_WINDOW")
        current += timedelta(days=1)
    segments, total, previous, beginning = [], 0, None, coverage.start
    for stamp in range(coverage.start, coverage.end, 60):
        local = datetime.fromtimestamp(stamp, zone)
        weekday, minute = local.isoweekday(), local.hour * 60 + local.minute
        if spec.weekdays and weekday not in spec.weekdays:
            rate = policy.outside_day_rate
        elif spec.windows and not any(day == weekday and start <= minute < end for day, start, end in spec.windows):
            rate = policy.outside_window_rate
        else:
            rate = policy.preferred_rate
        total += rate
        if total > 10**12:
            raise PreferenceUnavailable("PREFIX_COST_BOUND")
        if previous is not None and rate != previous:
            if previous != policy.outside_day_rate:
                segments.append((Interval(beginning, stamp), previous))
            beginning = stamp
        previous = rate
    if previous != policy.outside_day_rate:
        segments.append((Interval(beginning, coverage.end), previous))
    if len(segments) > 1024:
        raise PreferenceUnavailable("RATE_BAND_BUDGET")
    indifferent = spec.desired_gap == "indifferent"
    return Preference(policy.outside_day_rate, tuple(segments), 0 if indifferent else spec.desired_gap,
                      0 if indifferent else policy.gap_weight, policy.nearby_limit, "synthetic-D1-explicit-profile")


def compile_preferences(snapshot, preferences, cost_policy, cost_context):
    """Compile only explicit synthetic facts; never execute, query or mutate anything."""
    try:
        return _compile(snapshot, preferences, cost_policy, cost_context)
    except PreferenceError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, MemoryError):
        raise PreferenceError("INVALID_SYNTHETIC_COMPILATION") from None


def _compile(snapshot, preferences, cost_policy, cost_context):
    check(type(snapshot) is Snapshot and snapshot.origin == "synthetic", "SYNTHETIC_ONLY")
    check(type(preferences) is list and len(preferences) <= 32, "PREFERENCE_BUDGET")
    if (len(snapshot.participants) > 32 or len(snapshot.commitments) > 2000
            or sum(len(p.published) for p in snapshot.participants) > 2048):
        raise PreferenceUnavailable("SNAPSHOT_BUDGET")
    if snapshot.resources or any(e.resources for e in snapshot.commitments):
        raise PreferenceUnavailable("RESOURCE_SEMANTICS")
    policy = parse_policy(cost_policy)
    specs = [parse_preference(value) for value in preferences]
    check(len({p.owner for p in specs}) == len(specs), "DUPLICATE_OWNER")
    check({p.owner for p in specs} <= {p.id for p in snapshot.participants}, "UNKNOWN_OWNER")
    by_owner = {p.owner: p for p in specs}
    required = {p.id for p in snapshot.participants if p.required}
    if not required <= by_owner.keys():
        raise PreferenceUnavailable("PREFERENCE_MISSING")
    for person in snapshot.participants:
        if not person.required:
            continue
        spec = by_owner[person.id]
        if spec.state != "configured":
            raise PreferenceUnavailable("PREFERENCE_" + spec.state.upper())
        if spec.timezone != snapshot.zone:
            raise PreferenceUnavailable("MULTIPLE_COST_TIMEZONES")
        if person.calendar_state != "known":
            raise PreferenceUnavailable("UNRESOLVED_CALENDAR")
    publication = tuple((p.id, merged(p.published)) for p in snapshot.participants)
    candidates = _candidate_starts(snapshot, publication)
    if not candidates:
        raise PreferenceUnavailable("EMPTY_CANDIDATE_UNIVERSE")
    if len(candidates) > 256:
        raise PreferenceUnavailable("CANDIDATE_BUDGET")
    padding = policy.nearby_limit if policy.gap_weight and any(by_owner[p].desired_gap != "indifferent" for p in required) else None
    coverage, events, source = _context(cost_context, snapshot, required, candidates, padding)
    profiles = {p: _profile(by_owner[p], policy, coverage) for p in sorted(required)}
    # Keep the original candidate universe, but preserve complete cost context on
    # both sides. The explicit mode cannot generate extra search times.
    prepared = replace(snapshot, anchor=coverage.start, horizon=coverage, commitments=events,
        candidate_mode="explicit", explicit_starts=candidates,
        participants=tuple(replace(p, preference=profiles[p.id]) if p.required else p for p in snapshot.participants))
    normalized = normalize(prepared)
    if normalized.unsupported:
        raise PreferenceUnavailable("UNSUPPORTED_CALENDAR")
    request = cdmcs_request(normalized)
    request["existing"] = [
        {"id": event.id, "start": (event.interval.start - coverage.start) // 60,
         "duration": (event.interval.end - event.interval.start) // 60,
         "people": sorted(required.intersection(event.people)), "resources": [], "flexible": False}
        for event in events if required.intersection(event.people)]
    for profile in request["profiles"].values():
        profile["exception_fee"] = policy.exception_fee
    for key in ("move_fixed_cost", "move_participant_cost", "delay_per_day"):
        request[key] = getattr(policy, key)
    reference = DelayReference(candidates, snapshot.zone,
        datetime.fromtimestamp(min(candidates), ZoneInfo(snapshot.zone)).date().toordinal(), policy.delay_per_day)
    reference.check_candidates(candidates)
    document = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(document.encode("utf-8")) > 4 * 1024**2:
        raise PreferenceUnavailable("COMPILED_REQUEST_BUDGET")
    metadata = (("contract_version", 1), ("origin", "synthetic"), ("policy", (policy.identifier, policy.revision, policy.provenance)),
                ("owners", tuple((p, by_owner[p].revision, by_owner[p].provenance) for p in sorted(required))),
                ("search_horizon", (snapshot.horizon.start, snapshot.horizon.end)),
                ("cost_coverage", (coverage.start, coverage.end)), ("context_source", source),
                ("delay_basis", "earliest_full_candidate_local_date_v1"))
    return CompiledPreferences(document, reference, metadata)
