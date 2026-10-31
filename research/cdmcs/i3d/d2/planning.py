"""Immutable D1 preparation and complete, globally comparable request partitions."""

from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from research.cdmcs.i3a.execution import validate_cdmcs
from research.cdmcs.i3c.admission import admitted_snapshot
from research.cdmcs.i3d.d1.compiler import CompiledPreferences, compile_preferences
from research.cdmcs.i3d.d1.contract import PreferenceError, PreferenceUnavailable


_SEAL = object()


@dataclass(frozen=True, repr=False)
class PreparedInput:
    scope: object = field(repr=False)
    compiled: object = field(repr=False)
    bound_scope: object = field(repr=False)
    bound_compiled: object = field(repr=False)
    seal: object = field(repr=False)

    def __repr__(self):
        return 'PreparedInput(synthetic_only=True; calendar and costs withheld)'


def prepare(scope, preferences, policy, context):
    """Explicit pure preparation; no process, database, preference default or export."""
    snapshot = admitted_snapshot(scope)
    if snapshot.origin != 'synthetic':
        raise PreferenceError('SYNTHETIC_ONLY')
    if any(p.calendar_state != 'known' for p in snapshot.participants):
        raise PreferenceUnavailable('UNRESOLVED_CALENDAR')
    compiled = compile_preferences(snapshot, preferences, policy, context)
    return PreparedInput(scope, compiled, scope, compiled, _SEAL)


def admitted(value):
    if (type(value) is not PreparedInput or value.seal is not _SEAL
            or value.scope is not value.bound_scope or value.compiled is not value.bound_compiled
            or type(value.compiled) is not CompiledPreferences):
        raise ValueError('Invalid synthetic batch scope')
    snapshot = admitted_snapshot(value.scope)
    if snapshot.origin != 'synthetic':
        raise ValueError('Invalid synthetic batch origin')
    return snapshot


@dataclass(frozen=True)
class Batch:
    # Indices only, not participant identities or calendar timestamps.
    targets: tuple
    submitted: tuple


def batches(compiled, size):
    """Keep the reference date without adding foreign starts or rebasing costs."""
    if type(size) is not int or not 1 <= size <= 100:
        raise ValueError('Batch size must be an integer from 1 through 100')
    reference = compiled.delay_reference
    universe = reference.universe
    zone = ZoneInfo(reference.timezone)
    result, position = [], 0
    while position < len(universe):
        needs_reference = bool(reference.weight and
            datetime.fromtimestamp(universe[position], zone).date().toordinal() != reference.earliest_day)
        capacity = size - int(needs_reference)
        if not capacity:
            raise PreferenceUnavailable('BATCH_DELAY_CAPACITY')
        targets = tuple(range(position, min(position + capacity, len(universe))))
        submitted = (0, *targets) if needs_reference else targets
        reference.check_candidates(tuple(universe[i] for i in submitted))
        result.append(Batch(targets, submitted))
        position += len(targets)
    if tuple(i for b in result for i in b.targets) != tuple(range(len(universe))):
        raise ValueError('Incomplete candidate partition')
    return tuple(result)


def batch_request(base, compiled, batch):
    """Change candidate selection only; all calendar/cost context stays identical."""
    starts = tuple(compiled.delay_reference.universe[i] for i in batch.submitted)
    compiled.delay_reference.check_candidates(starts)
    relative = tuple(base['candidate_starts'][i] for i in batch.submitted)
    return {**base, 'candidate_starts': list(relative), 'limit': 100}


def complete_response(payload, request):
    """A missing row means infeasible only after the complete fixed-result gate."""
    outcome = validate_cdmcs(payload, request)
    if (outcome not in ('feasible', 'infeasible') or payload['truncated']
            or payload['returned_count'] != payload['solutions_evaluated']
            or not 1 <= len(request['candidate_starts']) <= request['limit'] <= 100):
        raise ValueError('Incomplete fixed-calendar batch response')
    return {row['start_minute']: (row['total_cost'], row['fairness_max_burden'])
            for row in payload['recommendations']}
