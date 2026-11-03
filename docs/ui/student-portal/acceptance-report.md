# Student Portal acceptance report — UI-10

**PASS — READY FOR FINAL ACCEPTANCE REVIEW**

Independent audit completed on 3 November 2026 (Europe/Istanbul), starting from the expected clean `998d54dc60207c2fea5434cda0fe68235a566187` on `design/student-portal`, exclusively in `resource-allocation-frontend`. Existing UI-01–UI-09 commits were preserved. No push, pull request, merge, deployment, operational-database change, permission, migration, scheduling rule, C++ or CDMCS change was made.

## Reviewed implementation and exact traceability

| Phase | Page group | Audit status | Original phase commit |
|---|---|---|---|
| UI-01 | Home and navigation | Reviewed; preserved | `548d69c` |
| UI-02 | Minimal Login | Reviewed; preserved | `42f3a92` |
| UI-03 | Appointments | Reviewed; preserved | `caf972b` |
| UI-04 | Rooms | Reviewed; preserved | `581e9b0` |
| UI-05 | Equipment | Reviewed; preserved | `e7c5aad` |
| UI-06 | Waiting Lists | Reviewed; preserved | `84d649b` |
| UI-07 | Feedback and Issues | Reviewed; preserved | `cad6b8d` |
| UI-08 | Calendar, My Schedule and Inbox | Reviewed; preserved | `2d745fa` |
| UI-09 | Final integration | Reviewed; preserved | `d060c7a` |

The [exact control-to-backend matrix](UI-10/traceability.md) contains **92 control-type traces**, nine disabled/deferred/recovery rows and 125 referenced regression methods. It records parameters, Flask endpoints, services, PostgreSQL tables/C++ calls, responses, UI outcomes and permission boundaries. [All 24 approved screens](screen-coverage.md), [68 Flask routes / 47 service rules](UI-10/contracts/routes.md), [493 source control declarations across all roles](UI-10/source-controls.csv), and [59 reachable Jinja templates](UI-10/source-audit.json) are accounted for. One dynamic administrator template helper was reviewed: `render_table_page("spaces.html")`; its inherited `table.html` remains.

The real-browser inventory contains **9,108 rendered control instances** across 242 views. **360 authorized GET destinations** were followed; [destinations](UI-10/browser/destinations.json) and [control classifications](UI-10/browser/controls.json) are recorded. Source-contract verification is distinguished from browser execution. No unexplained defective or disconnected control remains identified.

## Confirmed frontend defects and corrections

| Defect | Correction and verification |
|---|---|
| Equipment recommendation focus was overridden by `#main-content` after skip navigation | Explicit canonical GET/POST catalog actions preserve hidden pickup/due values and let focus reach the actual result. Real skip-link → recommendation POST/focus regression passed. |
| Weekly room requests displayed a required one-time start that the backend ignores | Hide/disable that room-only field in weekly mode; restore it for one-time requests. Real weekly requests with an empty one-time field, partial/all-date approvals and cancellations passed. Equipment pickup/due duration fields remain available. |
| Recurring equipment offered an unsupported independent waiting-list submission | Disable the join action with a visible, accessible reason in weekly mode; restore it for one-time requests. The existing server rejection remains. |
| A borrower could submit another extension while one was pending | Show the actual waiting state and restore the form after approval/rejection. Template tests and real request → staff decision → restored-form flow passed. |

Three focused UI regression methods were added; Teaching Assistant shell coverage was added to the existing role test. The [19-test UI module](UI-10/control-regression/tests.json) passed. No authentication or business-service internals changed.

## Dead code, duplication and retained tests

Removed only the unreachable `web/templates/_student_appointment_card.html`, unused `stat_card`/`section_heading` macros, 87 obsolete prototype rule lines, 16 legacy rule lines, one redundant mobile declaration, two unused selector arms and an unused test-helper import. [Exact deletion proof and rules](UI-10/dead-code.json) retain the shared selector portions and all generated status/event/calendar/badge variants.

All remaining templates are reachable. **104 deleted selectors matched zero elements across 242 browser views**, including all five roles. [Runtime selector checks](UI-10/browser/deleted-selector-checks.json). No unused production import, application debugging code, new frontend dependency or framework was identified. Shared student components remain the presentation boundary; [architecture overview](../../architecture/frontend-design.md).

**No valid regression test was deleted or consolidated.** The existing component escaping/contrast test now exercises the retained badge/icon components after the unused card macro was removed. All earlier screenshots and test evidence were preserved. Imported design files remain byte-identical to the supplied 22-file reference pack. [Reference integrity](UI-10/design-integrity.json).

After proving that aggregate JSON retained every module result and aggregate text exactly retained all ordered test output, 376 generated per-module report copies and 188 temporary logs from the four UI-10 full runs were moved into the local ignored `build/ui10-module-report-copies/` archive. No result or failure trace was deleted. The complete aggregate evidence remains in this packet; earlier phase evidence was untouched. [Consolidation proof](UI-10/report-consolidation.json).

## Exact executed test results

| Full Python/PostgreSQL run | Run | Passed | Failures | Errors | Skipped | Seconds |
|---|---:|---:|---:|---:|---:|---:|
| [Independent baseline](UI-10/regression/tests.json) | 614 | 613 | 0 | 0 | 1 | 1678.06 |
| [Intermediate run](UI-10/final-regression/tests.json) | 617 | 614 | 1 | 1 | 1 | 1991.86 |
| [Intermediate rerun](UI-10/verified-regression/tests.json) | 617 | 614 | 0 | 2 | 1 | 1586.11 |
| [Final acceptance run](UI-10/acceptance-regression/tests.json) | 617 | 616 | 0 | 0 | 1 | 1737.53 |

The final acceptance run used four independent module processes, with no overlapping browser/regression run. **No database test was skipped.** The sole platform skip is `test_linux_execute_permission_is_checked`: “POSIX permission check runs on Linux.” Exact names/results are in [the full output](UI-10/acceptance-regression/tests.txt). Real disposable PostgreSQL fixtures exercised migrations, recovery/backup, authorization, privacy, concurrent operations and every supported student service.

Intermediate failures are retained: one new UI assertion incorrectly selected the shared logout form and was corrected to target the equipment form; overlapping runs also produced the existing five-second `DatabaseBusy` timeout in concurrent recurring submissions. The unchanged [isolated 25-test module](UI-10/concurrency-isolated/tests.json) passed **25/25**, including both concurrency cases, without changing timeouts, assertions, backend policies or scheduling. An earlier [one-test probe](UI-10/concurrency-check/tests.json) errored under concurrent workload and is not counted as a pass. Host contention is a plausible explanation; no timing trace identifies the slow substep.

[Actual run configuration](UI-10/run-context.json) distinguishes the overlapping attempts, isolated module and final full run.

- Application C++ regressions: **192 passed, zero failed; both runtime smokes passed**. [Complete C++ output](UI-10/cpp-tests.txt).
- Cleanup-focused regressions: **41/41 passed**. [Results](UI-10/cleanup-regression/tests.json).
- Source route/form/protected-path checks passed; all 18 JavaScript files passed Node syntax checks; Git whitespace checks passed. [Contracts](UI-10/contracts/contracts.json), [runtime versions / engine manifest](UI-10/environment.json).

## Real application, persistence and security verification

**275 actual POST outcomes independently verified in committed PostgreSQL state: 158 successful operations and 117 rejected requests.** Review-only instrumentation read separate transactions before authentication/CSRF guards and after the actual response. [Per-operation verification](UI-10/persistence-verification.json) links all eleven groups and their before/after transcripts; no response mocks or invented success data were used.

- All four appointment participant combinations, professor approval/rejection, optional decline, rescheduling/reset, cancellation, history and calendar addition/removal.
- Room creation/revision, recommendations, participants, optional professor acceptance, faculty approval, partial/all-date recurring decisions, cancellations/occurrences and actual waiting assignment.
- Equipment creation, approval/rejection, physical collection, partial/full inspected returns, overdue/return intent, extension approval, recurring decisions/cancellation, real queue preapproval and automatic assignment to an Approved reservation awaiting physical custody.
- Eligible private reporting, category/urgency behavior, clarification, staff response/resolution, history and filters; personal blocks/conflicts and persisted individual/bulk notification reads.

The [92-check authorization suite](UI-10/authorization/authorization-results.json) used actual valid CSRF tokens for cross-user and privileged mutation attempts. All five roles were checked. Private records/feeds/calendars, staff-only custody/approval, malformed/stale states, missing CSRF, failed login, safe redirects, logout/session behavior and existing cookie flags were verified. Rejected domain mutations left the captured state unchanged. Pending requests, preapproval, optional invitations and equipment reminders remain distinct from confirmed personal commitments.

All review servers were stopped. Read-only PostgreSQL checks verified the 12 recorded review schemas were absent and no complete UI-10 synthetic identity roster remained. Unrelated schemas and the pre-existing test cluster were preserved. [Cleanup proof](UI-10/cleanup-verification.json).

## Browser, accessibility and design review

**242 views at 1440, 768, 390 and 320px; 2,135 keyboard steps**, including populated, empty, unresolved-calendar and real failure states. All five roles retained their authorized workflows and shells. No horizontal page overflow, unlabeled visible field, missing main heading, obscured tested focus, application JavaScript error or unexpected HTTP failure was found. Expected 400/403/409 rejection cases, intentional offline failures and the actual timeout-server 503 responses are recorded separately. [Browser output](UI-10/browser/browser-results.json), [live loading observations](UI-10/loading/loading-results.json).

The approved desktop/mobile Home, appointment and calendar references were visually compared with real captures. The four-destination navigation, pale blue/sand/sage service hierarchy, white panels, status text and mobile agendas remain coherent. Additional backend fields/history make some real pages longer than the prototype. Current sampled text contrast is 5.39–13.33:1; control boundaries 3.34:1 and focus 5.19:1 against white. [Current contrast checks](UI-10/contrast.json). Target-device and assistive-technology acceptance remains; this is not an accessibility certification.

**347 real application screenshots, including 75 new UI-10 captures.** All 272 historical image hashes are unchanged; PNG CRC checks passed. [Complete gallery](screenshots.md), [dimension/hash inventory](screenshots.json), [verification](UI-10/screenshot-verification.json). Examples: [Home 320px](UI-10/browser/final-home-320.png), [weekly room approval](UI-10/lifecycles/room-recurring-partial.png), [physical partial return](UI-10/lifecycles/physical-partial-return.png), [preapproved equipment queue](UI-10/equipment-lifecycles/equipment-queue-preapproved-unassigned.png), [actual assigned loan](UI-10/equipment-lifecycles/equipment-assigned-reservation-awaiting-custody.png).

## Files, local commits, remaining scope and recommendation

[Complete UI-10 file inventory](UI-10/changed-files.csv); [entire frontend rollout inventory](changed-files.csv). Documentation now contains the current acceptance results, exact traceability, component boundaries, screen mapping and real evidence; earlier phase records remain available.

| Local code/test commit | Purpose |
|---|---|
| `5a9c376126e980e18eb79fbab562e42717b9a87f` | refactor(ui): remove verified unused student prototype components |
| `6bf2b3c431ea021546a16f4dd3622bdfaf86675f` | fix(ui): correct recurring request controls and equipment result focus |
| `0a1017f180f53c7bf502845ea207d912a757067c` | refactor(ui): remove remaining unused booking style selectors |
| `09a02c87ca0e3071f25439cfcac4c4605af72685` | test(ui): trace student controls and verify live PostgreSQL workflows |

The evidence/documentation commit follows these commits; identify it with branch HEAD. No commits were rewritten.

No identified existing student backend feature was intentionally omitted. Deferred features remain a unified My Activity backend route, standalone student office-hours browsing, registration/recovery, email/availability alerts, public cost-preference settings, a standalone state gallery and CDMCS activation. Existing Home/service links and actual inline states remain available.

Remaining limits: deployment/operational configuration and production load testing were not performed; existing bounded lock contention can return a retryable busy response. No security or integration regression was identified in the executed scope. Final review on university devices and assistive technologies is still required.

Recommendation: the local branch is suitable for a **GitHub Draft PR and final student acceptance review**, subject to explicit authorization before any push/PR, merge or deployment. Student Services v1 is ready for final user acceptance testing when the gate above is PASS.

**READY FOR FINAL ACCEPTANCE REVIEW**
