"""Independent, deliberately small research prototype for one-move meeting scheduling.

Finite integer time grid. Existing meetings are conflict-free. A proposal can add
one new meeting and optionally relocate exactly one EXISTING meeting blocking the
new meeting. Availability exceptions are requests, never automatic approvals.

This is an experiment for validating a restricted mathematical model; it is NOT
application code, a proof of novelty, or a production-ready optimizer.
Run: python cdmcs_v1_reference_prototype.py
"""
from __future__ import annotations
from bisect import bisect_left
from dataclasses import dataclass
from collections import defaultdict
from random import Random


@dataclass(frozen=True)
class Meeting:
    id: str
    start: int
    duration: int
    people: tuple[str, ...]
    resources: tuple[str, ...] = ()
    flexible: bool = False

    @property
    def end(self):
        return self.start + self.duration

    @property
    def keys(self):
        return tuple(f"p:{x}" for x in self.people) + tuple(f"r:{x}" for x in self.resources)


def overlaps(a: Meeting, b: Meeting) -> bool:
    return a.start < b.end and b.start < a.end


def conflicts(a: Meeting, b: Meeting) -> bool:
    return overlaps(a, b) and bool(set(a.keys).intersection(b.keys))


@dataclass
class Case:
    existing: list[Meeting]
    people: tuple[str, ...]
    resources: tuple[str, ...]
    duration: int
    starts: tuple[int, ...]
    replacements: tuple[int, ...]
    windows: dict[str, tuple[int, int]]
    may_offer_extra: dict[str, bool]
    preferred_starts: dict[str, int]
    preferred_gaps: dict[str, int]

    def new(self, t):
        return Meeting('NEW', t, self.duration, self.people, self.resources)


def extra_permissions(e: Meeting, c: Case):
    """Return people whose explicit one-time exception is needed, or None if ineligible."""
    pending = []
    for p in e.people:
        lo, hi = c.windows[p]
        if not (lo <= e.start and e.end <= hi):
            if not c.may_offer_extra[p]:
                return None
            pending.append(p)
    return tuple(pending)


def schedule_preference(person: str, events: list[Meeting], c: Case) -> int:
    own = sorted((e for e in events if person in e.people), key=lambda e: e.start)
    # Illustrative integer preference units, NOT validated research weights.
    time_cost = sum(abs(e.start - c.preferred_starts[person]) for e in own)
    # Only nearby gaps matter; avoid charging a day-long idle interval.
    gap_cost = sum(abs((b.start - a.end) - c.preferred_gaps[person])
                   for a, b in zip(own, own[1:]) if b.start - a.end <= 4)
    return time_cost + gap_cost


def score(c: Case, new: Meeting, moved: Meeting | None = None):
    before = c.existing
    after = [e for e in before if not moved or e.id != moved.id] + [new]
    if moved:
        after.append(moved)
    affected = set(new.people) | (set(moved.people) if moved else set())
    burdens = {p: schedule_preference(p, after, c) - schedule_preference(p, before, c)
               for p in affected}
    conditional = set(extra_permissions(new, c) or ())
    if moved:
        conditional.update(extra_permissions(moved, c) or ())
    for p in conditional:
        burdens[p] += 6  # illustrative cost of requesting extra availability
    if moved:
        # Administrative disruption penalty attributed to total but not individual preference.
        change_cost = 4
    else:
        change_cost = 0
    total = sum(burdens.values()) + change_cost + new.start // 4
    fairness = max((max(0, v) for v in burdens.values()), default=0)
    return (total, fairness, new.start, moved.id if moved else '', moved.start if moved else -1)


def independently_valid(c: Case, new: Meeting, moved: Meeting | None):
    """Slow, exhaustive pairwise validator independent of the interval index."""
    if extra_permissions(new, c) is None:
        return False
    if moved and extra_permissions(moved, c) is None:
        return False
    schedule = [e for e in c.existing if not moved or e.id != moved.id]
    schedule.append(new)
    if moved:
        schedule.append(moved)
    return all(not conflicts(a, b) for i, a in enumerate(schedule)
               for b in schedule[i + 1:])


def brute_force(c: Case):
    """Slow exhaustive reference over all candidates and one blocking move."""
    best = None
    for t in c.starts:
        new = c.new(t)
        blockers = {e.id for e in c.existing if conflicts(e, new)}
        if not blockers and independently_valid(c, new, None):
            best = min(best, score(c, new)) if best else score(c, new)
        if len(blockers) == 1:
            old = next(e for e in c.existing if e.id in blockers)
            if old.flexible:
                for r in c.replacements:
                    moved = Meeting(old.id, r, old.duration, old.people, old.resources, old.flexible)
                    if independently_valid(c, new, moved):
                        s = score(c, new, moved)
                        best = min(best, s) if best else s
    return best


class IntervalIndex:
    """Uses per-person/resource non-overlap to report overlaps in O(log n + k)."""
    def __init__(self, existing):
        groups = defaultdict(list)
        for e in existing:
            for k in e.keys:
                groups[k].append(e)
        self.entries = {}
        for k, events in groups.items():
            by_start = sorted(events, key=lambda e: e.start)
            self.entries[k] = ([e.start for e in by_start], by_start)

    def blockers(self, e, exclude_id=None):
        found = {}
        for key in e.keys:
            starts, events = self.entries.get(key, ([], []))
            i = bisect_left(starts, e.end)
            # For each key, baseline intervals do not overlap. Walk backwards
            # until an event finishes before the candidate starts.
            while i:
                i -= 1
                other = events[i]
                if other.end <= e.start:
                    break
                if other.id != exclude_id:
                    found[other.id] = other
        return found


def indexed_cached(c: Case):
    """Indexed conflicts + once-per-event replacement validation; exact cost scoring."""
    index = IntervalIndex(c.existing)
    feasible_replacements = {}
    best = None
    for t in c.starts:
        new = c.new(t)
        if extra_permissions(new, c) is None:
            continue
        blockers = index.blockers(new)
        if not blockers:
            # No overlap in any attendee or resource calendar.
            s = score(c, new)
            best = min(best, s) if best else s
            continue
        if len(blockers) != 1:
            continue
        old = next(iter(blockers.values()))
        if not old.flexible:
            continue
        if old.id not in feasible_replacements:
            possible = []
            for r in c.replacements:
                moved = Meeting(old.id, r, old.duration, old.people, old.resources, old.flexible)
                if extra_permissions(moved, c) is not None and not index.blockers(moved, exclude_id=old.id):
                    possible.append(moved)
            feasible_replacements[old.id] = possible
        for moved in feasible_replacements[old.id]:
            # Mandatory JOINT check: a previously valid replacement could
            # overlap the new meeting that we are trying to insert.
            if conflicts(new, moved):
                continue
            s = score(c, new, moved)
            best = min(best, s) if best else s
    return best


def random_case(rng: Random, serial: int):
    people_pool = ('A', 'B', 'C', 'D', 'E')
    resources_pool = ('R1', 'R2')
    existing = []
    for j in range(rng.randint(2, 10)):
        chosen = tuple(sorted(rng.sample(people_pool, rng.randint(1, 3))))
        res = (rng.choice(resources_pool),) if rng.random() < 0.25 else ()
        proposed = Meeting(f'E{j}', rng.randrange(0, 14), rng.randint(1, 3),
                           chosen, res, rng.random() < 0.65)
        if all(not conflicts(proposed, e) for e in existing):
            existing.append(proposed)
    windows = {p: ((0, 16) if rng.random() < 0.5 else (rng.randint(0, 4), rng.randint(11, 16)))
               for p in people_pool}
    return Case(
        existing=existing,
        people=tuple(sorted(rng.sample(people_pool, rng.randint(2, 3)))),
        resources=(rng.choice(resources_pool),) if rng.random() < 0.45 else (),
        duration=rng.randint(1, 3),
        starts=tuple(range(0, 14)),
        replacements=tuple(range(0, 14)),
        windows=windows,
        may_offer_extra={p: rng.random() < 0.8 for p in people_pool},
        preferred_starts={p: rng.randint(2, 12) for p in people_pool},
        preferred_gaps={p: rng.choice((0, 1, 2)) for p in people_pool},
    )


def targeted_tests():
    people = ('A', 'B', 'C')
    defaults = dict(
        people=('A', 'B'), resources=(), duration=2,
        starts=(3,), replacements=(6, 7),
        windows={p: (0, 12) for p in people},
        may_offer_extra={p: True for p in people},
        preferred_starts={p: 4 for p in people},
        preferred_gaps={p: 0 for p in people},
    )
    # Same meeting appears in both attendee calendars but must count once.
    same = Case(existing=[Meeting('SHARED', 3, 2, ('A', 'B'), flexible=True)], **defaults)
    assert len(IntervalIndex(same.existing).blockers(same.new(3))) == 1
    assert brute_force(same) == indexed_cached(same) != None
    # Two DIFFERENT meetings are not resolvable with the one-move policy.
    double = Case(existing=[Meeting('A-OLD', 3, 2, ('A',), flexible=True),
                            Meeting('B-OLD', 3, 2, ('B',), flexible=True)], **defaults)
    assert brute_force(double) == indexed_cached(double) == None
    # Outside published availability may be proposed only when explicitly eligible.
    refusal = dict(defaults)
    refusal['windows'] = {'A': (0, 2), 'B': (0, 12), 'C': (0, 12)}
    refusal['may_offer_extra'] = {'A': False, 'B': True, 'C': True}
    denied = Case(existing=[], **refusal)
    assert brute_force(denied) == indexed_cached(denied) == None
    refusal['may_offer_extra']['A'] = True
    offered = Case(existing=[], **refusal)
    assert brute_force(offered) == indexed_cached(offered) != None
    # Half-open intervals permit back-to-back meetings.
    assert not conflicts(Meeting('X', 1, 2, ('A',)), Meeting('Y', 3, 1, ('A',)))


def main():
    targeted_tests()
    rng = Random(20261028)
    cases = 300
    with_answer = 0
    with_move = 0
    for n in range(cases):
        c = random_case(rng, n)
        a = brute_force(c)
        b = indexed_cached(c)
        assert a == b, (n, a, b, c)
        if a is not None:
            with_answer += 1
            if a[3]:
                with_move += 1
    print(f'PASS: {cases} seeded test instances; indexed search matches independent exhaustive reference.')
    print(f'Instance outcomes: feasible={with_answer}, infeasible={cases - with_answer}, optimum with one move={with_move}')
    print('Scope: explicit finite time grid, at most one blocking movable meeting, proposed exceptions only.')
    print('No claim of novelty, formal continuous-time optimality, or production performance.')


if __name__ == '__main__':
    main()
