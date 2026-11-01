# D2: research-only fixed-calendar batching

This stage is synthetic-only and explicitly invoked. It does not select a live
scheduler, read a database, create bookings or persist preferences. Both C++ engines,
their protocols and the historical Python references remain unchanged.

## Contract audit and supported domain

The existing I3c runner executes two subprocesses per candidate and retains only
aggregate feasibility. Its CDMCS codec sets delay to zero and uses merged busy
blocks. It is an independent **feasibility** baseline, not a D1 score serializer.
The production appointment `validate` operation checks exactly one proposed
interval, including off-grid starts; its capped recommendation operation is not a
complete feasible-set API.

The unchanged I1 `solve` loop visits exactly the submitted starts. With protected
fixed events, no resources, no replacement starts and no extra-availability
windows, each start yields zero or one arrangement. A successful request containing
at most 100 distinct starts and `limit=100` can therefore return every feasible
submitted start. This statement is false when relocation is permitted. Protocol
validation must additionally reject truncation, duplicate/foreign starts, missing
counts, movement/permission output or an unresolved-calendar status.

Each D2 input is bound to an existing immutable I3c synthetic fixture and compiled
once by D1 from explicit owner preferences, explicit synthetic numerical policy
and complete unclipped calendar context. No profile defaults are invented. Missing
or unresolved calendars (including optional calendars in this first strict domain),
database-origin projections, resources, overlapping baseline meetings and
unsupported timezone/cost data are rejected before execution. Optional invitees
remain nonmandatory; an unavailable **known** optional calendar does not block.

## Delay and partition proof

For the full universe U, submitted subset S and unchanged local date array d:

```text
C_S(t) = sum(personal net burden at t) + w * (d(t) - d(min S))
C_S(t) - C_U(t) = -w * (d(min S) - d(min U))
```

Personal burden/fairness are independent of alternative candidate starts. Plain
chunks are equivalent only for zero delay or a preserved minimum local date. For
positive delay, a later-date chunk includes the original earliest candidate as an
ordinary reference alternative, consuming one of the configured <=100 slots.
No foreign time is introduced; the union remains exactly U. The reference is an
alternative, never a new commitment or reservation. Reference rows are
checked for consistent feasibility/cost/fairness but counted only at their unique
target occurrence. Every original candidate is a target exactly once. A blocked
reference still works: the C++ reader fixes its origin before feasibility checks.
Batch size one cannot express a later-date positive-delay target plus reference;
the entire plan is explicitly unsupported before launching, never silently rebased.

The D1 delay guard is called for each submitted subset. Only `candidate_starts`
and the output limit change; UTC anchor, horizon, prefix arrays, true original
events, published windows, duration and all weights stay unchanged. No score
correction, floating-point arithmetic or optimizer modification is performed.

Complete responses map each target to either its returned integer score/burden or
infeasible. Combining target scores by `(total, fairness, original start)` retains
the exact existing objective because movement fields are null. Production still
receives one original single-time validation per target, not per repeated reference.

## Components and use

- `planning.py`: immutable preparation through D1, delay-safe partitions and the
  strict complete-response gate. A batch has separate target and submitted indices.
- `runner.py`: `BatchedShadowRunner`, a narrow extension of the existing I3c runner.
  The shared normalization, executable verification and bounded child call were
  mechanically extracted in I3c; its singleton order and defaults are preserved.
- `benchmark.py`: explicitly invoked, bounded synthetic matched-path measurements.
- `tests/`: pure contract/transport tests, real bounded faulting children and native
  per-target/full-calendar witnesses. No production test or historical oracle changed.

```python
from research.cdmcs.i3d.d2.planning import prepare
from research.cdmcs.i3d.d2.runner import BatchedShadowRunner

# scope comes from the existing synthetic_fixture parser, never a live calendar.
prepared = prepare(scope, explicit_preferences, explicit_policy, complete_context)
runner = BatchedShadowRunner(cdmcs_binary, expected_sha256,
    production_path=manifest_validated_binary, enabled=True, batch_size=100)
result = runner.run(prepared)
```

Execution is disabled unless explicitly enabled. D2 shares I3c's single
process-local admission slot, per-child executable hashes, manifest validation,
5-second child/120-second run deadlines, 256 MiB child memory budget, 4 MiB input
and 64 KiB output limits. Existing configurable budget maxima remain unchanged.
There are no persistent workers, new dependencies, scheduler-selection hooks,
database calls or payload files. Original singleton execution remains available.

Successful results contain aggregate counts and ordinal-only integer scores/ranks
in normalized original-candidate order;
`summary()` and repr withhold those observations. No identities, timestamps, meeting
descriptions or raw payloads are returned. A child failure, truncation, changed
binary, inconsistent reference, invalid response or deadline discards partial
results. A production/CDMCS feasibility disagreement is explicit, incomplete and
withholds scores/ranking. No fallback silently reclassifies it as equality.

Native rows must remain `DIRECT_PENDING_NORMAL_MEETING_APPROVAL` with empty
extra-availability/relocation permission lists. This is a scheduling proposal,
not meeting approval, reservation or confirmation.

The unchanged C++ engine is trusted only after pinning and protocol validation.
An absent recommendation means infeasible in the proved fixed domain, not for a
general top-K response. Internally consistent but false count metadata cannot be
proved truthful from JSON alone; paired production checks detect differing
membership, and native tests independently verify the actual engine's behavior.

## Correctness evidence

The initial D2 checkpoint executed **52 tests with zero skips**: 14 planning/response,
14 runner plus one real faulting-child test, three benchmark tests and 20 native
tests. Native tests cover candidate counts 1, 2, 8, 32, 99, 100, 101, 128, 191 and
256, batch sizes 1, 2, 8, 32, 99 and 100, plus 20 seeded calendar/cost cases.
These are test methods with additional subcases, not 52 individual intervals.

Each native target is separately evaluated from D1 without using the D2 planner;
later-date positive-delay targets retain the original reference alternative.
Results also agree with D1's independent full-calendar cost recomputation. The
original I3c runner independently witnesses feasibility and, only for compatible
explicit profiles, raw scores. It cannot be used as a general D1 cost oracle.

Specific witnesses include:

- 101 feasible starts: the full response returns 100 and reports truncation;
  partitioning recovers all 101 without inferring a complete set from that response.
- Positive delay: costs `[3, 3, 5]` become `[3, 3, 0]` under naive singleton
  rebasing, reversing ranking. D2 preserves the former and its ordering.
- An infeasible earliest reference still preserves every later delay contribution.
- Negative personal-net changes remain negative; fairness uses the positive part,
  breaks equal-total ties and never overrides a lower total. Native costs above
  32 bits remain exact integers.
- True neighboring meetings outside the original search horizon, touching but
  separate events across midnight, noncontiguous/off-grid starts and DST changes
  retain full-calendar costs. Ambiguous/nonexistent endpoints fail explicitly.
- Four required calendars, sparse/empty feasible sets, optional unavailable guests and generic organizer
  labels preserve feasibility. Missing preferences/context, unresolved calendars,
  unsupported resources, overlapping baselines and excessive inputs fail closed.
- Actual child crash, timeout, malformed output, output flood and memory exhaustion
  are bounded, reaped and sanitized. Shared admission and hash/deadline regressions
  remain covered; no partial-success result survives an injected failure.

The first native test run exposed an incorrect *test expectation*, not a scheduler
defect: the off-grid start at minute 16 overlaps the fixture's `[31,61)` commitment
for a 30-minute meeting. The independently verified result is
`(true, false, false, true)` for starts `(1,16,31,150)`. The corrected test and the
initial failing log are retained in the local evidence; neither engine changed.

To run the gate, set `CDMCS_I3A_BINARY`, its `CDMCS_I3A_SHA256` and
`CDMCS_I3A_PRODUCTION` to explicit Release binaries (production needs its current
build manifest), use the application Python dependencies and tzdata, then run:

```text
python -B -m unittest discover -s research/cdmcs/i3d/d2/tests -p "test_*.py" -v
```

Missing native prerequisites deliberately skip native tests; a complete gate must
require all current methods and zero skips, not accept a partial green unittest
result. D2.5 increases this gate to 56 methods, as described below.

## Performance methodology

```text
python -B -m research.cdmcs.i3d.d2.benchmark --cdmcs BINARY --cdmcs-sha256 SHA256 \
  --production PRODUCTION_BINARY --candidates 1 8 32 128 256 \
  --batch-size 100 --repetitions 5 --warmups 1
```

Both paths use identical problem JSON, explicit neutral synthetic costs, two
required participants, empty fixed calendars and the same 15-minute starts.
D1 preparation is included equally in both end-to-end paths. Trial order
alternates, with one active child maximum. There is no production weight default.
Default experiments have one warmup and five measured trials per mode/size.
The CLI rejects excessive counts/repetitions/process budgets and checks a
15-minute experiment deadline between bounded individual runs.

Measurements include end-to-end/preparation/runner wall time, exact child counts,
serialization time/characters, executable hashing time/bytes, child CPU and peak
RSS where available. Serialization excludes UTF-8 encoding; process-launch and
transport timings do not isolate optimizer computation. Windows child CPU has
coarse timer resolution. Parent peak RSS is process-lifetime; Linux child peak RSS
is cumulative over the experiment, unlike Windows' per-trial child maximum.
Hooks add overhead. The JSON timer covers execution, not D1 preparation.
Five-sample nearest-rank p95 equals the observed maximum,
not a reliable population-tail estimate. Results establish only matched-path
startup/transport savings on this fixture, never an algorithmic speedup.

## Measured results

Local verification used Windows 11, Python 3.12.14, an Intel i5-10210U (four
cores/eight logical processors), GCC 14.3 and C++17 Release binaries. CDMCS used
`-O3 -DNDEBUG -Wall -Wextra -Wpedantic`; the unchanged production engine used
`-O3 -DNDEBUG`. Both executable hashes, flags, source hashes, hardware metadata
and raw per-trial results are retained in external evidence.

The confirmation experiment ran after application tests and disposable PostgreSQL
shutdown finished. Each row is five alternating trials per mode after one warmup;
times below are milliseconds. The p95 columns are **sample maxima**, not estimated
production service-level percentiles.

| Candidates | Singleton median | Batched median | Singleton p95 | Batched p95 | Median ratio | Processes, singleton/batched |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 162.13 | 163.79 | 173.97 | 168.67 | 0.99 | 2 / 2 |
| 8 | 406.37 | 305.59 | 418.29 | 320.35 | 1.33 | 16 / 9 |
| 32 | 1321.04 | 759.57 | 1381.15 | 841.71 | 1.74 | 64 / 33 |
| 128 | 4539.58 | 2439.12 | 4806.41 | 2722.85 | 1.86 | 256 / 130 |
| 256 | 9391.21 | 4675.20 | 9450.33 | 4698.59 | 2.01 | 512 / 259 |

Measured coefficients of variation, singleton/batched: 3.02/2.37%, 1.26/2.82%,
4.90/6.35%, 2.61/5.82%, and 0.45/0.55% in row order. Every measured result was
complete and matched, with one active child maximum and no unreaped children.
Maximum observed child RSS in this pass was 5.17 MiB; the parent lifetime peak
was 90.40 MiB, not a per-mode or per-trial heap measurement.

At 256 candidates, median instrumented JSON dumping fell from 271.9 to 11.1 ms;
hashing from 2070.5 to 1352.6 ms; summed partial process-launch time from 1774.2
to 895.4 ms; and exchange from 4694.9 to 2108.5 ms. Child CPU fell from 5718.8
to 2546.9 ms, but includes parsing/serialization and coarse Windows accounting.
These medians describe separate components/trials and must not be summed as an
exact latency decomposition. Pure optimization time remains unisolated. Repeated
hash verification is preserved, not cached away to improve the numbers.

The initial pass is also retained: singleton medians were
`158.87, 407.96, 1243.98, 4791.11, 9278.74` ms and batched medians were
`161.44, 304.41, 742.47, 2515.55, 4589.46` ms for the same candidate counts.
Its 128-candidate batched sample maximum was 3512.23 ms (CV 14.20%). PostgreSQL
shutdown was a known concurrent operation during that pass, a potential confound
but not a demonstrated cause of the outlier. No observations were discarded or
pooled into the confirmation pass. The earlier one-trial smoke run also remains
available and is not treated as performance evidence.

Recommendation: retain explicit bounded batching for supported multi-candidate
comparisons. One candidate saves no subprocess and showed no benefit; keep the
compatible singleton/reference option rather than promising universal improvement.
No automatic production strategy selection follows from these measurements.
Non-neutral/complex calendar performance and other platforms remain unbenchmarked.

## Regression verification

| Suite | Actual local result |
|---|---|
| Initial D2 checkpoint | 52 passed, zero skips; includes 20 native methods and 20 randomized subcases |
| D1 | 84 passed, zero skips |
| I3a | 37 passed, zero skips; 41 complete equality cases, 469 candidates, 391 feasible per engine; five unsupported/four invalid |
| I3b and identity | 47 + 8 passed, zero skips |
| I3c | 47 passed, zero skips |
| Standalone Release CTest | 2/2 passed: 618 differential cases, one unresolved, ten invalid; 25 safety methods including 84 independent horizon subcases |
| Application C++ | 192 passed; both standalone CSV CLI smoke cases passed |
| Application Python/PostgreSQL | 501 run in 2350.972 seconds: 500 passed, one expected Windows-only POSIX permission skip; no PostgreSQL skips |

The complete application run included all five strategy comparisons, schema drift
and migration checks, backup/restore, rollback/concurrency and existing student/staff
workflows. Alembic head remains `0049b`. The earlier interrupted application run
had no final result and is not counted as a pass. PostgreSQL 17.11 ran exclusively
in a separately owned synthetic cluster and was stopped after successful tests.

Local evidence is in `CDMCS_D2_Verification_20261031_205646` outside the checkout:
full test logs, `native-witnesses.json`, `benchmark-final.json` (initial pass),
`benchmark-confirmation.json`, hardware information, source/executable hashes,
build flags and preserved verification executables. No generated evidence,
database, binary or private calendar was added to Git.

## Remaining boundaries

- Maximum 256 original candidates and 100 submitted starts per batch. Positive
  multi-date delay may consume an additional original reference slot; size one
  is unsupported there. Relocation, additional availability and resource matching
  remain outside D2, even if the standalone optimizer supports some of them.
- D1's full-context/numerical/timezone restrictions remain intact. Batching cannot
  evade parent, input, child-work, output or time budgets. Resource-limit failures
  need not occur at the same point as singleton execution; no failed run is called
  complete or equivalent.
- Optional unknown calendars are deliberately rejected in this strict D2 domain;
  known unavailable optional invitees remain nonblocking. Optional preference
  ordering and production SS1 ranking are not added to the CDMCS objective.
- Synthetic provenance is an internal trusted-caller contract, not a sandbox
  against malicious Python code with access to process memory. Database-origin
  snapshots remain rejected; existing I3a export restrictions are unchanged.
- Distributed admission, production query budgets, actual user weights,
  real-calendar authorization/retention and activation require separate approval.
  No hosted CI, Linux D2 run or sanitizer result is implied by local Windows
  Release execution. The D2.5 gate below prepares that verification, not D3 activation.

## D2.5 correctness and security review

The review found no confirmed optimizer, preference-mapping or partition defect.
In the unchanged I1 source, `read_case()` fixes the earliest submitted start before
feasibility; `score()` adds its civil-day delay after personal burdens; `solve()`
enumerates submitted starts independently and caps retained arrangements. With
protected fixed events, empty exception/replacement/resource sets, at most one
arrangement exists per start. Thus the partition proof above applies, including an
infeasible reference and negative personal-net costs. Production ranking remains
separate: only its exact single-time feasibility validator is compared.

One verified coverage gap was corrected. The older injected-failure test failed
on the third call: the second production validation in the *first* paired batch.
New tests finish the first CDMCS batch and both production validations before
failing the next batch. They check later truncation, duplicate/foreign starts,
missing counts, conditional permissions and sanitized dependency exceptions.
Real child tests also finish a successful batch before a later crash, partial
stdout/nonzero exit, malformed output, flood, timeout or memory exhaustion. Both
children are reaped, pipes are closed, and no earlier scores or complete result
survive. These process doubles test transport, not native mathematical correctness.

The current **56-test** gate consists of 14 planning/response, 19 runner/process,
three benchmark and 20 native methods. It ran locally with zero skips. Existing
D1, I3a, I3b/identity, I3c and standalone tests also passed without weakening them.
The five original D2 commits remain intact; no C++ or production module changed.

Hosted coverage reuses the existing isolated PostgreSQL projection job rather
than duplicating builds or adding another runner framework. Its D2 step requires
each test group/minimum count, executable presence and SHA verification, and zero
skips. The Python gate has a 420-second timeout plus a five-second kill grace;
the step has an eight-minute cap. Existing container limits remain 3 GiB/two CPUs/
256 processes, with a separately bounded disposable PostgreSQL service. A local
execution of the exact embedded program passed all 56 methods. A negative check
with absent native prerequisites correctly rejected 20 skipped native methods.
Both workflows pass actionlint; all five embedded Python programs compile.

D2 changes now trigger the existing standalone Release, ASan/UBSan and I3a offline
jobs. Application C++/Python/PostgreSQL, D1, I3b/identity and I3c gates remain intact.
D2 runs with **Release CDMCS**, not ASan under its child address-space limit. The
projection job's production binary uses the existing builder's default flags;
that correctness gate is not an optimized performance experiment. Sanitizer
coverage applies only to actually executed instrumented standalone C++ suites,
never to D2 Python or its Release children. No deployment or private-payload
artifact step was added. Hosted execution remains pending publication; locally,
Windows has neither an installed WSL environment nor Docker.

Admission remains a trusted in-process synthetic contract, not an authorization
sandbox or a proof that a fixture author supplied every real commitment. Binary
pinning assumes trusted local build files; it is not an atomic-exec defense against
malicious concurrent replacement. Distributed admission, parent preparation/query
budgets and real-data policy still require separate approval. None is silently
enabled or resolved by batching.

Fresh D2.5 local verification repeated all gates with synthetic records on an
independently initialized PostgreSQL 17.11 cluster and newly built Release CDMCS:

| Gate | Executed result |
|---|---|
| Exact embedded D2 CI program | 56 passed, zero skips, in 127.079 seconds |
| D1 | 84 passed, zero skips |
| I3a | 37 passed, zero skips; original 41/469/391 complete-set baseline preserved |
| I3b and identity | 47 + 8 passed, zero skips |
| I3c | 47 passed, zero skips |
| Standalone Release | 2/2 CTest suites passed, including differential/safety/horizon tests |
| Application C++ | 192 passed; clean-slot and normal-dataset CSV CLI smokes passed |
| Application Python/PostgreSQL | 501 run in 2075.785 seconds: 500 passed, one expected Windows-only POSIX permission skip; no PostgreSQL skips |

The cluster was stopped after testing. No operational database, private calendar,
production scheduler or booking was used or changed. Hosted Ubuntu and ASan/UBSan
results are still pending; local static validation is not a hosted CI pass.

### D2.5 performance reproduction

The same audited benchmark/neutral synthetic fixture was re-executed using fresh
GCC 14.3 Release CDMCS and the SHA/manifest-validated unchanged optimized production
binary. Both use C++17, `-O3 -DNDEBUG`; environment remains Windows 11/Python
3.12.14/i5-10210U. All test/build processes and PostgreSQL shutdown finished before
measurement. Workstation load, frequency and thermal effects were not controlled.

Primary results: one warmup and five alternating trials per mode, batch size 100.
All times are milliseconds; each p95 is the observed sample maximum.

| Candidates | Singleton median | Batched median | Singleton p95 | Batched p95 | Median ratio | Processes, singleton/batched |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 227.30 | 213.95 | 237.46 | 236.10 | 1.06 | 2 / 2 |
| 8 | 537.10 | 547.84 | 1580.33 | 1470.74 | 0.98 | 16 / 9 |
| 32 | 1990.31 | 1347.39 | 2132.88 | 2330.70 | 1.48 | 64 / 33 |
| 128 | 4781.24 | 2596.39 | 5615.00 | 3382.15 | 1.84 | 256 / 130 |
| 256 | 11171.68 | 5105.89 | 12405.45 | 5813.04 | 2.19 | 512 / 259 |

Separate boundary experiment: one warmup and **three** alternating measured trials
per mode, not pooled with the primary data. Its p95 also equals the sample maximum.

| Candidates | Singleton median | Batched median | Singleton p95 | Batched p95 | Median ratio | Processes, singleton/batched |
|---|---:|---:|---:|---:|---:|---:|
| 2 | 310.96 | 332.63 | 354.32 | 380.02 | 0.93 | 4 / 3 |
| 99 | 5058.85 | 2075.44 | 5627.03 | 2126.89 | 2.44 | 198 / 100 |
| 100 | 3642.09 | 1962.48 | 3759.34 | 1970.67 | 1.86 | 200 / 101 |
| 101 | 3781.00 | 2067.58 | 3978.20 | 2090.87 | 1.83 | 202 / 103 |

Every result was complete/matched and every child was reaped, with at most one
active child. Maximum observed child RSS was 5.18 MiB and the primary parent
lifetime peak was 88.94 MiB. The boundary process had a separate 60.71 MiB lifetime
peak; neither value is a per-mode heap measurement.

The negative observations are important: batching's median was slower at 2 and 8,
and its 32-candidate sample maximum was worse despite a better median. The
8-candidate coefficients of variation were 58.07% singleton/54.00% batched;
32-candidate values were 9.87%/29.95%. Single-candidate 1.06 ratio saves no process
and does not establish an advantage. No outlier was removed or rerun until green.
These workstation samples do not justify a universal crossover threshold or SLA.
Keep compatible singleton/reference execution selectable for small comparisons;
do not silently zero D1 costs or rebase delay to obtain that fallback.

At 256, median JSON dumping was 328.8/12.1 ms (singleton/batched), hashing
2454.8/1468.6 ms, partial launch 2074.7/969.1 ms, and exchange 5617.2/2311.2 ms.
Child CPU was 6734.4/2828.1 ms with the same coarse-accounting/parsing limitations.
The observations are consistent with reduced process/transport/serialization and
repeated initialization work. Pure optimizer computation was not isolated, so no
faster scheduling algorithm or precise causal percentage is claimed.

Raw primary/boundary trials, counts, min/max/deviation/CV, components, hardware,
flags, executable/source hashes and test logs are retained outside the checkout in
`CDMCS_D25_Review_20261101_205015`. Earlier D2 measurements remain intact. These
experiments use neutral explicit weights/empty calendars; non-neutral correctness
is independently tested, not presented as benchmarked production performance.
