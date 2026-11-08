# Administration Services v1 — final acceptance record

**Approved Administration v1 scope verified locally and ready for Draft PR review.**

Date: 2026-11-08. Branch: `feature/admin-services-v1`.
Reviewed base: `aae966bf8fa6390348c6e6a2d53a24faf6c0ab70`, the released integrated
Student/Professor beta. Final application code checkpoint:
`b6c9c78bbf9021aa36fdec539797bf499e019c96`. Subsequent acceptance changes are
documentation and six representative screenshots. No merge or deployment is authorized
by this report; the deliverable is a Draft PR for user review.

## Iteration outcomes

| Phase | Delivered / reused | Focused verification | Commit |
| --- | --- | --- | --- |
| ADM-B0 | All twelve contracts audited; existing source/authority/engine paths mapped | Source audit; zero tests claimed | `e6e6909` |
| ADM-B1 | Existing eligibility, revisions, all allocation entry points and calendar publication retained | 77/77 | `daecc18` |
| ADM-B2 | Existing scoped rooms, inventory/custody, queues, recurrence and feedback retained | 187/187 | `f446e30` |
| ADM-B3 | Bounded, consistent read-only Home/report/run-history service | 11/11 plus two history and two boundary cases | `0db8d03` |
| ADM-B4 | Sensitive account/resource/permission extensions explicitly deferred | Source/permission review, zero tests claimed | `5f6af41` |
| ADM-B5 | Independent backend acceptance before frontend | 752 distinct cases reconciled as 751 passed/one expected skip; initial fixture error and corrected module fully documented | `54111d3` |
| ADM-UI-01 | Campus Space Administration Home, real queues/empty states, dedicated login landing and compact navigation | 35/35; populated and empty browser phases | `3796b88` |
| ADM-UI-02 | Academic review, strategy, current results and persisted run history | 44/44 plus 6/6 history; real engine/stale-review browser | `77c265d` |
| ADM-UI-03 | Scoped room/equipment policies, custody/inventory and read-only directory search | 39/39 plus 1/1 directory; real approval/handover/partial return | `b7658a0` |
| ADM-UI-04 | Existing calendar bindings/publication, waiting/recurring policy and private issues | 96/96; publication, queue assignment, response and clarification browser | `d4b5a3e` |
| ADM-UI-05 | Bounded read-only reports and recipient-scoped Inbox guidance | 40/40; real single/bulk/repeated read and foreign-ID denial | `c3d7b4c` |
| ADM-UI-06 | Independent full pipeline, cross-role audit and safe cleanup | Final results below and [iteration report](iterations/ADM-UI-06.md) | `fdeaba6`, `d6919cb`, `ddcdb40`, `04b1270`, `b6c9c78` |

The [use-case matrix](traceability.md), [screen inventory](screen-coverage.md) and
[complete control-to-persistence matrix](integration-verification.md) define the
approved implementation. UC-01/11 are new read composition, UC-02 adds supported
literal directory search, UC-03 retains its existing trusted CLI and defers its
unapproved browser extension, and UC-04–10/12 preserve authoritative existing
services. There are no unsupported functional placeholder controls.

## Final regression gates

Fresh full Python/PostgreSQL discovery: **763 run, 762 passed, zero failures,
zero errors, one expected Windows platform skip**, **1377.70 seconds**. All 58
discovered modules completed successfully on the final application code. The
skip is `test_linux_execute_permission_is_checked`, which runs on Linux.

C++: **192 passed, zero failed**; both actual runtime smokes passed. Schema catalog:
all **62 application tables** match. Node syntax checks passed for the changed
browser harness and duplicate-submit script. **124 local Markdown links/anchors**
resolve. Changed Python/Jinja syntax and known secret-pattern scans passed;
source scope was reviewed. These automated scans supplement source review and do
not claim to detect every possible secret format.

The full Python discovery includes authentication/revocation/logout, five-role
authorization, IDOR/CSRF, PostgreSQL locking/concurrency and publication failures,
fresh/legacy eligibility migrations, session migration/rollback, room/equipment/
waiting/feedback/recurrence, Student/Professor workflows, adapters, CLI, gateway,
private preferences and inactive cost-policy/governance regressions. No useful
test was removed or weakened to suppress a supported-function failure.

Canonical commands, from the repository root with disposable `TEST_DATABASE_URL`:

```powershell
python scripts/build_backend.py
python -B -m unittest discover -s tests -p "test_*.py" -v
powershell -ExecutionPolicy Bypass -File tests/run_tests.ps1
python -B scripts/generate_database_diagrams.py --check
```

Local full discovery was executed as all 58 discovered modules in four isolated
subprocesses, preserving each test's normal setup/teardown and exact result.
Raw evidence: ignored `build/administration/ADM-final-verified/` and
`build/professor-tests/ADM-final-verified/`. The expected Windows-only omission is
the POSIX execute-permission test; hosted Linux executes that check and permits
only its corresponding Windows PowerShell-runner omission.

## Real browser and persistence evidence

The maintained `tests/administration/browser.py` launches actual Flask/Edge against
owned PostgreSQL fixtures. The detailed browser counts are in
[screen coverage](screen-coverage.md) and [UI-06](iterations/ADM-UI-06.md).
Important independent final executions:

- Academic pipeline: **18 POSTs / 12 non-login outcomes**, current eligible-only
  real C++ snapshots, material revision invalidation, actual allocation, explicit
  dates/publication, owner tracking, published read-only enforcement and preservation
  after eligibility rejection. Peer access and professor allocation attempts denied.
- Configuration controls: **15 POSTs / 14 non-login outcomes**, including actual
  closures/reopening, type/asset/condition/policy changes, immediate custodian
  authority removal, recurring quotas and justified priority without reservations.
- Retained Student lifecycle: **67 POSTs**, 62 successful and five expected rejected,
  independently verified. All four student/professor appointment combinations,
  approval/calendar changes, room recurrence and equipment custody/returns/extensions.
- Retained Professor independent audit: **200 width/page observations**, 2629
  keyboard steps, **32 POSTs / 20 verified outcomes**, including the direct
  run-allocation-now entry point and Student cross-role surfaces.
- Legacy eligibility: **28 POSTs / 21 verified outcomes** and real replacement
  engine run. Outstanding individual reviews block replacement; rejected legacy
  requests are excluded later without changing the existing publication at review.
- Logout race: all five roles; **five durable per-login denials**, no rejected
  mutation persisted, account versions unchanged. Original user credentials were untouched.
- Final academic replay: **50 observations / 6 POSTs / 4 outcomes**; final calendar/
  waiting/issues replay: **60 observations / 16 POSTs / 11 outcomes**; final report/
  Inbox replay: **40 observations / 9 POSTs / 4 outcomes**.

Successful browser phases have zero unexpected HTTP/console errors or horizontal
document overflow at **1440, 1024, 768, 390 and 320px**. Focus indicators, keyboard
walks, field labels, headings, table scrolling, native forms and relevant menus
were checked. This is a bounded browser/accessibility review, not an independent
screen-reader or formal WCAG certification. See [six genuine screenshots](screenshots.md).
Owned browser schemas were verified absent and servers stopped after each run.

## Corrections and code quality

Confirmed issues fixed: duplicate heading in the Student/Admin compatibility view,
mobile advanced-navigation overlap, tablet result-grid overflow, missing retry
guidance, and stale administrator assertions in retained cross-role harnesses.
The legacy review count now reuses enforcement's identical SQL predicate instead
of duplicating it. Final iteration records distinguish initial failing/aborted
commands from successful reruns; screenshots never substitute for persisted-state
verification.

Removed only an unreachable legacy admin-navigation block after its move to the
new branch of the shared template, an ineffective selector use and temporary
browser diagnostics. No files, regression tests, dependencies, compatibility
templates or Staff/TA styles were deleted. No general architectural rewrite.
Six representative screenshots total **622,056 bytes**; intermediate screenshots,
raw logs, state JSON and synthetic fixture credentials are ignored local artifacts.

Changed production scope: `admin_dashboard_service.py`, `admin_routes.py`, shared
legacy predicate, administrator presentation/landing, literal directory filtering,
Jinja composition and scoped CSS/form-guard reuse. Tests add administration read
models/pages, a legacy count case and live persistence coverage; retained cross-role
expectations reflect the intended administrator workspace. Documentation remains
within the administration guide, index and relevant READMEs.

## Data, migration and preservation review

- **No new migrations or schema/model changes.** Head remains `0051b`; existing
  `0051a`/`0051b` compatibility/recovery tests run against disposable databases only.
- C++ source, JSON protocols, strategies, conflict rules, research implementation,
  dependency pins and GitHub workflows are unchanged from the reviewed baseline.
- New Home/report/history reads use one read-only repeatable-read snapshot,
  bounded SQL and current service-specific permission predicates. They do not run
  the C++ engine, expose private appointments or create a second source of truth.
- Eligibility, engine outcome, calendar visibility, room confirmation, equipment
  reservation/custody/return and waiting preapproval are separately displayed.
- Original main/release/tags and four pre-existing worktrees are preserved. Existing
  demo databases/accounts were not accessed or migrated. Normal-main untracked
  files are compared with their initial SHA-256 manifest at final verification.
- Deployment remains a separate controlled task. Existing migrations need backup,
  review and coordinated application worker restarts; this branch adds no extra
  migration requirement. No operational database or release was modified.

## Explicit deferrals and practical limits

Browser account management, password recovery, permission delegation, unrestricted
resource/identity CRUD, broad PII exports, academic-request notifications, academic
cancellation and versioned replacement of published requests remain deferred.
SIS import/enrollment inference, optimizer/cost-policy activation and production
database/deployment controls remain outside scope. Existing trusted provisioning
CLI and existing service notifications continue unchanged.

Changing a faculty room approver does not rewrite the approver stored on an
existing pending request; an organizer may need to revise/resubmit. Current
faculty/custodian scope means an administrator without a designated assignment
does not receive operational authority or private queues. Reports count current
source-record statuses by their documented date, not historical occupancy or
utilization. Recurring parent totals are not per-occurrence confirmations.

## Commit inventory

| SHA | Checkpoint |
| --- | --- |
| `e6e6909f6e8909efd8e76afdf370afbff97ddf81` | B0 audit |
| `daecc181a9609bc4fe33c673ceba2060a6e0ae00` | B1 academic verification |
| `f446e3042f43f25b02d1f7e6dbb24153d7f4d19d` | B2 operational verification |
| `0db8d03235155ed343d7a657d6261431579653ea` | B3 read models |
| `5f6af41501d4eb55dd9740d4004140ca60f0f49c` | B4 sensitive deferrals |
| `54111d312b6054b9a38a6887a2a7dcf258cd2cb0` | B5 backend acceptance |
| `3796b88c860ca9eb87c897ffc964a672723b519d` | UI-01 Home |
| `77c265d7ee0a269f1d756bc64f819b8552594f5b` | UI-02 academic workspace |
| `b7658a02a06d572c4e4e2880cd95da8f7914520c` | UI-03 resource operations |
| `d4b5a3ea8af35b5f5ab8a069de411adc5346957a` | UI-04 calendar/policies/issues |
| `c3d7b4c08b9aefbc484380299c7aba7deaf5391a` | UI-05 reporting/Inbox |
| `fdeaba6efca4cf9d8778f70408ca57ec0ca16d4a` | UI-06 independent pipeline |
| `d6919cba564763eb286f65fbece2d670a7bc6b1e` | Retained cross-role expectations |
| `ddcdb40020e5f1a3a254758b046db2139ce178fc` | Shared unchanged legacy predicate |
| `04b12700b605401818e1548f9737b5fcb6d3bcb0` | Busy guidance and landing contract |
| `b6c9c78bbf9021aa36fdec539797bf499e019c96` | Configuration-control persistence |

The commit introducing this final record contains documentation and representative
images only. The Draft PR is the publication checkpoint; its checks page records
hosted CI at the exact proposed head/merge revision. No automatic merge is planned.
