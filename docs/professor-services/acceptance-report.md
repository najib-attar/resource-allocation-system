# Professor Portal - acceptance record

**PASS for the supported Professor Portal scope.** PROF-UI-01 through PROF-UI-07 are implemented and verified against actual Flask/PostgreSQL/C++ contracts. Academic notifications, academic cancellation and versioned published replacements remain explicitly deferred; the interface does not present them as functional.

## Delivery and reviewed revisions

Work is local on `codex/professor-services-v1` in the dedicated professor worktree. The frontend reviewed base is `5a7f0b012308dea87e15c390519122f8248699f4`, inheriting completed Student UI-10 `747c925b14c29368e6cb9bc8b2e2d9d33c494462`. [Student Draft PR #24](https://github.com/najib-attar/resource-allocation-system/pull/24) remains open, draft, unmerged and unchanged at that head. The Student worktree is clean. Reviewed main and its remote remain `d9a63f3ef0f5f22b56a79af670c740a13f7bb6ad`; main-only CDMCS/governance work was neither merged nor edited. The professor branch has no remote branch or upstream. [Fresh Git/PR proof](git-isolation-current.json).

No professor push, PR, merge, deployment or operational database change was performed. The user request takes precedence over archived handoff instructions.

## Phase and use-case completion

| Phase | Delivered interface | Verified use cases / local commit |
|---|---|---|
| PROF-UI-01 | Dedicated real-data Home; Home / My requests / Calendar / Inbox; service discovery and bounded authorized summaries | UC01-09; `9fe9b8b` |
| PROF-UI-02 | Pending/confirmed/history appointment hub; own decisions, shared approval/invitation progress, cancellation and history | UC02; `b460e67` |
| PROF-UI-03 | Own weekly hours, inclusive validity/exclusions/removal; personal timetable/blocks and mobile agenda | UC01/03; `52dff9c` |
| PROF-UI-04 | Exam, OneTime, Recurring and CommitteeMeeting declarations using one field component and actual resource specifications | UC06/07/08; `c41f271` |
| PROF-UI-05 | Owner filters/pagination/detail; separate review, allocation and calendar progress; actual rooms/reasons/history and protected revisions | UC09 and supported UC06-08 revisions; `6441b3b` |
| PROF-UI-06 | Shared month/week/day calendar, existing filters/navigation/privacy and recipient Inbox/read actions | UC05; `8f65975` |
| PROF-UI-07 | Independent integration/control/source audit, cross-role acceptance, test preservation and final full regressions | All supported use cases; `47825f5` |

UC04 optional room invitation acceptance/decline remains accessible through Home and the existing room pages; faculty approval authority is not granted. Existing authorized equipment/waiting-list/feedback history remains discoverable. Professors cannot initiate student appointments or run eligibility/allocation/publication operations.

The [screen/control matrix](screen-coverage.md) and [full backend traceability](traceability.md) map use case -> input/control -> route -> service -> PostgreSQL/C++ -> response/UI and regression. The [architecture/implementation plan](frontend-plan.md) describes shared components and preserved boundaries. The [changed-file inventory](changed-files.json) is relative to the reviewed frontend base; historical backend changes remain available in the base commit.

## Confirmed corrections and integration

- Promoted the existing Student shell/home/service CSS and Jinja service components into shared Campus Space assets, rather than retaining duplicate implementations. Original Student CSS declarations and Home content are preserved; ordinary Student and Instructor workspaces opt in while other roles retain their existing chrome.
- Added only a bounded, read-only Instructor Home projection. Existing appointment, academic, schedule and notification contracts remain authoritative; Home performs no scheduling or mutation and never infers affiliation from declarations.
- Appointment controls now reflect the acting professor's own current decision. Student-only reschedule/invitation decline controls match the existing server role guard, including historical role changes. HTML failures retain their HTTP status and safe recovery; API error contracts remain JSON.
- Professor native POST protection preserves named submitters and CSRF, prevents repeat submission and resets after back navigation. Browser acceptance submitted the form twice and verified one request. Success follows actual committed operations.
- Hours validation retains entered fields on failure. Personal blocks preserve the existing policy: confirmed appointments/student room bookings reject overlap; an overlapping academic allocation stays active. The interface explains that blocks affect appointment availability and do not cancel academic allocations.
- Academic end-time entry now represents the existing `24:00` backend boundary and round-trips it during revisions. Configured resource specifications/service status are distinguished from time availability. Weekly-slot and participant helpers perform local presentation/serialization only.
- Exposed the backend's existing unpublished request-type revision. A stale-error form keeps its original expected revision instead of silently pairing old values with the latest token; another retry remains stale until explicit reload. Active published decisions, including engine rejection, remain read-only.
- Tracking distinguishes submission, eligibility, processed outcome, actual allocation and explicit calendar applicability. Eligibility approval alone is never displayed as a reservation. Recipient Inbox states persist; academic notifications are visibly identified as unavailable.

No schema, eligibility service, repository, gateway, C++ algorithm/protocol or appointment/room/equipment/calendar/notification business rule changed in this frontend increment. Authentication/session/CSRF internals are unchanged; the authorized ordinary Instructor default landing now points to Professor Home.

## Security, eligibility and publication

Fresh preflight and full regressions verify active Instructor ownership at HTTP and service boundaries, administrator-only revision-bound eligibility review, all allocation entry points, stale approvals/publication proofs, concurrent decisions/revisions and direct-SQL protections. Unreviewed/rejected input cannot reach the default academic engine gateway. Approval and material revision reserve no resources; unpublished material revision resets eligibility.

Legacy requests require individual explicit review. Outstanding relevant legacy reviews block replacement rather than silently dropping reservations. Reviewing/rejecting a currently published request preserves its existing reservation, calendar and active pointer until authorized replacement. Published records remain read-only under concurrent writes. The refreshed eligibility browser performs a real old-schema publication, upgrade, individual review, blocked run and C++ replacement with eligible inputs only. [Gate contract proof](eligibility-contract-review.json), [legacy/engine browser persistence](eligibility-browser/persistence-verification.json).

All five roles - Student, Instructor, Teaching Assistant, Staff and Administrator - were exercised. Foreign private IDs, owner changes, self approval, unauthorized intake/review/run/publication, cross-user read changes and invalid CSRF are denied server-side. Rejected mutations leave captured database state unchanged. Existing administrator allocation/review, Student services and staff/custodian permissions remain covered by the full suite. No client-side check supplies authority.

The prior approved backend migration remains `0051a` (declaration column plus RequestEligibility, EligibilityEvent and AllocationEligibility; 61 application tables). This frontend adds **no migration**. Operational rollout still requires a separate reviewed maintenance upgrade: stop old workers, verify backup, upgrade and restart matching code, then individual legacy review. No bulk legacy approval is introduced and no operational upgrade was run. The previous backend acceptance remains in Git at `5a7f0b0` and its retained evidence directories.

## Automated execution

| Python/PostgreSQL execution | Run | Passed | Failures | Errors | Skipped | Seconds |
|---|---:|---:|---:|---:|---:|---:|
| Final full application regression: all 53 modules | 663 | 662 | 0 | 0 | 1 | 1343.64 |
| Diagnostic full run before the two heading assertions were corrected | 663 | 660 | 2 | 0 | 1 | 1882.11 |
| Complete service-example recheck | 5 | 5 | 0 | 0 | 0 | 67.42 |

[Final JSON/module results](portal-acceptance-regression/tests.json), [final transcript](portal-acceptance-regression/tests.txt), [diagnostic JSON](portal-final-regression/tests.json), [redacted diagnostic transcript](portal-final-regression/tests.txt). All final module subprocesses exited 0.

C++: **192 passed, zero failed**, exit 0; clean-slot and normal-dataset runtime smokes both passed. [Exact C++ output](portal-cpp-tests.txt).

No PostgreSQL workflow was skipped. The Windows-only skip is the POSIX execute-permission test, which requires Linux. The full suite includes authentication/authorization, all Student workflows, administration, real allocation, legacy migrations, concurrency, recovery and inactive cost-policy persistence. Exact module counts, names and elapsed times are retained in the linked JSON/transcript, not inferred from discovery.

Before frontend implementation, [fresh backend preflight](portal-backend-preflight/tests.json) ran **29/29**, zero skips. Per-phase runs and corrected harness failures remain recorded:

| Phase | Executed Python/PostgreSQL evidence |
|---|---|
| 01 | Initial 56: 54 passed, one fixture-helper error and one old redirect expectation failed. Both corrected: [dashboard 4/4](PROF-UI-01-recheck/tests.json), [redirect 1/1](PROF-UI-01-redirect-recheck/tests.json). [Initial report](PROF-UI-01/tests.json). |
| 02 | Initial 56: 55 passed, one renamed handler reference errored. Updated test; [entire failure-presentation class 4/4](PROF-UI-02-error-recheck/tests.json). [Initial report](PROF-UI-02/tests.json). |
| 03 | [48/48 passed](PROF-UI-03/tests.json). |
| 04 | Initial 37: 36 passed, one new HTML-parser checkbox assertion failed. Corrected presence check; [targeted 1/1 passed](PROF-UI-04-field-recheck/tests.json). [Initial report](PROF-UI-04/tests.json). |
| 05 | [42/42 passed](PROF-UI-05/tests.json); [stronger stale-retry check 1/1 passed](PROF-UI-05-stale-recheck/tests.json). |
| 06 | [58/58 passed](PROF-UI-06/tests.json). |

Those diagnostic attempts are not counted as passing. The first full run also exposed two service-example assertions expecting the old appointment history title. Both expectations were updated to the actual contextual heading, retaining all privacy/action/notification checks; the complete [service-example recheck](portal-service-examples-recheck/tests.json) passed 5/5. The final full run contains the corrected tests. The initial full result remains [diagnostic evidence](portal-final-regression/tests.json). An initial phase-03 browser assertion incorrectly assumed academic overlap must reject a personal block; the test/copy were corrected to the actual preserved policy. Intermediate failure artifacts remain in ignored build storage; final evidence below is from successful executions.

## Real browser, persistence and accessibility

| Execution | Views | Keyboard steps | Actual POSTs | Independently verified domain/rejection outcomes |
|---|---:|---:|---:|---:|
| PROF-UI-01 | 30 | 705 | 7 | 1 |
| PROF-UI-02 | 15 | 70 | 13 | 9 |
| PROF-UI-03 | 26 | 351 | 10 | 8 |
| PROF-UI-04 | 25 | 590 | 6 | 5 |
| PROF-UI-05 | 35 | 335 | 10 | 6 |
| PROF-UI-06 | 30 | 765 | 5 | 3 |
| PROF-UI-07 independent sweep | 175 | 2,464 | 28 | 17 |
| **Portal phase total** | **336** | **5,280** | **79** | **49** |
| Existing UC01-05 / all-role backward browser rerun | 41 | 927 | 41 | 28 |
| Eligibility / legacy / real-engine browser rerun | 32 | 452 | 28 | 21 |

All listed final scripts exited 0. Portal counts include 30 successful authentication/session POSTs in addition to 49 verified domain/rejection outcomes; they are executions, not unique workflows. Every important mutation is checked via independent committed PostgreSQL reads. Phase artifacts live under [portal/](portal/), each with `browser-results.json`, `post-states.json`, `persistence-verification.json` and `cleanup.json`. [Final sweep](portal/PROF-UI-07/browser-results.json), [committed outcomes](portal/PROF-UI-07/persistence-verification.json), [fixture cleanup](portal/PROF-UI-07/cleanup.json).

The final sweep covers 24 Professor surfaces, three real error states and eight Student surfaces at **1440, 1024, 768, 390 and 320px**, including long persisted content. Its [control trace](portal/PROF-UI-07/control-trace.json) accounts for **2,342 rendered control instances**: 1,437 links, 745 form/local inputs, 125 form actions, 30 native disclosures and five local helpers. All **130 actor-scoped unique GET destinations returned 200**. Supported form/helper behaviors were exercised across the phase suites, with negative cases and persisted-state checks. No unexplained defective or disconnected control was found; unsupported features are omitted or visibly explained in the matrix.

There were no application JavaScript exceptions, unexpected HTTP errors, horizontal overflow or unlabeled tested visible fields. Keyboard checks cover focus visibility/scrolling, mobile navigation, disclosures, account/notification controls and staff/TA/admin drawer Escape behavior. Native date/time picker subfocus uses Edge's native focus indicator. This is automated keyboard and visual acceptance, not screen-reader certification or a WCAG conformance claim. All nine owned browser schemas are confirmed absent and local fixture servers stopped. The [final read-only cleanup check](portal-acceptance-regression/cleanup.json) also observed two other disposable test namespaces; their ownership was not established and they were left untouched. Browser POST recorders omit credentials/cookies/CSRF values; all identities/data are synthetic. Diagnostic unit-test HTML uses disposable session tokens and its tracked transcript is redacted.

**272 real application PNGs** are retained with dimensions, SHA-256 and verified PNG chunk CRCs in [screenshots.json](screenshots.json). They show synthetic PostgreSQL fixtures rendered by the actual Flask application, not prototypes. Representative reviewed views: [desktop Home](portal/PROF-UI-07/home-1440.png), [320px examination form](portal/PROF-UI-07/form-Exam-320.png), [320px allocated request](portal/PROF-UI-07/allocated-320.png), [eligibility rejected while published reservation remains](portal/PROF-UI-05/rejected-eligibility-still-allocated-320.png), [weekly mobile calendar](portal/PROF-UI-07/week-320.png), and [legacy review warning](eligibility-browser/legacy-rejected-reservation-preserved.png).

## Cleanup and test retention

The [source/reachability audit](portal-source-audit.json) confirms all **67 templates are reachable**, all **652 existing test methods retained** and **11 portal methods added** (663 total). No valid test was removed, renamed or consolidated. Six old implementation paths were promoted: `student-shell.css` -> `campus-shell.css`, `student-home.css` -> `campus-home.css`, `student-services.css` -> `campus-services.css`, `student_service_base.html` -> `service_base.html`, `components/student_services.html` -> `components/services.html`, `student_error.html` -> `workspace_error.html`. Original declarations/reference updates and browser coverage justify removing the old paths. Repeated appointment rows now share one macro. One unused browser fixture binding was removed.

The 16 protected source areas, ProfessorService business-method ASTs and Student Home/CSS preservation were checked. [Contract/source review](source-review.json) parses 18 Python sources, finds no unused imports there, validates 45 matrix test references and verifies all 12 original handoff file hashes. New JavaScript functions are called by concrete event handlers; new styles have template/component callers. No further code was proven obsolete across all roles/states/layouts. `style.css` remains active for administration/staff; dynamic `spaces.html`/`table.html` remain used by `render_table_page`. They were retained. No framework or dependency was added.

Screenshots required for current/historical evidence are retained. Earlier role-ambiguous phase-01 and failed phase-03 intermediate artifacts were moved to ignored build storage; final retained screenshots identify actual actors/states. No operational or historical branch/tag was deleted.

## Remaining limitations and recommendation

1. Academic notifications need a separately approved event source/producer and recipient policy. Existing Inbox sources remain functional; academic outcomes are available in My requests.
2. Academic cancellation and versioned published replacement contracts are not implemented. Published requests are intentionally read-only until an authorized replacement excludes them.
3. Academic slots are weekly. Dated calendar commitments require explicit administrative bindings; declared course/faculty/activity information does not establish affiliation or private teaching entitlement. Professors cannot select/run allocation strategies.
4. Existing personal-block/academic-overlap semantics remain as documented above. This release does not change scheduling policy.
5. Linux execute-permission and screen-reader/manual assistive-technology certification remain outside this Windows acceptance execution. Eventual main integration and operational migration require separate review.
6. The professor branch depends on unmerged Student Draft PR #24. A professor Draft PR can be prepared only after explicit approval and dependency/integration review. Nothing was pushed or published.

The supported frontend and administrative gate are ready for final user acceptance review, subject to those documented scope limits. No unresolved security, backend-integration or data-integrity blocker was found in the executed scope. The final documentation commit follows the implementation/audit commits and is available in `git log`.

**READY FOR PROFESSOR PORTAL ACCEPTANCE REVIEW**
