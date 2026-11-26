"""Native pilot search with group-level explanations and no calendar writes."""

from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from research.cdmcs.i3a.execution import validate_cdmcs

from .calendar_service import calendar_snapshot, epoch, university_zone
from .cdmcs_rehearsal import FlexibleMeeting, TIER_POLICY, _compile, _relocation_rows, _run
from .group_meeting_rooms import require_meeting_room
from .group_meeting_service import MeetingError, hard_windows, relocation_target
from .persistence.models import GroupMeeting, GroupMeetingParticipant


def _facts(session, fixture, actor, selection, *, exclude=(), room=None):
    required, optional, duration, _, _, _ = selection
    return calendar_snapshot(session, actor, required, optional, duration, fixture.start, fixture.end,
        exclude_group_meetings=exclude, linked_room_request=room)


def _replacement_candidates(fixture, facts, windows, target, affected):
    busy = defaultdict(list)
    for row in facts["busy"]:
        if row["userId"] in affected:
            busy[row["userId"]].append((row["start"], row["end"]))
    start = max(fixture.start, datetime.now(timezone.utc).replace(second=0, microsecond=0) + timedelta(minutes=1))
    origin = fixture.start
    duration = target.end_at - target.start_at
    minutes = int((start - origin).total_seconds() // 60)
    start = origin + timedelta(minutes=(-minutes % 15) + minutes)
    matches = []
    while start + duration <= fixture.end:
        end = start + duration
        if start != target.start_at and all(any(a <= start and end <= b for a, b in windows[uid])
                and not any(a < epoch(end) and b > epoch(start) for a, b in busy[uid]) for uid in affected):
            matches.append(start)
        start += timedelta(minutes=15)
    # Keep both ends of the free range. Sampling only the earliest proposals
    # could place every replacement inside a longer new meeting.
    return tuple(dict.fromkeys(matches[:2] + matches[-2:]))


def _gap_count(events, local_days):
    ordered = sorted(events)
    return sum(left[1] < right[0] and local_days[left[0]] == local_days[right[0]]
               for left, right in zip(ordered, ordered[1:]))


def _metrics(payload, row, earliest):
    start, end = row["start_minute"], row["end_minute"]
    people, days = payload["required_people"], payload["local_day_index"]
    old = defaultdict(list)
    new = defaultdict(list)
    for event in payload["existing"]:
        a, b = event["start"], event["start"] + event["duration"]
        replacement = row["replacement_start_minute"] if event["id"] == row["moved_meeting_id"] else a
        for uid in event["people"]:
            old[uid].append((a, b))
            new[uid].append((replacement, replacement + (b - a)))
    preferred = 0
    for uid in people:
        new[uid].append((start, end))
        prefix = payload["profiles"][uid]["rate_prefix"]
        preferred += sum(prefix[i + 1] - prefix[i] == TIER_POLICY["preferred_rate"] for i in range(start, end))
    return {"wait": start - earliest, "coverage": round(100 * preferred / ((end - start) * len(people))),
            "gaps": sum(_gap_count(new[uid], days) - _gap_count(old[uid], days) for uid in people),
            "cost": row["total_cost"]}


def _rank(fixture, selection, payload, rows, *, earliest=None, target=None):
    if earliest is None:
        earliest = min(payload["candidate_starts"])
    zone = university_zone()
    preferred = selection[-1]
    result = []
    for row in rows:
        start = fixture.start + timedelta(minutes=row["start_minute"])
        end = fixture.start + timedelta(minutes=row["end_minute"])
        move_time = (fixture.start + timedelta(minutes=row["replacement_start_minute"])
                     if target is not None else None)
        result.append({"start": start, "display": f"{start.astimezone(zone):%a %d %b, %H:%M} – {end.astimezone(zone):%H:%M}",
            "move": (target.id, target.revision, move_time.isoformat()) if target else None,
            "replacement": (f"{move_time.astimezone(zone):%a %d %b, %H:%M} – "
                f"{(move_time + (target.end_at - target.start_at)).astimezone(zone):%H:%M}") if target else None,
            "rank": (row["total_cost"], row["fairness_max_burden"],
                     abs((start - preferred).total_seconds()) if preferred else 0, start),
            **_metrics(payload, row, earliest)})
    return result


def plan(session, fixture, actor, roster, selection, room_id, features):
    required, optional, duration, first, last, _ = selection
    future = datetime.now(timezone.utc).replace(second=0, microsecond=0) + timedelta(minutes=1)
    minutes = max(0, int((future - first).total_seconds() // 60))
    first += timedelta(minutes=minutes + (-minutes % 15))
    if first >= last:
        raise MeetingError("Choose a search range with future availability.")
    selection = (*selection[:3], first, last, selection[-1])
    room = None
    if room_id is not None:
        from .group_meeting_rooms import meeting_room_choices
        room = next((choice for choice in meeting_room_choices(session, actor) if choice.request_id == room_id), None)
        if (room is None or room.end - room.start != timedelta(minutes=duration)
                or not first <= room.start < room.end <= last):
            raise MeetingError("Choose the approved room's exact date and duration.")
        require_meeting_room(session, actor, room_id, room.start, room.end, [*required, *optional], features)
        selection = (*selection[:3], room.start, room.end, selection[-1])
    windows, _ = hard_windows(session, required, fixture.start, fixture.end)
    if any(not windows[uid] for uid in required):
        return [], [], room
    fixed = replace(fixture, flexible=())
    facts = _facts(session, fixture, actor, selection, room=room_id)
    payload, _, _, _ = _compile(session, fixed, actor, roster, selection, hard_windows=windows, facts_snapshot=facts)
    if payload is None:
        return [], [], room
    direct = _run(fixture, payload)
    validate_cdmcs(direct, payload)
    direct_rows = _rank(fixture, selection, payload, direct["recommendations"])
    moved = []
    if room_id is None:
        query = select(GroupMeeting.id).join(GroupMeetingParticipant).where(
            GroupMeeting.status == "Confirmed", GroupMeeting.flexible.is_(True), GroupMeeting.move_target_id.is_(None),
            GroupMeeting.start_at < last, GroupMeeting.end_at > first, GroupMeetingParticipant.user_id == actor,
            GroupMeetingParticipant.side != "optional").order_by(GroupMeeting.start_at, GroupMeeting.id).limit(3)
        for target_id in session.scalars(query):
            try:
                target, affected = relocation_target(session, actor, roster, target_id, set(required))
            except MeetingError:
                continue
            unblocked = _facts(session, fixture, actor, selection, exclude=(target.id,))
            replacements = _replacement_candidates(fixture, unblocked[0], windows, target, affected)
            if not replacements:
                continue
            subject = FlexibleMeeting(tuple(sorted(affected)), target.start_at, target.end_at, replacements)
            candidate, flex, _, _ = _compile(session, replace(fixture, flexible=(subject,)), actor, roster, selection,
                hard_windows=windows, facts_snapshot=unblocked)
            if candidate is not None:
                rows = _relocation_rows(fixture, candidate, flex)
                moved.extend(_rank(fixture, selection, candidate, rows, earliest=min(payload["candidate_starts"]), target=target))
    return sorted(direct_rows, key=lambda item: item["rank"])[:8], sorted(moved, key=lambda item: item["rank"])[:8], room
