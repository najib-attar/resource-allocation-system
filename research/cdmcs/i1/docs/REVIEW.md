# I2 isolated integration review

## Scope and provenance

Reviewed on 2026-10-28 against application base
`5b9f7eeaa7889f570cbfa984f20dbb24ad4fcb91`. All additions are under
`research/cdmcs/i1/`. No production source, Flask routes, PostgreSQL model,
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

Final gate, executed on the final C++ source:

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
| `README.md` | Scope, reproducible build/run/test instructions |
| `docs/JSON_CONTRACT.md` | Fields, statuses, numeric/resource bounds and semantics |
| `docs/CORRECTNESS_AND_COMPLEXITY.md` | Restricted exactness and actual computational costs |
| `docs/UPSTREAM_SHA256.json` | Original archive manifest, not a hardened-tree manifest |
| `docs/REVIEW.md` | Findings, corrections, actual verification and integration limits |
