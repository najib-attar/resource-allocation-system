# Professor Services v1 — eligibility and backend acceptance

**PASS for the approved eligibility/backend increment.** The former missing-gate blocker is resolved under the user's explicit approval. Full professor visual redesign and academic outcome notifications remain outside this completed increment; historical pre-gate reports are identified below.

## Source and delivery boundary

Professor branch `codex/professor-services-v1` is based on completed Student UI-10 commit `747c925b14c29368e6cb9bc8b2e2d9d33c494462`. Student work is unchanged and clean. [Draft PR #24](https://github.com/najib-attar/resource-allocation-system/pull/24) remains open, draft, unmerged and targets main with that exact head. The professor branch has no remote branch or upstream. [Current remote/PR proof](git-isolation-current.json), [original preparation](git-preparation.json).

Reviewed main was `d9a63f3ef0f5f22b56a79af670c740a13f7bb6ad`; its seven main-only governance/cost-policy commits were inspected but not merged or changed. C++ algorithms/protocols, CDMCS, account/session internals, appointment/room/equipment/notification/calendar services are preserved. No professor push, PR, deployment or operational database migration was performed.

## Use-case results

| Use case | Implementation |
|---|---|
| UC-PROF-01 | Existing own dated hours/exclusions/removal verified; confirmed-appointment protection retained |
| UC-PROF-02 | Existing professor approval/rejection, all participant combinations, unanimous current revision, reschedule invalidation, cancellation/history/calendar verified |
| UC-PROF-03 | Existing own timetable/blocks and cross-user protection retained |
| UC-PROF-04 | Existing optional room invitation response retained; no faculty approval or reservation authority granted |
| UC-PROF-05 | Existing university calendar views/filters/privacy and recipient Inbox/read actions retained |
| UC-PROF-06 | Self-owned Exam intake, declarations, eligibility review and existing engine result tracking implemented |
| UC-PROF-07 | Self-owned OneTime/Recurring weekly academic intake, review and existing allocations implemented |
| UC-PROF-08 | Self-owned CommitteeMeeting with active mandatory participants/roles, review and existing committee allocation implemented; separate from appointments |
| UC-PROF-09 | Functional owner Jinja list/detail, filters/pagination, eligibility/revision/history, actual active outcomes/rooms and explicit bindings implemented; academic outcome notifications remain deferred |

The [complete control-to-endpoint/service/persistence/engine/result matrix](traceability.md) includes authorization, stale/invalid paths, run entry points and intentionally unavailable controls. [Approved state, legacy and revision contracts](../srs/professor-workflows.md). [Professor frontend sequence](frontend-plan.md).

## Eligibility, persistence and migration

Migration `0051a` adds one declaration column and three tables: RequestEligibility, EligibilityEvent and AllocationEligibility. There are 61 application tables plus Alembic; generated schema catalog and ER diagrams were updated.

New professor requests begin **Pending Eligibility Review**, independently of allocation Pending/Approved/Rejected and calendar publication. Active enabled Instructor ownership is checked in HTTP and services. A different active administrator reviews a specific request revision and review version with a reason. Decisions append immutable history, invalidate in-flight input revisions and reserve nothing. Material unpublished revisions return to review. All requests included in the active published batch are read-only, even engine-rejected requests or requests whose eligibility later changes.

All repository snapshots/start paths filter Eligible current revisions. The default Python gateway refuses unguarded raw academic dictionaries and revalidates captured digest/current eligible payload. Standalone protocol fixtures explicitly opt in; production never does. C++ itself remains the trusted protocol primitive without SQL or publication authority. Publication rechecks current input/review versions and immutable run proofs under the same application-state lock. A later review/edit makes a captured run stale and preserves the previous active results.

Every old academic record becomes **Legacy / Pending Eligibility Review**, with baseline revision and audit record; no blanket approval. Outstanding current legacy reviews block a new run and replacement publication, with a clear queue of IDs. Individual rejection excludes future input but preserves the current reservation until authorized replacement. Current allocations, results, bindings and history are retained. Downgrade with eligibility/history refuses destructive loss.

Rollout assumes old workers stopped, backup verified, Alembic upgraded through 0051a, then matching application code restarted. Old in-flight revisions are invalidated. No operational schema was migrated. Administrator-owned legacy requests require a different administrator to review them. Review changes do not themselves alter existing reservations or calendars.

## Confirmed corrections and code quality

- Closed raw-dictionary/presentation-snapshot allocation bypasses at the Python gateway; copy/deepcopy retain guards and payloads are checked against current eligible data.
- Extended published read-only enforcement to every active RequestDecision, including engine rejection, at service and database boundaries.
- Protected eligibility audit/proof records against rewriting, deletion and truncation; protected populated downgrade with table locks.
- Changed existing admin save/run shortcuts to explicit review-first behavior; no silent automatic approval.
- Fixed garbled separators in new Jinja views using HTML entities and rendered weekday/time values in readable HH:mm form. New forms reuse existing panels/form grids and one shared field component; no additional CSS/framework/dependency was retained.
- Demo seeds await review by default. Only explicit new-fictional-demo opt-in performs real synthetic administrator reviews; existing profiles are preserved.

All **617 baseline test methods remain**, with **35 additional methods** (17 from the initial professor verification and 18 from eligibility/intake/migration). No valid regression test was deleted, renamed or consolidated. Older allocation fixtures now perform real synthetic administrator reviews through EligibilityService in owned random PostgreSQL schemas; new gate/security tests call production paths directly. Presentation assertions use the all-record read model rather than eligible-only input. Historical-schema replay clears only gate-specific test metadata inside owned disposable schemas, never operational data. Schema/table/trigger counts reflect the additive migration. Inactive cost-policy implementation and tests' policy assertions are preserved.

No shared template/style/service was proven obsolete across every role, so none was removed. One unused test import was removed. Generated schema diagrams are current documentation; browser screenshots are retained as evidence. Temporary executables, fixture credentials and runtime profiles stay under ignored build storage.

## Executed results

| Execution | Run | Passed | Failures | Errors | Skipped | Seconds |
|---|---:|---:|---:|---:|---:|---:|
| Fresh full Python/PostgreSQL regression, all 52 modules | 652 | 651 | 0 | 0 | 1 | 1375.41 |
| Intake recheck after adding dated-calendar/direct-SQL assertions | 7 | 7 | 0 | 0 | 0 | 70.02 |
| Earlier focused gate/intake/legacy verification | 15 | 15 | 0 | 0 | 0 | 98.03 |

[Full results](eligibility-final-regression/tests.json), [full transcript](eligibility-final-regression/tests.txt), [calendar/intake recheck](calendar-preservation-recheck/tests.json). No PostgreSQL integration test was skipped. The sole skip is `test_linux_execute_permission_is_checked`: POSIX execute-permission checking runs on Linux, not Windows. The full suite includes all five-role authentication/authorization, student services, real allocation, recovery/restore, concurrency, migration drift, inactive preference/cost-policy persistence and new professor workflows. The later recheck strengthens an existing test; it does not replace the full run.

The [current contract/source audit](source-review.json) verified 14 new Python sources, no unused imports, all 45 matrix test references, unchanged protected services/C++ and session/CSRF internals, clean preserved Student worktree and all 12 original handoff file hashes. [Current gate proof](eligibility-contract-review.json) shows pending input excluded, explicitly reviewed input included, and no allocation/publication caused by review.

C++ output: [eligibility-cpp-tests.txt](eligibility-cpp-tests.txt), **192 passed, zero failed**; clean-slot and normal-dataset runtime smokes passed. Existing engine source/binary fingerprints remain recorded in [backend-artifact.json](backend-artifact.json).

The earlier diagnostic full run executed 651 tests: 635 passed, 10 failures, 5 errors and one Windows-only skip. It exposed old immediate-allocation fixtures/schema counts, mocked unguarded payloads, historical replay trigger expectations and the now-forbidden published-slot edit. The source was still being hardened during that diagnostic run; it is not final acceptance. [Original diagnostic results](eligibility-full-regression/tests.json), [transcript](eligibility-full-regression/tests.txt). Earlier compatibility (71 run, 67 passed, four failures) and intake harness (12 run, three subtest failures) evidence is retained; no failed attempt is counted as passing. Causes were corrected and rerun. Earlier pre-gate reports under regression/, owner-reads-final/, approval-gate-evidence.json and accepted-results.json remain historical snapshots of the previous stage. The browser/ evidence has been refreshed against the current gate; its earlier version remains in Git history.

## Real browser and responsive acceptance

| Browser execution | Views | Keyboard steps | POSTs | Independently verified domain/rejection outcomes |
|---|---:|---:|---:|---:|
| Existing UC01–05 and owner-read workflows, all five roles | 41 | 884 | 41 | 28 |
| New eligibility/intake/revision/legacy replacement workflows | 32 | 396 | 28 | 21 |

Both scripts exited 0. There were no application JavaScript exceptions, unexpected HTTP errors, horizontal overflow or unlabeled tested visible fields. Expected authorization/validation denials were asserted explicitly and left captured state unchanged. The 69 POSTs include 20 authentication/session operations and 49 verified domain/rejection outcomes; these are separate executions, not 69 unique workflows. Native picker subfocus contributed 45 and 24 steps respectively. The final eligibility browser was rerun after the HH:mm display correction; the retained results/screenshots come from that final run.

[Existing workflow browser results](browser/browser-results.json), [controls](browser/controls.json), [actual POST states](browser/post-states.json), [independent verification](browser/persistence-verification.json), [cleanup](browser/cleanup.json). [Eligibility browser results/control inventory](eligibility-browser/browser-results.json), [actual POST states](eligibility-browser/post-states.json), [independent verification and real engine inputs](eligibility-browser/persistence-verification.json), [cleanup](eligibility-browser/cleanup.json). Both owned schemas were independently confirmed absent and both servers stopped.

**38 real application PNGs** are inventoried with dimensions, SHA-256 and PNG CRC verification in [screenshots.json](screenshots.json). Visual review included [desktop academic list](eligibility-browser/academic-list-1440.png), [320px exam form](eligibility-browser/new-Exam-320.png), [320px legacy review](eligibility-browser/legacy-review-320.png), [rejected legacy reservation warning](eligibility-browser/legacy-rejected-reservation-preserved.png), and the original shared hour/calendar screens. No screenshot is a prototype image.

Initial browser harness attempts exposed synthetic identity/sequence collisions, which were repaired in the fixture. Visual inspection then corrected separator encoding and raw-minute display. Earlier failures are not reported as passing runs; the final scripts and artifacts reproduce the corrected behavior.

No prototype image is used as implementation proof. Browser fixtures are synthetic PostgreSQL schemas; actual Flask responses and real state-changing POSTs are checked using independent committed database reads. Passwords, cookies and CSRF values are omitted from tracked evidence. The gate browser also creates a real pre-migration publication, upgrades it, verifies review holds and runs an actual C++ replacement using eligible inputs only. Fixture/server cleanup is verified.

Keyboard/label/focus/overflow checks cover 1440, 768, 390 and 320 pixels. Native date/time picker subfocus uses Edge's native focus indicator. This is automated keyboard review and visual inspection, not screen-reader certification or a full professor visual redesign. The shared Campus Space shell and controls are reused; full professor page-group visual acceptance remains planned.

## Remaining scope and risks

1. Academic outcome notifications require a separately approved ResourceRequest event source/schema, producer and recipient/destination policy. Existing appointment/room/equipment/feedback notifications remain functional; the API explicitly reports academic notifications unsupported.
2. Published versioned replacement requests are deferred by user decision. Current active published requests are read-only until an authorized replacement excludes them.
3. Full professor Home and visual redesign follow the existing shared component sequence. Minimal functional academic/review interfaces are delivered now.
4. Dated calendar applicability needs existing explicit administrative bindings; declarations do not establish verified faculty/course affiliation or private attribution entitlement.
5. A reviewed maintenance migration and individual legacy review are required before operational use; no bulk approval policy is introduced.
6. The professor branch depends on Student Draft PR #24. Review eventual main integration before requesting a professor Draft PR; no merge/rebase of main-only research/governance work occurred here.

The approved backend gate and professor academic workflows passed local acceptance. Full Professor Services visual/notification completion is not claimed. A professor Draft PR can be prepared after explicit approval and dependency/integration review; no push or PR is authorized now.

## Local commits

| SHA | Scope |
|---|---|
| 19457e4 | Handoff, source/contracts and original gate gap |
| 9a751c6 | Owner academic read API |
| 4bf6f7c | Calendar keyboard focus correction and original browser evidence |
| 3c3af41 | Existing professor role/workflow tests |
| 9a3dc8a | Original blocked-stage acceptance/plan |
| 1c50ecd | Revision-bound review persistence, migration and allocation gate |
| 0ae1b84 | Professor submissions/revisions, minimal admin review and integration |
| 49552d3 | Strict gateway, immutable audit and all-published-input protection |
| 48beaeb | Explicit review for fictional demo allocation |
| 8e4ca07 | Full regression compatibility, retained tests and dated-calendar proof |
| 50cacf2 | Readable shared forms/states and refreshed real-browser evidence |

The final documentation/schema-catalog commit follows these local commits; its SHA is available with `git log -1`. No professor commit was pushed. The complete [changed-file inventory](changed-files.json) is relative to the reviewed Student base. No tracked file was deleted.

**PASS — approved backend increment ready for local acceptance review. Full Professor Services visual redesign and academic notifications remain deferred.**
