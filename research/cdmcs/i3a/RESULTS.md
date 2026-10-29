# I3a verified results - 28 October 2026

## Scope and architecture

Base: merged I2.5 `2ceadbd941b8666479277616791bf1a4bc34cb2d`.
Measured code checkpoint: `7635287029d23a8253bcbeeddb312a3f33a63c2d`.
All new code is under `research/cdmcs/i3a/`. Neither C++ engine, historical
reference, production build, gateway, Flask route, database model, migration,
authorization rule nor appointment record was changed.

```text
Explicit synthetic JSON / in-memory facts
                 |
       Frozen Snapshot / Participant / Commitment / Preference
                 |
       One Normalized fixed-calendar projection
           /                              \
Production appointment serializer     I1 serializer
           |                              |
Existing --appointments-json         Existing CDMCS CLI
           \                              /
        Raw process records + strict output validation
                 |
  Complete per-candidate feasible sets; separate rank/timing evidence
```

`snapshot.py` owns immutable facts and explicit timezone/input validation.
`adapter.py` normalizes interval unions and produces fresh protocol dictionaries.
`execution.py` verifies/pins binaries, owns a disposable working directory and
records process output/timeouts. `comparison.py` compares complete candidate sets
without making Python scheduling decisions. `fixtures.py` defines fictional
calendars; `__main__.py` exports evidence exclusively outside the checkout.
Four test modules exercise contracts, mapping, failure paths and real C++ calls.
No framework, persistence layer, new C++ algorithm or live adapter was introduced.

## Complete feasible-set comparison

The repeated matrix contains **50 cases**:

| Classification | Actual result |
|---|---:|
| Supported, equal complete feasible sets | 41 |
| Unsupported comparison, no engine invocation | 5 |
| Intentionally invalid input, rejected before invocation | 4 |
| Unexplained discrepancies / native integration failures | 0 / 0 |

One supported case has an explicitly empty candidate universe and invokes neither
engine. The other 40 execute real paired C++ validation. Across case-specific
universes there are **469 candidate contexts**, with **391 feasible contexts** in
each engine. These are not 469 distinct global timestamps. No false positives or
false negatives occurred on these tested finite universes; no universal theorem
or equivalence outside the documented restricted mapping is inferred.

One warmup round and three measured rounds produced **3790 native calls**:
938 warmup validations, 2814 measured validations and 38 separate ranking calls.
Every candidate uses identical instants/duration/mandatory calendars in both
engines. Raw requests, stdout, stderr, parsed responses, exits and times are kept.
All case-file SHA-256 checks and per-candidate timestamp mappings were independently
rechecked after export. Twenty small cases also match independent interval-
inequality expectations, without using either engine as the expected-result oracle.

Witnesses include three professors (feasible minute offsets 30, 90, 150), manual
off-grid times (1 and 150 feasible; 16 and 31 conflicting), touching published
windows with a non-clock-quarter anchor (22, 37, ..., 142), half-open adjacency,
overlapping busy records, midnight/weekdays, Unicode opaque identities, all four
organizer role labels, optional unknown/busy people and both Berlin DST transitions.

The large fixture has **191 feasible starts in each complete reconstructed set**;
each actual batch recommendation returns only **100**. No capped list was treated
as complete. The empty-feasible-set and empty-grid cases are reported distinctly.

Five excluded cases are mandatory missing data, mandatory unresolved data,
exclusive resources, unsupported facility requirements and a backward civil-date
transition in historical St Johns timezone data. Invalid cases are a DST gap,
DST fold, boolean duration and excessive availability windows. Unit tests cover
additional malformed JSON, duplicate fields, identifiers, precision and bounds.

## Ranking is a separate experiment

Exactly one ranking fixture intentionally differs: an optional student is busy
for the first hour, while synthetic professor rates prefer the earliest slot.
Production ranks offset **60 minutes** first; CDMCS ranks **0 minutes** first,
with total cost and maximum positive burden both zero. The feasible sets are
identical. Production prioritizes known-free optional invitees and preferred-time
distance; I1 uses configured incremental cost/fairness. This is not a correctness
discrepancy, utility calibration, permission grant or booking.

## Measured process costs, not pure algorithm runtime

Windows x64; Python 3.12.14; GCC/MinGW 14.3.0; CMake 4.0.2; Boost 1.85.0;
tzdata 2026.5 with `PYTHONTZPATH` empty. Both engines were freshly compiled with
effective **-O0**, C++17, without sanitizer instrumentation for measurements.
Production used the unchanged `scripts/build_backend.py --compiler <g++14.3>
--output <external>/production/allocation_system.exe`. I1 used its unchanged CMake
project, empty build type and `-DCMAKE_CXX_FLAGS=-O0`; the full flags/cache are in
provenance. Both source and executable hashes are recorded. Builds and other test
suites completed before measurement; normal uncontrolled OS background noise remains.

Each invocation starts a new native process. Engine order alternates by candidate
and round. Warmups and batch ranking calls are excluded from the timing summaries.
Request construction, normalization and preflight hashing are outside these times;
JSON encoding and response validation are included. Each column is its own median.

| Fixture | Candidates | Samples per engine | Production total ms | CDMCS total ms |
|---|---:|---:|---:|---:|
| One professor | 11 | 33 | 12.4882 | 12.0641 |
| Three professors | 11 | 33 | 12.0047 | 11.9191 |
| Two-day, over-100 fixture | 191 | 573 | 12.1251 | 16.5096 |

For the large case, median Popen creation was 3.3827 / 3.2155 ms and communicate
was 8.5474 / 12.4396 ms (production / CDMCS). Communicate includes remaining OS
startup, transfer, parsing, computation and serialization. CDMCS also encodes and
parses larger prefix/day-array payloads. These results **do not establish an
algorithmic speedup or pure C++ computation timings**. Matched optimized builds,
in-process instrumentation and broader datasets would need separate review.

## Executed verification and gaps

| Check | Actual result |
|---|---|
| I3a unittest discovery with explicit native executable/hash | 35 passed, 0 failed, 0 skipped |
| I1 CTest on fresh matched build | Both suites passed: 618 ordinary + 1 unresolved case, 7202 arrangements, 2504 relocations, 10 invalid differential inputs; 25 safety methods including 84 independent horizon subcases |
| Existing C++ test driver | 192 passed, 0 failed; freshly compiled |
| Existing isolated standalone CSV CLI smokes | 2 passed |
| Existing full Python discovery without database configuration | 493 run: 101 passed, 0 failed, 392 explicitly skipped |
| Existing appointment protocol tests | 5 passed, including real engine and gateway failures |
| Python source syntax / import-use review | 11 files checked in memory; no unused imports identified |
| Protected-file integrity | All 553 protected existing/local files retained identical aggregate SHA-256 |
| PostgreSQL integration / migrations | NOT RUN: I3a explicitly prohibits database access; no database was started or migrated |
| New Linux/MSVC/sanitizer execution / remote CI | NOT RUN in I3a; Windows native verification only, no push authorized |

The prior merged I2.5 Linux/sanitizer/database CI evidence is not presented as an
I3a test run. Full application database workflow coverage remains a separate gate
before any future integration. The original I3a diff contained only I3a files;
I3a.5 additionally updates the existing isolated research CI workflow.

## Remaining boundaries and next stage

This is a synthetic shadow tool, not an appointment creation/approval system.
Roles remain metadata; no live identity, authorization, ownership or consent is
inferred. Real legacy academic-period resolution, capacity/resource constraints,
optional-participant CDMCS ranking, relocations and additional availability are
outside this equivalence claim. Merged/clipped per-person busy unions preserve
fixed feasibility but do not preserve movable group-event identity or arbitrary
original meeting-score semantics. Timeouts fail closed; resource budgets are not
infeasibility certificates. Historical original Python files remain unchanged.

Recommended I3b: separately approve an authorized, read-only calendar projection
that reuses existing application calendar/academic-period services to populate
this one snapshot contract, then shadow-test it without booking writes or changing
the default scheduler. Review privacy, missing data and response/build correlation
before any live activation. No I3b implementation, push, merge or deployment occurs
in I3a.

## I3a.5 CI and PR readiness - 29 October 2026

The six original I3a commits and the measurements above are preserved. Review
found no blocking defect requiring a runtime, serializer, snapshot, engine or
production-application change. Changes are limited to the research workflow,
stronger native tests and these technical documents.

Two additional tests pin the original comparison domain and reverse-project every
paired request to verify identical intervals, mandatory people, busy calendars
and publication windows. Optional invitees remain optional; all excluded/invalid
matrix cases must invoke neither engine. Native tests can explicitly select a
manifest-validated production artifact using `CDMCS_I3A_PRODUCTION`.

| I3a.5 verification | Executed local result |
|---|---|
| I3a tests / strict no-skip CI-equivalent gate | 37 passed, 0 failed, 0 skipped (35 original plus 2 added tests) |
| Paired CLI matrix and exported case hashes | 41 equal, 5 unsupported, 4 invalid; 469 candidate contexts, 391 feasible per engine; no unexplained discrepancies |
| Fresh standalone C++17 / -O0 build and CTest | 2 suites passed; 618 ordinary + 1 unresolved case, 7202 arrangements, 2504 relocations, 10 invalid inputs, 25 safety methods including 84 independent horizon subcases |
| Fresh existing application C++ suite / isolated CSV CLI smokes | 192 passed / 2 passed |
| Complete Python suite with real PostgreSQL 17.11 | 493 run: 492 passed, 0 failed, 1 expected Windows skip for Linux execute-permission behavior |
| Database coverage | Migrations/drift, rollback, concurrency, real backup/restore, all-five-strategy round trips and current Flask workflows executed |
| Schema documentation / Alembic head | 53 tables match; head 0049b; no migration changes |
| Workflow static validation | actionlint passed for both workflows; 9 multiline Bash blocks passed syntax checks; all 3 configure modes passed stubbed flag checks |
| Python syntax | 11 sources checked in memory |
| Protected-file integrity | 554 protected files, including the authoritative backend/manifest and unrelated local inputs/instructions, remained unchanged |
| Original evidence archive | Original I3a ZIP SHA-256 unchanged |
| Remote Linux / new ASan / MSVC / deployment | NOT RUN in I3a.5; publishing is not yet authorized |

The full PostgreSQL run supersedes the earlier I3a database-test gap, without
giving the offline adapter database access. Tests used a newly initialized,
loopback-only disposable cluster, never an operational database. Owned test
schemas were removed and that cluster was stopped after verification.

The existing CI matrix retains Release and fatal ASan/UBSan standalone modes and
adds a separate matched -O0 offline mode with strict nonempty/zero-skip tests and
synthetic raw-evidence retention, including after native test failures when builds
succeeded. Exact-checkout Git trust is process-scoped to the two export/test
steps; no global or wildcard trust is introduced. The application/PostgreSQL
workflow is unchanged. See README for deadlines, resource limits and dependencies.

No additional optimized paired benchmark was added: this checkpoint prioritizes
CI correctness and closing the database-regression gap, without expanding build/
instrumentation tooling. Existing process-dominated -O0 timings are not evidence
of algorithmic speedup. Release standalone correctness coverage must not be
presented as a matched optimized comparison or pure-computation measurement.

**Readiness:** ready to publish a Draft PR after approval, not yet remote-CI
verified or approved to merge. The first push must verify CDMCS release,
sanitizers, offline and application regression jobs. No application integration,
push, PR creation, merge, deployment or I3b implementation occurred here.

Rollback: before merge, close the proposed PR to leave main unchanged. Following
a future approved merge, revert that PR through the normal reviewed Git workflow;
do not rewrite shared history. There are no application schema/data changes or
scheduler-selection changes to reverse.
