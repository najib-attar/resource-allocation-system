"""Opt-in exact fixed-calendar batches on the existing bounded I3c kernel."""

from dataclasses import dataclass, field
from time import monotonic

from research.cdmcs.i3a.adapter import production_request
from research.cdmcs.i3c.process import ProcessFailure
from research.cdmcs.i3c.runner import ShadowResult, ShadowRunner
from research.cdmcs.i3d.d1.contract import PreferenceUnavailable
from web.engine_gateway import EngineIntegrationError, validate_appointment_result

from .planning import admitted, batch_request, batches, complete_response


@dataclass(frozen=True)
class BatchResult(ShadowResult):
    cdmcs_processes: int = 0
    production_processes: int = 0
    reference_evaluations: int = 0
    # Ordinal/feasible/integer cost/burden only, never identities or timestamps.
    observations: tuple = field(default=(), repr=False)
    ranked_ordinals: tuple = field(default=(), repr=False)

    def summary(self):
        return {key: value for key, value in self.__dict__.items()
                if key not in ('observations', 'ranked_ordinals')}


class BatchedShadowRunner(ShadowRunner):
    def __init__(self, *args, batch_size=100, **kwargs):
        super().__init__(*args, **kwargs)
        if type(batch_size) is not int or not 1 <= batch_size <= 100:
            raise ValueError('Batch size must be an integer from 1 through 100')
        self.batch_size = batch_size

    def _run(self, value, compare):
        deadline = monotonic() + self.budget.total_seconds
        if type(compare) is not bool:
            raise ValueError()
        admitted(value)
        normalized = self._normalize_scope(value.scope)
        if isinstance(normalized, ShadowResult):
            return normalized
        compiled = value.compiled
        if normalized.candidates != compiled.delay_reference.universe:
            raise ValueError('Mismatched original candidate universe')
        try:
            plan = batches(compiled, self.batch_size)
        except PreferenceUnavailable as error:
            return ShadowResult('unsupported', error.code)
        base = compiled.to_request()
        cdmcs, production, hashes = self._executables(compare)
        observed, first_reference = [], None
        feasible_c = feasible_p = discrepancies = launch = exchange = references = 0
        cdmcs_calls = production_calls = 0
        for batch in plan:
            request = batch_request(base, compiled, batch)
            call = self._call('cdmcs', cdmcs, [], request, hashes, deadline)
            cdmcs_calls += 1
            launch += call.launch_ns
            exchange += call.exchange_ns
            try:
                rows = complete_response(call.payload, request)
            except (ValueError, TypeError, KeyError):
                raise ProcessFailure('INVALID_PROTOCOL') from None
            reference = rows.get(base['candidate_starts'][0])
            if 0 in batch.targets:
                first_reference = reference
            elif 0 in batch.submitted:
                references += 1
                if reference != first_reference:
                    raise ProcessFailure('INCONSISTENT_REFERENCE')
            for index in batch.targets:
                score = rows.get(base['candidate_starts'][index])
                feasible = score is not None
                observed.append((index, feasible, score[0] if feasible else None, score[1] if feasible else None))
                feasible_c += feasible
                if compare:
                    candidate = normalized.candidates[index]
                    request = production_request(normalized, candidate)
                    call = self._call('production', production.path, ['--appointments-json'], request, hashes, deadline)
                    production_calls += 1
                    launch += call.launch_ns
                    exchange += call.exchange_ns
                    try:
                        validate_appointment_result(call.payload, request)
                        if call.payload['reasonCode'] in ('UNRESOLVED_CALENDAR', 'INVALID_INTERVAL'):
                            raise ValueError()
                    except (ValueError, TypeError, KeyError, EngineIntegrationError):
                        raise ProcessFailure('INVALID_PROTOCOL') from None
                    available = call.payload['feasible']
                    feasible_p += available
                    discrepancies += available != feasible
        if monotonic() > deadline:
            raise ProcessFailure('RUN_DEADLINE')
        if tuple(row[0] for row in observed) != tuple(range(len(normalized.candidates))):
            raise ProcessFailure('INCOMPLETE_CANDIDATE_ACCOUNTING')
        if discrepancies:
            return ShadowResult('discrepancy', 'FEASIBILITY_DISAGREEMENT', candidates=len(observed),
                                evaluated=len(observed), discrepancies=discrepancies)
        ranked = tuple(row[0] for row in sorted((r for r in observed if r[1]),
            key=lambda r: (r[2], r[3], normalized.candidates[r[0]])))
        if monotonic() > deadline:
            raise ProcessFailure('RUN_DEADLINE')
        return BatchResult('match' if compare else 'cdmcs_only',
            complete=True, candidates=len(observed), evaluated=len(observed), cdmcs_feasible=feasible_c,
            production_feasible=feasible_p, discrepancies=discrepancies, launch_ns=launch, exchange_ns=exchange,
            cdmcs_processes=cdmcs_calls, production_processes=production_calls, reference_evaluations=references,
            observations=tuple(observed), ranked_ordinals=ranked)
