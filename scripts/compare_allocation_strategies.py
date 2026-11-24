"""Compare the five application strategies on one fictional corpus, offline."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import platform
from statistics import median
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from web.backend_executable import BackendExecutableError
from web.engine_gateway import EngineGateway, EngineIntegrationError
from web.persistence.demo import demo_snapshot
from web.persistence.models import STRATEGIES


def compare(seed=41, size='moderate', repeats=5):
    if type(repeats) is not int or not 1 <= repeats <= 30:
        raise ValueError('Use 1 to 30 measured runs per strategy.')
    snapshot, _ = demo_snapshot(seed, size)
    corpus = {key: value for key, value in snapshot.items() if key != 'strategy'}
    digest = hashlib.sha256(json.dumps(corpus, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    # The standalone contract accepts only the synthetic data generated above.
    # Application allocation still uses the repository eligibility gate.
    gateway = EngineGateway(ROOT, allow_unbound_allocations=True)
    baseline = {}
    build = None
    for strategy in STRATEGIES:
        result, metadata = gateway.execute(dict(corpus, strategy=strategy))
        if build is not None and build != metadata:
            raise RuntimeError('The engine build changed during the comparison. Rerun the experiment.')
        build = metadata
        baseline[strategy] = result

    elapsed = {strategy: [] for strategy in STRATEGIES}
    for repeat in range(repeats):
        # Rotate the order to avoid always timing a strategy first.
        offset = repeat % len(STRATEGIES)
        for strategy in STRATEGIES[offset:] + STRATEGIES[:offset]:
            started = perf_counter()
            result, metadata = gateway.execute(dict(corpus, strategy=strategy))
            elapsed[strategy].append((perf_counter() - started) * 1000)
            if build != metadata or result != baseline[strategy]:
                raise RuntimeError(f'The build or the {strategy} outcomes changed during the comparison.')

    strategies = {}
    for strategy, result in baseline.items():
        decisions = result['requestResults']
        by_status = Counter(row['status'] for row in decisions)
        by_type = {kind: dict(Counter(row['status'] for row in decisions if row['requestType'] == kind))
                   for kind in sorted({row['requestType'] for row in decisions})}
        rejected = [dict(requestId=row['requestId'], requestType=row['requestType'],
                         code=row['reasonCode'], reason=row['rejectionReason'])
                    for row in decisions if row['status'] == 'Rejected']
        strategies[strategy] = dict(
            approved=by_status['Approved'], rejected=by_status['Rejected'],
            allocationSegments=len(result['allocations']), byType=by_type,
            rejectionCounts=dict(Counter(row['reason'] for row in rejected)), rejections=rejected,
            gatewayMedianMs=round(median(elapsed[strategy]), 3),
            gatewaySamplesMs=[round(ms, 3) for ms in elapsed[strategy]])

    return dict(
        seed=seed, size=size, corpusSha256=digest, repeats=repeats,
        counts={key: len(snapshot[key]) for key in ('users', 'spaces', 'requests', 'busySlots')},
        host=dict(system=platform.system(), architecture=platform.machine(), python=platform.python_version()),
        build=build, engineVersion=baseline[STRATEGIES[0]]['engineVersion'],
        timing='Gateway wall time in milliseconds. One warm-up per strategy, followed by measured runs.',
        strategies=strategies)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=int, default=41)
    parser.add_argument('--size', choices=('moderate', 'large'), default='moderate')
    parser.add_argument('--repeats', type=int, default=5)
    args = parser.parse_args()
    try:
        report = compare(args.seed, args.size, args.repeats)
    except (BackendExecutableError, EngineIntegrationError, RuntimeError, ValueError) as error:
        parser.exit(1, f'Comparison failed: {error}\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
