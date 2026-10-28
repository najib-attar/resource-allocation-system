# I2 isolated integration review

## Scope and provenance

Reviewed on 2026-10-28 against application base
`5b9f7eeaa7889f570cbfa984f20dbb24ad4fcb91`. All additions are under
`research/cdmcs/i1/`. I2.5 adds one separate research-verification workflow under
`.github/workflows/`; the engine remains isolated. No production source, Flask routes, PostgreSQL model,
migration, application test, dependency list, or appointment workflow changes.
The production builder/freshness manifest scans `src/`, not `research/`.
After verification, SHA-256 checks confirmed all 520 protected preexisting files
unchanged, including generated CSVs and local instructions. The original Python
reference hashes also match the staged Git blobs; a local `.gitattributes` rule
prevents checkout-time newline conversion from invalidating those hashes.

Supplied archive: `CDMCS_CPP_I1_Standalone_Cpp_Engine.zip`, SHA-256
`fc6ad8331e83595e1bc44f7e19312ae2d481fe7ccde0c6967cbe67a4382e1604`.
All 15 entries in its manifest matched before testing. The retained
`UPSTREAM_SHA256.json` is that original manifest; it is not a checksum list for
the hardened copy. All three Python reference files remain byte-identical.
Checksums establish supplied-file integrity, not independent authorship or a
historical research Git revision.

Original generated results, the redundant 195 KB generated minimal example,
example generator and internal engineering log were not imported. A compact
synthetic example remains. No generated executable, build tree, database, dump,
credential or private development instruction belongs in this directory.

## Confirmed corrections

| Finding | Reproduction / correction |
|---|---|
| Signed overflow in day-delay subtraction | Original binary ranks start 1 before 0 for days INT32_MIN/INT32_MAX. Widen before subtracting; later delay is correctly 21474836475 at weight 5. |
| Unbounded stdin before parsing | Original accepts a valid document with over 16 MiB of padding. Bound ingestion before DOM allocation. |
| Windows text-mode protocol truncation | Reproduced valid JSON plus Ctrl-Z plus trailing garbage being accepted, and CRLF reducing counted bytes. Use binary stdin/stdout on Windows; reject hidden trailing data and count raw bytes. |
| Unbounded collections and replacement-copy amplification | Limit ID length, memberships, window counts, total calendar entries and copied replacement-cache members. An originally accepted 1000-replacement/256-resource case now fails cleanly. No multi-gigabyte stress run was attempted. |
| Excessive window/key/scoring work | Add a per-solve logical work budget. Over-budget execution produces no partial result or false infeasibility claim. |
| Incomplete unresolved-result metadata | Return zero returned count and false truncation along with the existing empty recommendations. |
| Errors indistinguishable from malformed input | Keep exit 2 for validation/budget failures; add ENGINE_ERROR/exit 3 for internal/allocation failures. No automatic booking follows any result. |
| Verification rewrote source-tree examples | Test output is now stdout by default, with optional explicit report destination. Oracle imports are pinned to the included verified files. |
| Incomplete differential assertions | Verify exact permission lists, end times, output counts and truncation, plus spring DST, touching publication windows and unresolved relocation participants. |
| Locale-dependent oracle subprocess decoding | A returned Unicode meeting ID was corrupted under Windows cp1256. Decode protocol output explicitly as UTF-8 and retain a quoted/newline/Unicode relocation-ID case. |
| Complexity omitted window scans and copied memberships | Document actual linear windows, quadratic membership comparison and cache-space terms, plus budget-qualified exactness. |

The search universe, candidate grid, objective, fairness tie order, one-blocking-
move restriction and permission semantics are unchanged for completed requests.
Bounds intentionally reject excessive inputs rather than approximate them.
Signed score calculations are comfortably inside int64 after the widening fix:
even a full signed-32-bit day difference times maximum delay costs under 4.3e16;
bounded affected-person deltas keep the combined magnitude below 5e16.

## Preserved reference discrepancy

V15 `exception_requests()` checks the horizon inside the person loop. For a
resource-only event there is no iteration. With H=4, a flexible resource event
X=[0,2), a requested [0,1) event using that resource, and replacement start 3,
V15 `exhaustive()` can propose X=[3,5). The C++ engine correctly excludes it.
The supplied differential runner already filtered replacements extending past H.
That guard is now explicitly documented and independently tested alongside the
unmodified reference witness. Therefore results demonstrate agreement on the
documented bounded model, NOT unrestricted equality with every V15 behavior.
No original research algorithm was silently repaired.

### Minimal reproducible boundary case

The complete, synthetic input is
[`examples/resource_only_horizon_request.json`](../examples/resource_only_horizon_request.json).
It uses H=4, NEW=[0,1) requiring A and R, and flexible X=[0,2) requiring only R.
Only replacement start 3 is supplied. All preference costs are zero; the fixed
move cost is 20. The original reference returns `(20, 0, 0, 'X', 3)`.

The independent expected answer is **no feasible arrangement**: retaining X
conflicts with NEW on R; moving X gives [3,5), which ends beyond H=4. This proof
uses interval inequalities, not the reference implementation or its wrapper.
The actual C++ response is exit 0 with:

```json
{"operation":"cdmcs_schedule_v1","model":"V15_restricted_one_blocking_move","status":"NO_FEASIBLE_PROPOSAL","solutions_evaluated":0,"returned_count":0,"truncated":false,"recommendations":[]}
```

The adjacent boundary controls use the same H, NEW and X:

| Replacement start | X after relocation | Independent expected result |
|---|---|---|
| 0 | [0,2) | Infeasible: overlaps NEW on R |
| 1 | [1,3) | Feasible: half-open adjacency; cost 20, fairness 0 |
| 2 | [2,4) | Feasible: ending exactly at H is permitted |
| 3 | [3,5) | Infeasible: exceeds H |

The C++ guard in `src/cdmcs_i1.cpp:376` precedes participant availability checks
and applies even when `people` is empty. No algorithm correction was necessary.
`test_hardening.py` now separates the original-reference defect witness from
oracle-free C++ assertions. It exhausts 84 small horizon/duration/replacement
tuples and checks a mixed candidate list retains only valid replacements.
The historical V1/V3/V15 files remain byte-identical to their manifest.

From the repository root, after building as described in the README:

```text
python -B research/cdmcs/i1/tests/test_hardening.py --binary <executable> SafetyTests.test_resource_only_relocation_stays_inside_horizon SafetyTests.test_historical_python_resource_only_horizon_counterexample -v
```

## Verification

Toolchain: Windows x64, GCC/MinGW 14.3.0, CMake 4.0.2, Boost 1.85.0,
Python 3.12.14 and tzdata 2026.5. Boost's official archive hash was verified.
The Windows tar utility warned about two empty/unreadable archive entry names;
required headers were extracted and both independent CMake builds succeeded.
No C++ compiler warnings were emitted in the executed builds.

- Unchanged I1: 614 ordinary cases + one unresolved case; 7198 feasible
  arrangements, including 2503 relocations; 10 invalid inputs rejected. This
  reproduced the supplied result counts exactly.
- Before hardening: the first 12 new tests had 6 passes, 5 failures and 1 metadata
  error, reproducing the gaps without exhausting the machine.
- Hardened Release and checked Debug verification includes independent V15
  all-pairs/full-cost comparison; final counts are recorded below.
- Checked Debug uses `-ftrapv -D_GLIBCXX_ASSERTIONS`. These are signed-overflow
  traps and library assertions, NOT AddressSanitizer/UndefinedBehaviorSanitizer.
  Those runtimes and a Linux/WSL environment were unavailable; cross-platform
  execution and full sanitizer coverage are not claimed.

Accepted I2 implementation checkpoint gate, executed on the final C++ source:

| Check | Actual result |
|---|---|
| Release CMake build / checked Debug build | Both passed; no compiler warnings |
| Differential suite, each build | 618 ordinary cases + 1 unresolved case; 7202 feasible arrangements, 2504 relocations, 10 invalid inputs; zero score/permission/count mismatches |
| Boundary/safety suite, each build | 20 passed, 0 failed |
| CTest, each build | 2 registered suites passed, 0 failed |
| Existing application C++ suite | 192 passed, 0 failed, freshly compiled |
| Existing isolated CSV CLI smokes | 2 passed (clean-slot and normal-dataset) |
| Full application Python suite with real PostgreSQL | 493 run: 492 passed, 0 failed, 1 expected Windows skip for POSIX executable permission semantics |
| PostgreSQL coverage | Fresh schema/migrations, drift, rollback, concurrent actors, backup/restore, all five strategy parity tests and existing Flask workflows executed in an owned disposable cluster |
| Schema documentation check | Matched all 53 current application tables |
| Production backend manifest/freshness | Verified unchanged source hash `039a9fb90fadf260f3190b91867b9fabad5e40ae230cd8e2d2f769556e212221` |
| Python syntax / synthetic demo | 5 Python sources compiled in memory; demo returns 5 pending proposals |

The initial no-database Python discovery had 101 passes and 392 explicit skips;
it was superseded by the real-PostgreSQL run above, not reported as full coverage.
Two additional Windows wire-format regressions and a Unicode differential case
were observed failing before their respective fixes. ASan/UBSan, MSVC, Linux and
remote CI were not run. No machine-exhaustion experiment was attempted; controlled
limit tests verify explicit failure without partial publication. Real allocation
failure/OS kill behavior remains best-effort, not fault-injection verified.

The original score objective is unchanged. The scope of the differential result
is top-100 ordered results plus complete arrangement counts under the harness's
explicit bounded-horizon guard. It is not a comparison with the university
appointment scheduler, nor a general proof of algorithmic superiority.

### Release-readiness recheck

Commit `00ffc095830b6eddc12e60b5afe85a2a9bede8f7` contains 16 additions, all
under `research/cdmcs/i1/`. This follow-up adds the minimal synthetic input and
strengthens only research tests/documentation; the C++ implementation is unchanged.
The refreshed remote main and local main matched during this review.

- Fresh Release and checked Debug rebuilds passed without compiler warnings.
- Each build passed both CTest suites: 618 ordinary differential cases plus one
  unresolved case, 7202 arrangements including 2504 relocations, 10 invalid
  differential inputs, and 24 safety test methods including 84 oracle-free
  resource-only boundary subcases. No failures or mismatches occurred.
- Existing application appointment-protocol tests: 5 passed, 0 failed. The
  production executable's source/hash freshness validation still passes.
- Input types, identifiers, interval bounds, baseline conflicts, prefix/window
  constraints and budget/error paths were re-reviewed. Limits are logical/input
  bounds, not guaranteed peak RSS or wall-clock limits. Budget failures return
  no partial top-K; int64 arithmetic remains within the documented numeric bounds.
- An allowed resource-only move remains `CONDITIONAL_PENDING_APPROVAL` even with
  an empty person-permission list. Resource ownership/authorization is not modeled
  as consent by this CLI; empty lists never authorize a resource move or booking.
- The prior full 192-test C++ and 493-test PostgreSQL/Python results above are
  checkpoint evidence, not a claim that those complete suites were rerun during
  this test/documentation-only review. No database was accessed in this recheck.
- Review found no committed executables, build directories, runtime logs, database
  files, credentials or private instructions. JSON examples are intentional
  fictional input fixtures, not operational state.

**Decision:** ready for a PR as an isolated research prototype, not for production
activation. The resource-only horizon boundary is verified safe in C++; the
historical Python defect remains a documented reference limitation. At that
checkpoint, GitHub workflows did not run the separate research CTest target; no remote CI
result or PR publication is claimed. Linux/MSVC and ASan/UBSan remain unverified.

## I2.5 CI verification and PR preparation

The separate `.github/workflows/cdmcs-research-verification.yml` defines two
Ubuntu 24.04 jobs: native Release and ASan/UBSan Debug. Path filters cover this
research subtree and the workflow itself, with optional manual dispatch. The
existing application/PostgreSQL workflow is unchanged. No deployment, production
engine selection, application dependency or database migration is introduced.

Each job uses a disposable Ubuntu container limited to 3 GiB physical memory,
no swap allowance, two CPUs and 256 processes. A 20-minute job timeout, bounded
installation/build steps, 300-second CTest suite timeouts and existing 20/25-second
engine subprocess timeouts prevent indefinite test runs. ASan's large virtual
shadow mapping is not restricted with `ulimit -v`; the memory limit applies at
the container/cgroup boundary instead. See the official
[ASan limitations](https://clang.llvm.org/docs/AddressSanitizer.html#limitations)
and [Docker resource constraints](https://docs.docker.com/engine/containers/resource_constraints/).

Boost 1.85.0 is verified against its pinned archive SHA-256. The isolated Python
environment installs only `requirements-test.txt`; `PYTHONTZPATH` is empty so
the reference uses pinned tzdata 2026.5 rather than an OS-provided version.
The sanitizer job compiles and links with `-fsanitize=address,undefined`, frame
pointers, fatal sanitizer settings and disabled sanitizer recovery. Both jobs
execute the full differential and safety suites, including the independent
resource-only horizon boundary tests. Empty test discovery fails. The final
checkout must remain clean. Failed jobs retain only the synthetic CTest log
for seven days; checkout credentials are not persisted and token permissions
are restricted to `contents: read`.

The safety harness now includes engine exit status and bounded stderr when
stdout is not JSON. Its additional regression injects a simulated sanitizer
diagnostic to verify reporting; this is **not** a sanitizer execution claim.
The current safety suite contains 25 test methods, including the unchanged
84-case oracle-free horizon matrix.

Local static verification passed with actionlint 1.7.12 and Bash syntax checks
for all seven run blocks. Stubbed configure-command checks verified both matrix
branches select C++17/testing and sanitizer flags as intended. Native MinGW
Release and checked Debug builds/tests passed. **Ubuntu/container execution,
ASan/UBSan and remote GitHub Actions have not run**: this Windows machine has no
Docker executable or installed WSL environment, and publishing is not authorized.
The first approved push must verify both research matrix jobs and the existing
application regression job before merge. Hosted Windows/MSVC CI is deliberately
deferred rather than presented as reliable untested coverage.

I2.5 final local verification (2026-10-28):

| Check | Executed result |
|---|---|
| Research Release / checked Debug builds | Both freshly rebuilt successfully; no compiler warnings observed |
| Research CTest, each build | 2 suites passed; 618 ordinary + 1 unresolved case, 7202 arrangements, 2504 relocations, 10 invalid differential inputs, 25 safety methods including 84 horizon subcases |
| CI-equivalent native configuration | Strict C++17, extensions off, pinned Python timezone data, serial CTest and timeout/no-empty-test options passed locally |
| Workflow validation | actionlint 1.7.12 passed for both workflows; 7 Bash run blocks passed syntax checks; both configure flag branches passed stubbed command checks |
| Existing C++ regression suite | 192 passed, 0 failed; freshly compiled |
| Existing standalone CSV CLI smokes | 2 passed |
| Full application Python/PostgreSQL regression | 493 run: 492 passed, 0 failed, 1 expected Windows POSIX-permission skip; isolated cluster, not the operational database |
| Migration/drift, parity, recovery and concurrency | Executed by the full suite; all five strategy comparisons, real backup/restore and concurrent actor tests passed |
| Schema documentation | Matches all 53 application tables |
| Ubuntu / ASan / UBSan / hosted Windows | NOT RUN locally; Docker/WSL Linux infrastructure unavailable; no remote execution before an approved push |

The disposable PostgreSQL server was stopped after verification. The research
engine source, historical Python references, application scheduler, Student
Service 1, Flask routes, PostgreSQL models/migrations, application requirements
and existing application CI workflow remain unchanged. Only the isolated workflow,
research test diagnostics and research documentation changed for I2.5. A PR title,
description, verification results, limitations and rollback notes are prepared
locally; no branch was pushed and no PR was opened.

### Rollback

Before merge, closing the proposed PR leaves main unchanged. After a future
approved merge, revert that PR through the repository's normal revert workflow;
do not reset or rewrite shared history. No schema, operational data, production
configuration or application behavior needs a rollback because none changed.
The two accepted I2 commits are retained without amendment or rebasing.

## Remaining limits and next integration decision

This remains a standalone proposal engine. A completed result is not permission
to move an event, use extra availability, or reserve a room. Top-K output is not a
complete feasible set; counts concern arrangements, not distinct meeting starts.
No claims of speedup, universal optimality or human-valid preference weights are
supported by these tests. Resource limits are engineering policy, not constraints
in the mathematical scheduling problem. OS termination/out-of-memory and stalled
input still require a caller timeout/process policy.

The required nondecreasing local-day array excludes historical zones whose
clock rollback crosses the civil-date boundary. An actual tzdata witness for
America/St_Johns on 2010-11-07 moves from 00:00 to the previous day's 23:01;
the engine explicitly rejects that mapping. Istanbul and the tested Berlin
spring-gap/fall-fold mappings are supported, but universal historical timezone
coverage is not claimed. No fabricated dates or offsets were introduced.

The existing `EngineGateway._execute()` has useful subprocess/timeout patterns,
but cannot consume this contract unchanged. Production uses epoch seconds,
correlation/build metadata, different statuses, optional-invitee ranking and
published-window normalization. Research uses anchored UTC minutes, supplied
cost/day arrays, resources, movable meetings and explicit conditional permissions.
No adapter or flag was added to the gateway or production `main.cpp`.

The next safe milestone is an explicitly approved offline snapshot adapter and
shadow comparison: define the UTC anchor and truthful date/availability mapping,
reject precision loss, version/correlate requests, validate responses, preserve
existing scheduler selection and expose no booking side effects. Live approvals,
relocation permissions, privacy and transactional revalidation need their own
approved design before activation. This work is not blocked for isolated research
use; it is not authorization or certification for production deployment.

## Added files

All paths below are relative to `research/cdmcs/i1/`; no existing tracked file
outside this subtree was modified.

| File | Responsibility |
|---|---|
| `src/cdmcs_i1.cpp` | Standalone proposal engine and hardened JSON boundary |
| `CMakeLists.txt` | Independent target and two CTest suites |
| `.gitattributes` | Byte-preserving reference checkout |
| `.gitignore` | Standalone build/bytecode exclusions |
| `requirements-test.txt` | Pinned test-only IANA timezone data |
| `tests/test_differential.py` | V15 exhaustive/full-score oracle, counts and permissions |
| `tests/test_hardening.py` | Boundary, numeric, Windows-wire, resource and provenance regressions |
| `tests/original_reference/cdmcs_v1_reference_prototype.py` | Unchanged shared research meeting/index primitives |
| `tests/original_reference/cdmcs_v3_weekly_cost.py` | Unchanged V15 research dependency |
| `tests/original_reference/cdmcs_v15_minute_domain.py` | Unchanged minute-domain independent reference |
| `examples/demo_request.json` | Fictional standalone input with conditional proposals |
| `examples/resource_only_horizon_request.json` | Minimal resource-only relocation counterexample with independently derived expected result |
| `README.md` | Scope, reproducible build/run/test instructions |
| `docs/JSON_CONTRACT.md` | Fields, statuses, numeric/resource bounds and semantics |
| `docs/CORRECTNESS_AND_COMPLEXITY.md` | Restricted exactness and actual computational costs |
| `docs/UPSTREAM_SHA256.json` | Original archive manifest, not a hardened-tree manifest |
| `docs/REVIEW.md` | Findings, corrections, actual verification and integration limits |
