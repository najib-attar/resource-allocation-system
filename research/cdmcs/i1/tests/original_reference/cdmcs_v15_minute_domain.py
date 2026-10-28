"""V15 standalone research extension: UTC-minute intervals with local-time preferences.

DOES NOT replace historical V1--V14 implementations. No production code.
The finite explicit candidate grid is supplied by the caller. All permissions
are proposals only; no calendars are mutated, and no approvals are obtained.

This module reuses the *unchanged* V1 IntervalIndex and V3 WeeklyCostIndex.
The independent exhaustive reference uses all-pairs conflict checks and
full schedule preference recomputation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable
from zoneinfo import ZoneInfo
from collections import defaultdict
from cdmcs_v1_reference_prototype import Meeting, IntervalIndex, conflicts
from cdmcs_v3_weekly_cost import WeeklyCostIndex


@dataclass(frozen=True)
class MinuteProfile:
    """Prefix costs per elapsed UTC minute, based on local civil weekday/hour.

    published and exceptions are lists of *half-open absolute UTC-minute windows*
    relative to a common UTC anchor. Each requested interval must be fully
    contained in one window; adjacent entries are not implicitly merged.
    """
    prefix: tuple[int, ...]
    published: tuple[tuple[int, int], ...]
    exceptions: tuple[tuple[int, int], ...]
    preferred_break: int
    gap_weight: int
    nearby_limit: int
    exception_fee: int
    anchor: datetime
    zone: ZoneInfo

    def event_cost(self, event: Meeting) -> int:
        if not (0 <= event.start < event.end < len(self.prefix)):
            raise ValueError('Event lies outside precomputed bounded UTC-minute horizon')
        return self.prefix[event.end] - self.prefix[event.start]

    def gap(self, left: Meeting | None, right: Meeting | None) -> int:
        if left is None or right is None:
            return 0
        gap = right.start - left.end
        if gap < 0:
            raise ValueError('Overlapping events in preference calendar')
        if gap > self.nearby_limit:
            return 0
        ld = (self.anchor + timedelta(minutes=left.start)).astimezone(self.zone).date()
        rd = (self.anchor + timedelta(minutes=right.start)).astimezone(self.zone).date()
        if ld != rd:
            return 0  # explicit V15 policy: no break penalty across start dates
        return abs(gap - self.preferred_break) * self.gap_weight


def build_profile(*, anchor_utc: datetime, zone_name: str, horizon_minutes: int,
                  weekday_penalty: tuple[int, ...], preferred_bands: dict[int, tuple[tuple[int, int], ...]],
                  published: tuple[tuple[int, int], ...],
                  exceptions: tuple[tuple[int, int], ...] = (),
                  nonpreferred_hour_penalty: int = 2,
                  preferred_break: int = 15, gap_weight: int = 1,
                  nearby_limit: int = 120, exception_fee: int = 30) -> MinuteProfile:
    if anchor_utc.tzinfo != timezone.utc:
        raise ValueError('anchor_utc must use datetime.timezone.utc explicitly')
    if horizon_minutes <= 0 or len(weekday_penalty) != 7:
        raise ValueError('Invalid horizon or weekday penalty table')
    if any(x < 0 for x in weekday_penalty) or any(x < 0 for x in
            (nonpreferred_hour_penalty, preferred_break, gap_weight, nearby_limit, exception_fee)):
        raise ValueError('Penalties and break parameters must be nonnegative')
    for day, bands in preferred_bands.items():
        if not 0 <= day <= 6:
            raise ValueError('Invalid weekday index')
        for lo, hi in bands:
            if not (0 <= lo < hi <= 1440):
                raise ValueError('Preferred-hour band outside a local day')
    for windows in (published, exceptions):
        for lo, hi in windows:
            if not 0 <= lo < hi <= horizon_minutes:
                raise ValueError('Availability window outside horizon')
    zone = ZoneInfo(zone_name)
    prefix = [0]
    for i in range(horizon_minutes):
        local = (anchor_utc + timedelta(minutes=i)).astimezone(zone)
        minute_of_day = 60 * local.hour + local.minute
        preferred = any(lo <= minute_of_day < hi for lo, hi in preferred_bands.get(local.weekday(), ()))
        rate = weekday_penalty[local.weekday()] + (0 if preferred else nonpreferred_hour_penalty)
        prefix.append(prefix[-1] + rate)
    return MinuteProfile(tuple(prefix), published, exceptions, preferred_break,
                         gap_weight, nearby_limit, exception_fee, anchor_utc, zone)


def covered(event: Meeting, windows: tuple[tuple[int, int], ...]) -> bool:
    return any(lo <= event.start and event.end <= hi for lo, hi in windows)


@dataclass
class MinuteCase:
    existing: list[Meeting]
    participants: tuple[str, ...]
    resources: tuple[str, ...]
    duration: int
    candidate_starts: tuple[int, ...]
    replacement_starts: tuple[int, ...]
    profiles: dict[str, MinuteProfile]
    move_fixed_cost: int = 20
    move_participant_cost: int = 5
    delay_per_day: int = 5
    unresolved_people: frozenset[str] = frozenset()
    earliest_start: int = field(init=False)

    def __post_init__(self):
        if not self.participants:
            raise ValueError('At least one required participant is needed')
        if not self.candidate_starts or self.duration <= 0:
            raise ValueError('New meeting needs positive duration and explicit starts')
        if len({e.id for e in self.existing}) != len(self.existing):
            raise ValueError('Duplicate original meeting IDs')
        if any(e.id == 'NEW' for e in self.existing):
            raise ValueError('NEW is reserved for proposed meeting')
        if any(e.duration <= 0 for e in self.existing):
            raise ValueError('Nonpositive existing duration')
        if any(conflicts(a, b) for i, a in enumerate(self.existing) for b in self.existing[i+1:]):
            raise ValueError('Initial schedule contains conflicts; indexing invariant invalid')
        for p in set(self.participants) | {p for e in self.existing for p in e.people}:
            if p not in self.profiles:
                raise ValueError(f'Missing participant preference/availability profile: {p}')
        if not self.profiles:
            raise ValueError('At least one profile is required')
        anchors = {(p.anchor,p.zone.key,len(p.prefix)) for p in self.profiles.values()}
        if len(anchors) != 1:
            raise ValueError('All profiles must share UTC anchor, timezone and horizon')
        self.earliest_start = min(self.candidate_starts)
        H = len(next(iter(self.profiles.values())).prefix) - 1
        if any(t < 0 or t+self.duration > H for t in self.candidate_starts):
            raise ValueError('Candidate start outside horizon')
        if any(t < 0 or t > H for t in self.replacement_starts):
            raise ValueError('Replacement start outside horizon')
        if any(e.start < 0 or e.end > H for e in self.existing):
            raise ValueError('Existing meeting outside precomputed horizon')

    def new(self,t):
        return Meeting('NEW',t,self.duration,self.participants,self.resources)


def exception_requests(event: Meeting, case: MinuteCase) -> tuple[str, ...] | None:
    if event.start < 0 or event.duration <= 0:
        return None
    requested=[]
    if set(event.people) & case.unresolved_people:
        return None  # fail closed; an unresolved calendar is never free time
    for person in event.people:
        pref=case.profiles[person]
        if event.end > len(pref.prefix)-1:
            return None
        if covered(event,pref.published):
            continue
        if not covered(event,pref.exceptions):
            return None
        requested.append(person)
    return tuple(requested)


def _full_person_cost(person: str, meetings: Iterable[Meeting], case: MinuteCase) -> int:
    p=case.profiles[person]
    own=sorted((e for e in meetings if person in e.people),key=lambda e:(e.start,e.id))
    return sum(p.event_cost(e) for e in own) + sum(p.gap(a,b) for a,b in zip(own,own[1:]))


def _burdens(case: MinuteCase, new: Meeting, moved: Meeting | None):
    required=exception_requests(new, case)
    extra=exception_requests(moved,case) if moved else ()
    if required is None or extra is None:
        raise ValueError('Cannot score arrangement without requestable availability')
    burdens=defaultdict(int)
    for person in required + extra:
        burdens[person]+=case.profiles[person].exception_fee
    if moved:
        for person in moved.people:
            burdens[person]+=case.move_participant_cost
    return burdens


def _delay(case: MinuteCase, new: Meeting):
    profile=next(iter(case.profiles.values()))
    start_date=(profile.anchor+timedelta(minutes=new.start)).astimezone(profile.zone).date()
    earliest_date=(profile.anchor+timedelta(minutes=case.earliest_start)).astimezone(profile.zone).date()
    return (start_date-earliest_date).days*case.delay_per_day


def full_score(case: MinuteCase, new: Meeting, moved: Meeting | None=None):
    after=[e for e in case.existing if moved is None or e.id != moved.id]+[new]
    if moved:
        after.append(moved)
    affected=set(new.people) | (set(moved.people) if moved else set())
    burdens=_burdens(case,new,moved)
    for person in affected:
        burdens[person]+=_full_person_cost(person,after,case)-_full_person_cost(person,case.existing,case)
    total=sum(burdens.values())+(case.move_fixed_cost if moved else 0)+_delay(case,new)
    fair=max((max(0,x) for x in burdens.values()),default=0)
    return (total,fair,new.start,moved.id if moved else '',moved.start if moved else -1)


def local_score(case: MinuteCase, index: WeeklyCostIndex, new: Meeting, moved: Meeting | None=None):
    affected=set(new.people) | (set(moved.people) if moved else set())
    burdens=_burdens(case,new,moved)
    for person in affected:
        burdens[person]+=index.delta(person,case,new,moved)
    total=sum(burdens.values())+(case.move_fixed_cost if moved else 0)+_delay(case,new)
    fair=max((max(0,x) for x in burdens.values()),default=0)
    return (total,fair,new.start,moved.id if moved else '',moved.start if moved else -1)


def independently_feasible(case: MinuteCase, new: Meeting, moved: Meeting | None=None):
    if exception_requests(new,case) is None:
        return False
    if moved:
        original=next((e for e in case.existing if e.id==moved.id),None)
        if (original is None or not original.flexible or not conflicts(original,new)
                or (original.people,original.resources,original.duration) !=
                   (moved.people,moved.resources,moved.duration)):
            return False
        if exception_requests(moved,case) is None:
            return False
    after=[e for e in case.existing if moved is None or e.id!=moved.id]+[new]
    if moved:
        after.append(moved)
    return all(not conflicts(a,b) for i,a in enumerate(after) for b in after[i+1:])


def case_status(case: MinuteCase):
    if case.unresolved_people.intersection(case.participants):
        return 'UNRESOLVED_CALENDAR'
    return 'READY'

def exhaustive(case: MinuteCase):
    if case_status(case) != 'READY':
        return None
    best=None
    for t in case.candidate_starts:
        new=case.new(t)
        if independently_feasible(case,new):
            s=full_score(case,new)
            best=s if best is None else min(best,s)
        for old in case.existing:
            if not old.flexible or not conflicts(new,old):
                continue
            for r in case.replacement_starts:
                moved=Meeting(old.id,r,old.duration,old.people,old.resources,old.flexible)
                if independently_feasible(case,new,moved):
                    s=full_score(case,new,moved)
                    best=s if best is None else min(best,s)
    return best


def indexed(case: MinuteCase):
    if case_status(case) != 'READY':
        return None
    intervals=IntervalIndex(case.existing)
    cost_index=WeeklyCostIndex(case.existing)
    valid_replacements={}
    best=None
    for t in case.candidate_starts:
        new=case.new(t)
        if exception_requests(new,case) is None:
            continue
        blockers=intervals.blockers(new)
        if not blockers:
            s=local_score(case,cost_index,new)
            best=s if best is None else min(best,s)
        elif len(blockers)==1:
            old=next(iter(blockers.values()))
            if not old.flexible:
                continue
            if old.id not in valid_replacements:
                avail=[]
                for r in case.replacement_starts:
                    moved=Meeting(old.id,r,old.duration,old.people,old.resources,old.flexible)
                    if (exception_requests(moved,case) is not None and
                            not intervals.blockers(moved,exclude_id=old.id)):
                        avail.append(moved)
                valid_replacements[old.id]=avail
            for moved in valid_replacements[old.id]:
                if conflicts(new,moved):
                    continue
                s=local_score(case,cost_index,new,moved)
                best=s if best is None else min(best,s)
    return best
