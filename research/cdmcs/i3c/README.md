# I3c: controlled internal shadow execution

This module is **disabled by default, synthetic-only and explicitly invoked**.
It registers no routes, hooks, jobs or configuration defaults. It does not select
an application scheduler, query a database, confirm a meeting, obtain approval,
relocate a commitment or request additional availability. Both C++ engines and
the production application remain unchanged.

## Boundaries and reuse

```text
Synthetic JSON fixture                Owned synthetic PostgreSQL fixture
        |                               |
I3a strict parser                 Existing authenticated I3b read-only projection
        |                               |
        |                         Explicit disposable-fixture declaration
        |                         + explicitly prepared synthetic preferences
        +-------------------------------+
                        |
            Bound immutable ShadowInput
                        |
           Existing fixed-calendar normalization
                        |
             Trusted internal serialization
                  /                 \
       pinned CDMCS CLI       manifest-validated production CLI (optional)
                  \                 /
          Bounded private pipes / strict response validation
                        |
           Sanitized aggregate ShadowResult only
```

- `admission.py`: strict synthetic fixture parsing and deliberate admission of an
  already-authorized I3b projection from a disposable **synthetic** test database.
  It preserves database origin, published/busy facts, duration, horizon and exact
  candidate scope. Fresh scope binding catches accidental replacement/widening.
- `serialization.py`: dedicated internal entry point, bound to the admitted
  snapshot and declared candidate. It reuses I3a's private protocol codecs rather
  than duplicating calendar mapping or C++ feasibility rules.
- `runner.py`: explicit enablement, admission/budgets, executable verification,
  paired singleton evaluation and aggregate results. It is participant-role
  independent and contains no new user-role or appointment authorization policy.
- `process.py`: bounded binary stdin/stdout pipes, discarded bounded stderr,
  process limits, timeout/termination/reaping and static error codes.
- The small change in `../i3a/adapter.py` separates common mapping mechanics from
  public synthetic admission. Public normalization still flags database origin;
  **both public serializers also reject that origin directly**, even if passed
  an internally normalized object. The I3a parser/CLI/export guards are unchanged.

There is no new framework, dependency, schema, persistence layer or scheduling
algorithm. I3b authorization remains in `CalendarProjectionService`, including
same-transaction identity checks and coherent PostgreSQL read-only projection.
Optimization starts only after the test explicitly invokes the runner.

The raw-evidence-oriented I3a executor and the production gateway's diagnostic
transport are deliberately not reused: they retain raw output or log diagnostics
and do not enforce these bounded pipes/OS limits. Executable resolution, protocol
validation, normalization and serializers are reused; no scheduling rule is copied.

## Supported comparison domain

One new meeting, fixed protected commitments, identical required participants,
required professor published windows, organizer conflicts and exact minute-aligned
intervals. Optional invitees remain non-blocking, including unresolved invitees.
The existing 15-minute first-professor-window grid, touching-window unions,
cross-midnight and timezone normalization are reused unchanged. Manual off-grid
starts stay explicit. An existing appointment review remains its exact singleton
interval; its authorization never becomes a general search horizon.

Each candidate is independently evaluated by production `action=validate` and a
CDMCS singleton-candidate request. No capped recommendation list is interpreted
as a complete feasible set. Empty candidate universes are explicitly complete
with zero evaluations. Ranking and cost objectives are **not compared** here;
CDMCS proposal permissions must remain empty and normal meeting approval pending.
Nothing in an optimizer response is an approval or booking.

Unsupported: relocation, additional availability, required exclusive resources,
resource-bearing commitments, unsupported/unresolved required calendar facts,
incompatible publication policy, absent prepared required-participant preferences,
and workloads exceeding admission budgets. Requested unsupported capabilities
must be explicitly represented as unsupported information, not silently omitted.

The application has no CDMCS preference model. Missing preferences remain `None`
and cause `unsupported`, not fabricated zero weights. PostgreSQL integration
tests supply explicit fictional `Preference` values with `synthetic-` provenance;
this is not calibration, a default university preference or an application write.

## Privacy, admission and retention

`synthetic_fixture` requires the existing explicit synthetic marker and strict
schema. `synthetic_projection(..., disposable_fixture=True)` is for a trusted
test harness that **owns and populated** the disposable database. The declaration
is not proof that arbitrary input is fictional, a production authorization token
or permission to process real calendars. Python object sealing and opaque IDs are
not a sandbox against malicious trusted code. No live caller is installed.

The runner returns only status, static reason code, complete/evaluated/candidate
counts, feasible counts, discrepancy count and aggregate elapsed timings. It
returns no participant aliases, times, preferences, revisions, titles, raw
payloads, stdout, stderr, paths, SQL or executable diagnostics. It has no logger,
evidence exporter or file-backed payloads. Raw responses are short-lived internal
objects, not securely zeroized memory. Host debuggers, dumps and instrumentation
capturing frame locals remain outside this boundary. Do not enable them on private
calendar processing. Linux child core dumps are disabled.

Exceptions from dependencies are replaced by static outcomes; a failed run never
returns a partial feasible result as complete. Outcomes distinguish `disabled`,
`busy`, `input_error`, `unsupported`, `engine_failure`, `match`, `discrepancy` and
`cdmcs_only`. A complete match with zero feasible intervals means **infeasible on
that declared candidate universe**, not an engine failure. `cdmcs_only` is not a
cross-engine parity claim. Any discrepancy requires investigation, not an approval.

## Resource and process limits

| Boundary | Initial maximum/default |
|---|---|
| Concurrent runs | One per Python process; nonblocking busy failure |
| Candidate universe | 256; reject, never silently truncate |
| Pre-normalization | 32 participants, 2,000 commitments, 2,048 published windows, 10,000 memberships, 200,000 required-person prefix entries |
| Child request / each output stream | 4 MiB / 64 KiB |
| Child wall time / whole run | 5 seconds / 120 seconds, configurable downward (child maximum 10 seconds) |
| Child memory | 256 MiB by default; configurable 64 MiB-1 GiB |
| Executables | Explicit CDMCS SHA-256 pin; existing production source/manifest/binary validation; hashes rechecked each call |

Linux uses `prlimit` for address-space/CPU/core limits, a dedicated process group
and group kill/reap on failure. Unsupported POSIX platforms fail closed when
`prlimit` is unavailable. Windows uses a Job Object with process-memory,
one-active-process and kill-on-close limits, plus wall deadlines. Limit setup must
succeed **before sending stdin**; these trusted CLIs wait for a complete document.
This is not a sandbox for arbitrary hostile executable bootstrap code. Windows
venv redirectors that spawn another interpreter are intentionally not compatible
with the one-process job limit; the actual C++ binaries do not spawn children.
Multiple external Python workers require future deployment-level admission
control; the present per-process gate is not a distributed quota.

Input serialization, remaining child startup, JSON parsing, IPC and output
validation contribute overhead. `launch_ns` measures Popen construction only;
`exchange_ns` includes limit setup, remaining startup, I/O, computation, parsing
and thread cleanup. Neither is isolated optimizer CPU time. No speedup claim is
supported. Hash checks and normalization are not included in these two subtotals.

## Verification

Use the pinned existing dependencies and a disposable synthetic PostgreSQL
database only. Set `TEST_DATABASE_URL`, `PYTHONDONTWRITEBYTECODE=1`,
`PYTHONTZPATH=''`, `CDMCS_I3A_BINARY`, its `CDMCS_I3A_SHA256` and optionally
`CDMCS_I3A_PRODUCTION` (a manifest-validated artifact).

```text
python -B -m unittest discover -s research/cdmcs/i3c/tests -v
python -B -m unittest discover -s research/cdmcs/i3b/tests -v
python -B -m unittest discover -s research/cdmcs/i3a/tests -v
```

An explicit offline invocation uses only an existing fictional fixture:

```python
import os
from research.cdmcs.i3a.fixtures import basic
from research.cdmcs.i3c.admission import synthetic_fixture
from research.cdmcs.i3c.runner import ShadowRunner

runner = ShadowRunner(os.environ["CDMCS_I3A_BINARY"],
                      os.environ["CDMCS_I3A_SHA256"], enabled=True)
summary = runner.run(synthetic_fixture(basic()))
```

Native/database tests explicitly skip without their prerequisites; skips are not
verification. Tests cover the complete existing 41/5/4 synthetic matrix,
singletons beyond top-K, protocol/permission failures, process timeout/crash/output
flooding/memory exhaustion, no raw logging, admission/concurrency/deadlines,
database-origin export denial, authentication denial and all-table/sequence
fingerprints before/after an explicit real-C++ comparison.

### Executed local verification: 31 October 2026

Windows, Python 3.12.14, GCC 14.3.0, PostgreSQL 17.11 and pinned tzdata 2026.5.
Only an owned loopback PostgreSQL cluster and random disposable schemas were used.
The standalone CDMCS binary was freshly compiled with CMake Release/C++17.

| Check | Actual result |
|---|---|
| I3c | 41 passed, zero failed/skipped: 31 admission/process/orchestration, five native and five PostgreSQL tests |
| Complete synthetic matrix | 41 supported equality cases (one empty universe), 469 candidate contexts, 391 feasible per engine, five unsupported and four invalid cases; zero unexplained discrepancies |
| I3b | 47 passed, zero failed/skipped; repeated against committed implementation |
| I3a | 37 passed, zero failed/skipped; independent exhaustive witnesses and ranking-separation regressions retained |
| Standalone CDMCS | 2/2 CTest suites: 618 differential cases, one unresolved case, 10 invalid inputs, 25 safety tests including 84 independent horizon subcases; original source checksums verified |
| Existing application C++ | 192 passed, zero failed; two standalone CSV CLI smokes passed |
| Full application Python/PostgreSQL | 501 run in 2487.709 seconds: 500 passed, zero failed, one expected Linux-only execute-permission skip on Windows; all eight identity regressions passed |
| Schema documentation | All 53 application tables match; no schema/migration change |

The full suite exercised migrations/drift, isolated backup/restore, rollback,
concurrent reservations, all five allocation strategies, JSON/CSV compatibility,
Flask workflows, appointments, equipment, calendars, recurrence, feedback and
waiting lists. No PostgreSQL test was skipped; Alembic head remains `0049b`.

Five measured paired runs after one warmup per fixture gave median whole-run wall
times of 1331.84 ms (one professor), 1400.62 ms (three professors) and 598.64 ms
(four manual off-grid candidates). Corresponding aggregate Popen/exchange medians
were 131.29/277.22 ms, 126.34/288.75 ms and 41.90/98.56 ms. Other regression
processes were active. These are overhead-dominated **path measurements**, not an
isolated benchmark: the canonical production artifact is `-O0`, CDMCS is Release,
and pure optimizer CPU time is not separately measured. No speedup is inferred.

No Linux, new sanitizer, browser or remote CI execution is claimed for this stage.
Windows Job Object limits were actually exercised, including a refused 1 GiB
allocation inside a 128 MiB child budget. Linux `prlimit` awaits platform CI;
ASan's large virtual shadow mapping is incompatible with this address-space cap,
so sanitizer verification must remain a separate appropriately budgeted job.

## I3c.5 release review

The first I3c checkpoint above remains the historical verification of `e5a8175`.
The independent review added two reproduced safety corrections, without changing
either scheduling engine or its hard constraints:

| Confirmed finding | Correction and regression |
|---|---|
| An I/O thread-start failure could make cleanup join an unstarted thread, masking the failure and leaving pipes open | Track only successfully started threads; return static `THREAD_START`; test each of the three start positions, closed pipes, child reaping and sanitized exception chains |
| An empty candidate universe could return success after the whole-run deadline expired | Check the deadline after preparation and before returning completion, including empty universes |

Source guards still enforce synthetic declaration, immutable scope, unchanged
database origin, missing-preference rejection and blocked public I3a export.
Authentication grants a projection context, not execution rights. The test-only
declaration is not a new permission or proof against arbitrary trusted Python.
Configured executables remain constructor/configuration inputs, not snapshot or
HTTP request fields; no shell or calendar-bearing command arguments are used.

### Performance assessment

`benchmark.py` is an explicitly invoked synthetic-only harness. It accepts no
calendar input file or database connection. It checks exact parity and counts
actual launches, hash calls/bytes, partial startup and exchange wall time. Windows
also supplies child CPU and peak working-set measurements through OS counters.
CPU includes startup and native JSON parsing/serialization as well as scheduling;
**scheduling computation alone is not measured**. Linux reports cumulative child
CPU and cumulative maximum child RSS, not per-case peak RSS. Missing counters
remain null, not zero. Compiler flags and source/binary hashes accompany evidence.

```text
python -B -m research.cdmcs.i3c.benchmark --cdmcs <binary> --cdmcs-sha256 <hash> --production <manifest-validated-binary> --candidates 1 8 32 128 --repetitions 3 --warmups 1
```

There are exactly `2N` subprocesses for `N` candidates, never overlapping inside
one run. The original loop also rehashed the unused peer before each launch:
`4N+1` runner hash calls versus the corrected `2N+1` (plus unchanged production
manifest/source validation). Each executable is still verified immediately before
its own launch. A mutation between paired calls still aborts the complete run.

| Candidates | Original wall ms | Corrected wall ms | Matched Release wall ms |
|---:|---:|---:|---:|
| 1 | 287.68 | 329.56 | 220.35 |
| 8 | 991.10 | 1051.99 | 654.08 |
| 32 | 3785.13 | 3061.06 | 1795.62 |
| 128 | 15582.26 | 11572.97 | 7820.60 |

Medians use three trials after one warmup: one required professor, fixed empty
busy calendars and all-feasible explicit starts. Original/corrected columns use
the same canonical production `-O0` and CDMCS Release artifacts. The last column
uses separately built **both `-O3 -DNDEBUG`**, outside the checkout, with their
actual flags recorded. Background regressions were active: small cases were
noisy and these are not causal or algorithmic speedup measurements.

At 128 candidates the redundant-hash correction reduced runner executable reads
from about 1644.77 MiB to half that amount. The matched Release experiment observed
one active child maximum and 5.17 MiB maximum child working set across its cases.
Mean combined child CPU was 31.25/322.92/1270.83/5578.12 ms for the four sizes;
Windows accounting is quantized. This is not peak parent memory or a worst-case
inventory/calendar benchmark. Large prefixes are retransmitted for every singleton,
so path growth includes `O(N * horizon)` transport, not just optimizer work.

Singletons remain intentionally unchanged. A future bounded CDMCS batch of at
most 100 fixed candidates could reduce startup/transport work, but needs a separate
complete-output and resource-failure review; a capped result must never silently
replace complete singleton feasibility. Parallel execution is not enabled.

### CI and platform boundary

The existing disposable PostgreSQL job now builds a SHA-verified Boost 1.85.0
Release CDMCS, runs both standalone CTest suites against **that binary**, pins its
SHA-256, preserves the 55-test I3b/identity gate and requires every I3c test group
with zero skips. The existing I3a/Release/ASan-UBSan workflow also triggers on I3c
changes. Application C++/Python/PostgreSQL regressions remain enabled. Permissions
stay read-only; there are no deployment steps or projection/shadow artifact uploads.

The I3c child is Release, **not sanitizer-instrumented**. ASan/UBSan executes only
in the existing separately instrumented standalone job with suitable virtual
memory. Workflow parsing, shell/Python syntax checks and Windows test runs do not
prove hosted CI success. Publication is required before those jobs can execute.

Windows/MinGW Job Object limits are locally tested; Windows/MSVC hosted coverage
is not added. Linux `prlimit` awaits actual hosted execution (no local Docker/WSL).
Windows limits committed process memory; Linux limits virtual address space, not
RSS. Windows prevents descendant processes; Linux relies on the audited no-fork
CLIs, process-group termination and the CI container's PID limit. Abrupt parent
death on Linux requires external process/container supervision; there is no
claim of Windows Job Object-equivalent parent-death enforcement. Normal timeout,
crash, output-flood, memory-exhaustion and thread-start cleanup are regression-tested.
Whole-run checks are cooperative during Python preparation; arbitrary blocked
filesystem/kernel calls are not preemptible by this wrapper. An outer job/service
supervisor is still needed, in addition to the child-process deadline.

### Executed I3c.5 verification: 31 October 2026

Same Windows/Python/GCC/PostgreSQL/tzdata versions as above, with a new isolated
synthetic cluster and fresh Release engine. No operating database was used.

| Check | Actual result |
|---|---|
| Complete I3c CI-equivalent gate | 47 passed, zero failed/skipped: original 41 retained plus six review/benchmark regressions |
| I3b PostgreSQL + identity CI-equivalent gate | 55 passed, zero failed/skipped |
| I3a offline regressions | 37 passed, zero failed/skipped; original 41/5/4 matrix and 469/391 counts unchanged |
| Fresh standalone Release | Both CTest suites passed: 618 differential cases, one unresolved, 10 invalid, 25 safety tests/84 independent horizon subcases |
| Complete application C++ | 192 passed, zero failed; both CSV CLI smokes passed |
| Complete application Python/PostgreSQL | 501 run in 2314.224 seconds: 500 passed, zero failed, one expected POSIX execute-permission skip on Windows; no PostgreSQL skips |
| Schema | All 53 tables match documentation; migrations/drift and backup/restore tests passed; Alembic head unchanged at 0049b |
| Workflow static verification | Both workflows pass actionlint; 17 Bash blocks, three embedded Python programs and I3c Python source syntax pass |

The two failure regressions failed on the original implementation before the
corrections; their failing evidence is preserved separately from final green runs.
No previous tests or safety budgets were removed or weakened. Hosted/Linux and
new sanitizer verification remain **not run**, pending separately authorized
publication. This is readiness for a draft PR, not approval for live calendars.

## Approval gates before real-data shadow execution

This stage does **not** authorize real-calendar execution. A separately reviewed
stage must establish:

1. Who may initiate shadow evaluation; exact permitted calendars, contexts and
   horizons; fresh authorization/revocation behavior. No professor/admin/committee
   initiation rights are inferred from generic DTO support.
2. An actual prepared preference source and meaning (or a reviewed independent
   feasibility-only engine operation). Synthetic weights cannot become defaults.
3. Private data handling/retention, aggregate visibility, access controls, error
   monitoring, incident response and safe observability without raw locals/logs.
4. SQL statement/row/query budgets, snapshot age limits, cross-worker admission,
   CPU/memory/process supervision and operational monitoring.
5. Separately approved live workflow integration, rollout and stop/rollback gates.
   Any future booking still uses existing fresh validation, approvals, locks and
   transactional publication; a shadow proposal never reserves a resource.

Next recommendation: review this isolated boundary and add Linux/Windows CI
verification before considering any separately authorized real-data experiment.
