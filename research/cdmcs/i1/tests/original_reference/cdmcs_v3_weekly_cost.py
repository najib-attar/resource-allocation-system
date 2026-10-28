"""CDMCS V3 research prototype: exact weekday/hour + local gap/disruption costs.

Not production code. All weights and user profiles in this file are synthetic.
A single new meeting may be inserted, and optionally one *blocking* flexible
meeting may move to an explicitly enumerated replacement slot. No cascades.
Conditional availability exceptions require later approval, never auto-booking.

Run from the same directory as cdmcs_v1_reference_prototype.py:
    python cdmcs_v3_weekly_cost.py
"""
from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass, field
from random import Random
from statistics import median
from time import perf_counter
from typing import Iterable

from cdmcs_v1_reference_prototype import Meeting, IntervalIndex, conflicts

SLOTS_PER_DAY = 96  # 15-minute ticks, day 0 = Monday; a seven-day research week
WEEK = 7 * SLOTS_PER_DAY


def date_time(day: int, hour: int, minute: int = 0) -> int:
    assert 0 <= day < 7 and 0 <= hour < 24 and minute in (0, 15, 30, 45)
    return day * SLOTS_PER_DAY + hour * 4 + minute // 15


def same_day_event(e: Meeting) -> bool:
    return (0 <= e.start < WEEK and e.duration > 0 and e.end <= WEEK
            and e.start // SLOTS_PER_DAY == (e.end - 1) // SLOTS_PER_DAY)


def within_any(e: Meeting, windows: tuple[tuple[int, int], ...]) -> bool:
    return any(lo <= e.start and e.end <= hi for lo, hi in windows)


@dataclass(frozen=True)
class Profile:
    """Preference rates in *illustrative* penalty units per 15-minute slot.

    `rate_prefix` is a prefix sum over all seven days. `published` are already
    offered booking windows, `exception` are *potentially requestable* extra
    windows. Both require the entire meeting to fit one individual window.
    """
    rate_prefix: tuple[int, ...]
    published: tuple[tuple[int, int], ...]
    exception: tuple[tuple[int, int], ...]
    preferred_break: int
    nearby_limit: int = 8
    gap_weight: int = 1
    exception_fee: int = 5

    def event_cost(self, meeting: Meeting) -> int:
        if not same_day_event(meeting):
            raise ValueError('An event must be positive-length and within one week/day')
        return self.rate_prefix[meeting.end] - self.rate_prefix[meeting.start]

    def gap(self, a: Meeting | None, b: Meeting | None) -> int:
        if a is None or b is None:
            return 0
        gap = b.start - a.end
        if gap < 0:
            raise ValueError('Calendar overlap in a preference evaluation')
        if a.start // SLOTS_PER_DAY != b.start // SLOTS_PER_DAY:
            return 0  # no overnight gap penalty
        if gap > self.nearby_limit:
            return 0  # unrelated meetings are not treated as adjacent appointments
        return abs(gap - self.preferred_break) * self.gap_weight


def make_profile(day_base: tuple[int, ...],
                 preferred_time_bands: dict[int, tuple[tuple[int, int], ...]],
                 published: tuple[tuple[int, int], ...],
                 exception: tuple[tuple[int, int], ...],
                 preferred_break: int, exception_fee: int = 5,
                 nearby_limit: int = 8, gap_weight: int = 1,
                 nonpreferred_time_surcharge: int = 2) -> Profile:
    """Construct ONE weekday-by-hour rate map from two distinct preferences.

    Each slot rate = weekday penalty + hour penalty (0 in preferred bands,
    `nonpreferred_time_surcharge` elsewhere). Thus a preferred hour does not
    erase the cost of a disliked day, nor is either factor counted twice.
    Preferred bands use day-local ticks in [0, 96]. Units are uncalibrated.
    """
    if len(day_base) != 7 or any(v < 0 for v in day_base):
        raise ValueError('Seven nonnegative daily base rates required')
    if (preferred_break < 0 or nearby_limit < 0 or gap_weight < 0
            or exception_fee < 0 or nonpreferred_time_surcharge < 0):
        raise ValueError('Nonnegative penalty parameters required')
    for windows in (published, exception):
        for lo, hi in windows:
            if not (0 <= lo < hi <= WEEK) or lo // 96 != (hi - 1) // 96:
                raise ValueError('Availability windows must be within a single day')
    rates = []
    for day in range(7):
        day_rates = [day_base[day] + nonpreferred_time_surcharge] * SLOTS_PER_DAY
        for lo, hi in preferred_time_bands.get(day, ()):
            if not (0 <= lo < hi <= SLOTS_PER_DAY):
                raise ValueError('Invalid preferred time band')
            for tick in range(lo, hi):
                day_rates[tick] = day_base[day]
        rates.extend(day_rates)
    prefix = [0]
    for rate in rates:
        prefix.append(prefix[-1] + rate)
    return Profile(tuple(prefix), published, exception, preferred_break,
                   nearby_limit, gap_weight, exception_fee)


def windows_for_days(days: Iterable[int], start_tick: int, end_tick: int):
    if not 0 <= start_tick < end_tick <= 96:
        raise ValueError('Invalid day-local window')
    return tuple((d*96 + start_tick, d*96 + end_tick) for d in days)


@dataclass
class ResearchCase:
    existing: list[Meeting]
    participants: tuple[str, ...]
    resources: tuple[str, ...]
    duration: int
    candidate_starts: tuple[int, ...]
    replacement_starts: tuple[int, ...]
    profiles: dict[str, Profile]
    move_fixed_cost: int = 3
    move_participant_cost: int = 1
    delay_per_day: int = 2
    earliest_start: int = field(init=False)

    def __post_init__(self):
        if not self.candidate_starts:
            raise ValueError("At least one candidate start is required")
        self.earliest_start = min(self.candidate_starts)

    def new(self, t: int) -> Meeting:
        return Meeting('NEW', t, self.duration, self.participants, self.resources)


def exception_requests(event: Meeting, case: ResearchCase) -> tuple[str, ...] | None:
    if not same_day_event(event):
        return None
    requested = []
    for p in event.people:
        pref = case.profiles[p]
        if within_any(event, pref.published):
            continue
        if not within_any(event, pref.exception):
            return None
        requested.append(p)
    return tuple(requested)


def full_person_cost(person: str, meetings: Iterable[Meeting], case: ResearchCase) -> int:
    profile = case.profiles[person]
    own = sorted((e for e in meetings if person in e.people), key=lambda e: (e.start, e.id))
    return sum(profile.event_cost(e) for e in own) + sum(
        profile.gap(a, b) for a,b in zip(own, own[1:]))


def disruption_burdens(case: ResearchCase, new: Meeting, moved: Meeting | None):
    ex_new = exception_requests(new, case)
    ex_move = exception_requests(moved, case) if moved else ()
    if ex_new is None or ex_move is None:
        raise ValueError('An unrequestable time may not be scored')
    burden = defaultdict(int)
    # Per-event exception requests. Both events may require separate approvals.
    for p in ex_new + ex_move:
        burden[p] += case.profiles[p].exception_fee
    if moved:
        for p in moved.people:
            burden[p] += case.move_participant_cost
    return burden


def score_full(case: ResearchCase, new: Meeting, moved: Meeting | None = None):
    """Independent full-calendar recomputation oracle (not the fast evaluator)."""
    after = [e for e in case.existing if moved is None or e.id != moved.id]
    after += [new]
    if moved:
        after += [moved]
    affected = set(new.people) | (set(moved.people) if moved else set())
    burden = disruption_burdens(case, new, moved)
    for p in affected:
        burden[p] += full_person_cost(p, after, case) - full_person_cost(p, case.existing, case)
    total = sum(burden.values()) + (case.move_fixed_cost if moved else 0)
    total += ((new.start - case.earliest_start) // 96) * case.delay_per_day
    fairness = max((max(0, x) for x in burden.values()), default=0)
    return (total, fairness, new.start, moved.id if moved else '', moved.start if moved else -1)


@dataclass
class PersonCalendar:
    events: list[Meeting]
    keys: list[tuple[int, str]]
    by_id: dict[str, Meeting]


class WeeklyCostIndex:
    """Sorted baseline plus ≤2 locally inserted events, and one removed event."""
    def __init__(self, existing: Iterable[Meeting]):
        grouped = defaultdict(list)
        for event in existing:
            for person in event.people:
                grouped[person].append(event)
        self.calendars = {}
        for p, meetings in grouped.items():
            events = sorted(meetings, key=lambda e: (e.start, e.id))
            self.calendars[p] = PersonCalendar(
                events, [(e.start, e.id) for e in events], {e.id: e for e in events})

    def neighbors(self, p: str, target: Meeting, excluded_id: str | None,
                  overlay: tuple[Meeting, ...]):
        cal = self.calendars.get(p)
        key = (target.start, target.id)
        prev = following = None
        if cal:
            pos = bisect_left(cal.keys, key)
            left = pos-1
            while left >= 0 and cal.events[left].id == excluded_id:
                left -= 1
            if left >= 0:
                prev = cal.events[left]
            right = pos
            while right < len(cal.events) and cal.events[right].id == excluded_id:
                right += 1
            if right < len(cal.events):
                following = cal.events[right]
        for other in overlay:
            k = (other.start, other.id)
            if k < key and (prev is None or k > (prev.start, prev.id)):
                prev = other
            if k > key and (following is None or k < (following.start, following.id)):
                following = other
        return prev, following

    def delta(self, p: str, case: ResearchCase, new: Meeting,
              moved: Meeting | None) -> int:
        profile = case.profiles[p]
        old = None
        cal = self.calendars.get(p)
        if moved and p in moved.people:
            old = cal.by_id.get(moved.id) if cal else None
            if old is None:
                raise ValueError('Original movable meeting is absent')
        excluded_id = old.id if old else None
        cost = 0
        overlay = ()
        if old:
            a, b = self.neighbors(p, old, excluded_id, overlay)
            cost -= profile.event_cost(old) + profile.gap(a, old) + profile.gap(old, b)
            cost += profile.gap(a, b)
        if p in new.people:
            a, b = self.neighbors(p, new, excluded_id, overlay)
            cost += profile.event_cost(new) + profile.gap(a, new) + profile.gap(new, b)
            cost -= profile.gap(a, b)
            overlay = (new,)
        if moved and p in moved.people:
            a, b = self.neighbors(p, moved, excluded_id, overlay)
            cost += profile.event_cost(moved) + profile.gap(a, moved) + profile.gap(moved, b)
            cost -= profile.gap(a, b)
        return cost

    def score(self, case: ResearchCase, new: Meeting,
              moved: Meeting | None = None):
        affected = set(new.people) | (set(moved.people) if moved else set())
        burden = disruption_burdens(case, new, moved)
        for p in affected:
            burden[p] += self.delta(p, case, new, moved)
        total = sum(burden.values()) + (case.move_fixed_cost if moved else 0)
        total += ((new.start - case.earliest_start) // 96) * case.delay_per_day
        fairness = max((max(0, x) for x in burden.values()), default=0)
        return (total, fairness, new.start, moved.id if moved else '', moved.start if moved else -1)


def independent_feasible(case: ResearchCase, new: Meeting,
                         moved: Meeting | None = None):
    """Slow pairwise feasibility reference, independent of interval indexing."""
    if exception_requests(new, case) is None:
        return False
    if moved and exception_requests(moved, case) is None:
        return False
    if moved:
        orig = next((e for e in case.existing if e.id == moved.id), None)
        if not orig or not orig.flexible or not conflicts(orig, new):
            return False
        if (moved.duration, moved.people, moved.resources) != (orig.duration,orig.people,orig.resources):
            return False
    others = [e for e in case.existing if moved is None or e.id != moved.id]
    after = others + [new] + ([moved] if moved else [])
    return all(not conflicts(a,b) for i,a in enumerate(after) for b in after[i+1:])


def exhaustive(case: ResearchCase):
    best = None
    for t in case.candidate_starts:
        new = case.new(t)
        if independent_feasible(case, new):
            result = score_full(case, new)
            best = result if best is None else min(best, result)
        for old in case.existing:
            if not old.flexible or not conflicts(new,old):
                continue
            for r in case.replacement_starts:
                moved = Meeting(old.id, r, old.duration, old.people, old.resources, old.flexible)
                if independent_feasible(case, new, moved):
                    result = score_full(case, new, moved)
                    best = result if best is None else min(best, result)
    return best


def indexed(case: ResearchCase):
    idx = IntervalIndex(case.existing)
    costs = WeeklyCostIndex(case.existing)
    valid_replacements = {}
    best = None
    for t in case.candidate_starts:
        new = case.new(t)
        if exception_requests(new, case) is None:
            continue
        blockers = idx.blockers(new)
        if not blockers:
            result = costs.score(case, new)
            best = result if best is None else min(best, result)
            continue
        if len(blockers) != 1:
            continue
        old = next(iter(blockers.values()))
        if not old.flexible:
            continue
        if old.id not in valid_replacements:
            replacements = []
            for r in case.replacement_starts:
                moved = Meeting(old.id, r, old.duration, old.people, old.resources, old.flexible)
                if (exception_requests(moved, case) is not None
                        and not idx.blockers(moved, exclude_id=old.id)):
                    replacements.append(moved)
            valid_replacements[old.id] = replacements
        for moved in valid_replacements[old.id]:
            if conflicts(new, moved):
                continue
            result = costs.score(case, new, moved)
            best = result if best is None else min(best, result)
    return best


def profile_for_test(rng: Random, allow_extra=True):
    pref = {day: ((rng.randrange(33, 45), rng.randrange(55, 69)),) for day in range(3)}
    # Rebuild strictly ordered bands for random generation
    pref = {day: ((min(b[0], b[1]-1), b[1]),) for day, (b,) in pref.items()}
    return make_profile(
        day_base=tuple(rng.choice((1,2,3,5)) for _ in range(7)),
        preferred_time_bands=pref,
        published=windows_for_days(range(3), 36, 58),
        exception=windows_for_days(range(3), 30, 70) if allow_extra else (),
        preferred_break=rng.choice((0,1,2,4)),
        exception_fee=rng.choice((1,4,8)),
    )


def random_case(rng: Random):
    all_people = ('A','B','C','D')
    profiles = {p: profile_for_test(rng, rng.random() < 0.8) for p in all_people}
    existing = []
    for i in range(rng.randrange(0,9)):
        ps = tuple(sorted(rng.sample(all_people, rng.randint(1,3))))
        rs = ('R',) if rng.random() < 0.25 else ()
        day = rng.randrange(3)
        proposal = Meeting(f'E{i}', day*96 + rng.randrange(34,61),
                           rng.randint(1,4), ps, rs, rng.random() < 0.6)
        if all(not conflicts(e, proposal) for e in existing):
            existing.append(proposal)
    starts = tuple(sorted(set(rng.randrange(3)*96+rng.randrange(30,66) for _ in range(8))))
    replacements = tuple(sorted(set(rng.randrange(3)*96+rng.randrange(30,68) for _ in range(8))))
    return ResearchCase(
        existing=existing,
        participants=tuple(sorted(rng.sample(all_people, rng.randint(1,3)))),
        resources=('R',) if rng.random() < 0.3 else (),
        duration=rng.randint(1,4), candidate_starts=starts,
        replacement_starts=replacements, profiles=profiles,
        move_fixed_cost=3, move_participant_cost=2, delay_per_day=2)


def check_pairwise_cost(case: ResearchCase):
    idx = WeeklyCostIndex(case.existing)
    arrangements = 0
    moved_count = 0
    for t in case.candidate_starts:
        new = case.new(t)
        if independent_feasible(case, new):
            a,b = score_full(case,new),idx.score(case,new)
            assert a==b, ('DIRECT',a,b,new)
            arrangements += 1
        for old in case.existing:
            if not old.flexible or not conflicts(new,old):
                continue
            for r in case.replacement_starts:
                moved = Meeting(old.id, r, old.duration, old.people, old.resources, old.flexible)
                if independent_feasible(case,new,moved):
                    a,b = score_full(case,new,moved),idx.score(case,new,moved)
                    assert a==b, ('MOVE',a,b,new,moved)
                    arrangements += 1
                    moved_count += 1
    assert exhaustive(case)==indexed(case), ('WINNER',exhaustive(case),indexed(case))
    return arrangements,moved_count


def run_tests():
    rng = Random(20261028)
    # Explicit adversarial cases around midnight, start/end of day, and neighbor gap edits.
    all_people = ('A','B','C')
    prof = make_profile(
        (1,2,1,2,4,6,6),
        {0: ((36,48),), 1: ((52,68),), 2: ((36,52),)},
        windows_for_days(range(3),36,60),
        windows_for_days(range(3),30,72),
        preferred_break=1, exception_fee=5,
    )
    ps = {p:prof for p in all_people}
    assert prof.event_cost(Meeting('A',date_time(0,9),4,('A',)))==4
    assert prof.event_cost(Meeting('B',date_time(1,9),4,('A',)))==16
    assert prof.event_cost(Meeting('C',date_time(1,13),4,('A',)))==8
    assert prof.event_cost(Meeting('D',date_time(2,9),4,('A',)))==4
    assert prof.event_cost(Meeting('E',date_time(4,9),4,('A',)))==24
    # A preferred hour does NOT remove a disliked-day penalty.
    friday_pref = make_profile((0,0,0,0,5,0,0),{4: ((36,48),)},(),(),0)
    assert friday_pref.event_cost(Meeting('FRI',date_time(4,9),4,('A',)))==20
    # Adjacent events incur 1 unit if a 15-minute gap is preferred; overnight gaps ignored.
    assert prof.gap(Meeting('O',date_time(0,9),4,('A',)),Meeting('N',date_time(0,10),4,('A',)))==1
    assert prof.gap(Meeting('O',date_time(0,16),4,('A',)),Meeting('N',date_time(1,9),4,('A',)))==0
    # Outside published but inside exception is conditional; protected/unoffered is invalid.
    t = date_time(0,8)
    testcase = ResearchCase([],('A',),(),4,(t,),(date_time(1,10),),ps)
    assert exception_requests(testcase.new(t),testcase)==('A',)
    assert exception_requests(testcase.new(date_time(0,7)),testcase) is None
    assert exception_requests(testcase.new(date_time(0,23,45)),testcase) is None
    assert exception_requests(testcase.new(date_time(6,23,45)),testcase) is None
    # One published window is insufficient for a meeting spanning two windows.
    split = make_profile((0,)*7, {},
                         ((date_time(0,9),date_time(0,10)),
                          (date_time(0,10,15),date_time(0,11))), (), 0)
    splitcase = ResearchCase([],('A',),(),2,(date_time(0,9,45),),(),{'A': split})
    assert exception_requests(splitcase.new(date_time(0,9,45)),splitcase) is None
    # Non-overlap at a 15-minute boundary.
    assert not conflicts(Meeting('N',date_time(0,10),1,('A',)),Meeting('X',date_time(0,10,15),1,('A',)))
    targeted = [
        ResearchCase([Meeting('M',date_time(0,10),2,('A','B'),flexible=True)],('A','B'),(),2,
                     (date_time(0,10),date_time(0,11)),(date_time(1,14),date_time(2,12)),ps),
        ResearchCase([Meeting('M',date_time(0,10),2,('A','B'),flexible=True),
                      Meeting('Z',date_time(1,14),2,('A',))],('A','B'),(),2,
                     (date_time(0,10),date_time(1,14)),(date_time(1,14),date_time(2,12)),ps),
        ResearchCase([Meeting('X',date_time(0,10),2,('A',),('R',),True),
                      Meeting('Y',date_time(0,10),2,('B',))],('A','B'),('R',),2,
                     (date_time(0,10),),(date_time(2,12),),ps),
        ResearchCase([],('A',),(),2,(date_time(0,23,45),),(date_time(1,11),),ps),
        ResearchCase([Meeting('IMMOVABLE',date_time(0,10),2,('A','B'))],
                     ('A','B'),(),2,(date_time(0,10),),(date_time(2,12),),ps),
        ResearchCase([Meeting('M1',date_time(0,10),2,('A',),flexible=True),
                      Meeting('M2',date_time(0,10),2,('B',),flexible=True)],
                     ('A','B'),(),2,(date_time(0,10),),(date_time(2,12),),ps),
    ]
    assert exhaustive(targeted[-1]) is None and indexed(targeted[-1]) is None
    assert exhaustive(targeted[-2]) is None and indexed(targeted[-2]) is None
    assert exhaustive(targeted[-3]) is None and indexed(targeted[-3]) is None
    tcount=0; tmoves=0
    for c in targeted:
        a,b=check_pairwise_cost(c); tcount+=a;tmoves+=b
    trials=600; checked=0; moved=0; feasible=0
    for i in range(trials):
        c=random_case(rng)
        a,b=check_pairwise_cost(c)
        checked+=a;moved+=b
        if exhaustive(c) is not None:
            feasible+=1
    # Deliberately force blocked cases. Random calendars alone overwhelmingly
    # admit a direct solution, so they poorly exercise the core relocation rule.
    forced = 300
    forced_solutions = 0
    forced_moves = 0
    forced_options = 0
    for i in range(forced):
        day = i % 3
        t = date_time(day,10)
        mode = i % 4
        if mode == 0:
            old = [Meeting('X',t,2,('A','B'),flexible=True)]
        elif mode == 1:
            old = [Meeting('X',t,2,('A','B'),flexible=False)]
        elif mode == 2:
            old = [Meeting('X',t,2,('A',),flexible=True),
                   Meeting('Y',t,2,('B',),flexible=True)]
        else:
            old = [Meeting('X',t,2,('A','B'),flexible=True),
                   Meeting('Y',t+96,2,('A','B'),flexible=False)]
        cas = ResearchCase(old,('A','B'),(),2,(t,),
                           (t+96,t+97,t+2*96),ps)
        a,b=check_pairwise_cost(cas)
        forced_options += a
        answer=exhaustive(cas)
        if answer is not None:
            forced_solutions+=1
            if answer[3]:
                forced_moves+=1
    return {'targeted_cases':len(targeted),'targeted_valid_options':tcount,
            'randomized_cases':trials,'randomized_cases_with_solution':feasible,
            'forced_conflict_cases':forced,'forced_cases_with_solution':forced_solutions,
            'forced_winners_relocating':forced_moves,
            'feasible_alternatives_verified':checked+tcount+forced_options,
            'relocation_alternatives_verified':moved+tmoves+forced_options}



def benchmark_case(n_per_person: int, starts_count: int):
    people = ('A','B','C')
    pref = make_profile((1,2,1,2,1,3,3),{},
                        windows_for_days(range(7),0,96),(),1)
    profiles={p:pref for p in people}
    events=[]
    # Distribute across first five days; single-unit events, non-overlapping.
    ticks=[d*96+t for d in range(5) for t in range(10,85)]
    for p in ('A','B'):
        for i,t in enumerate(ticks[:n_per_person]):
            events.append(Meeting(f'{p}{i}',t,1,(p,)))
    starts=tuple(date_time(6,10)+i for i in range(starts_count))
    return ResearchCase(events,('A','B'),(),1,starts,(),profiles)


def run_benchmarks(repeats=5):
    rows=[]
    for n, starts in [(40,15),(150,25),(350,40)]:
        case=benchmark_case(n,starts)
        full_scores=[]; local_scores=[]
        for t in case.candidate_starts:
            ev=case.new(t)
            full_scores.append(score_full(case,ev))
            local_scores.append(WeeklyCostIndex(case.existing).score(case,ev))
        assert full_scores==local_scores
        costs=WeeklyCostIndex(case.existing)
        measured=[]
        for label, method in [('full', lambda e:score_full(case,e)),
                              ('local',lambda e:costs.score(case,e))]:
            samples=[]
            for _ in range(repeats):
                start=perf_counter()
                for t in case.candidate_starts:
                    method(case.new(t))
                samples.append((perf_counter()-start)*1000)
            measured.append(median(samples))
        rows.append((len(case.existing),starts,measured[0],measured[1]))
    return rows


def main():
    print('PASS:',run_tests())
    print('Preference scorer microbenchmarks; index built BEFORE timing; illustrative only:')
    print('Calendar records | new starts | full ms | local ms | ratio')
    for n,k,a,b in run_benchmarks():
        print(f'{n:16d} | {k:10d} | {a:7.3f} | {b:8.3f} | {a/b:5.2f}x')
    print('No survey calibration, no external timezone conversion, no production integration.')


if __name__=='__main__':
    main()
