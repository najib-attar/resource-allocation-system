# Professor Services - independent acceptance record

**FRESH LOCAL INTEGRATION VERIFICATION PASSED.** This is the pre-publication verification snapshot for Professor Services plus Student Portal and current main `196933506469ae25d3214a91ef2fd457356d096d`. User authorization resumes publication and a normal merge only after all hosted checks, current-base and review/protection gates pass. The eventual Professor PR records hosted run IDs and merge status. No deployment is included. [Exact fresh results](integration-verification.json).

## Resumed final integration - 4 November 2026

Fresh full Python/PostgreSQL: **741 executed, 740 passed, one expected Windows/POSIX permission skip, zero failures/errors**, all **56 modules**, **2342.84 seconds**. C++: **192 passed, zero failed**, both runtime smokes passed. These results were newly executed after the logout fix, not reused from historical audits.

All **ten fresh professor/security browser suites** passed. Nine portal/workflow suites inspected **434 real views**, **152 POST executions**, and **101 independently verified committed/rejected domain outcomes**. The tenth reproduces late authenticated Set-Cookie after actual logout for all five roles: subsequent private access is 302, replayed writes are rejected, five denials persist, other logins and new logins work. The separate Student lifecycle browser checked **67 actual POSTs (62 successful, five rejected)**, all independently verified, including student form submission -> professor approval -> confirmation -> calendar updates across all four participant configurations. No unexpected browser exceptions/errors were recorded; deliberate invalid/forbidden/conflict responses remain assertions. Widths 1440, 1024, 768, 390 and 320px and keyboard/focus checks passed.

The previously interrupted legacy browser now passes. It verifies individual legacy reviews, preserved current reservations after rejection, pending/rejected exclusion from every observed real C++ input, explicit eligible allocation, authorized replacement publication, owner tracking, revision invalidation and published read-only behavior. All **11 owned browser schemas** are absent and servers stopped; two unrelated pre-existing test schemas were preserved.

Migration `0051a` and `0051b` fresh/legacy/rollback/integrity regressions passed. A separate development copy upgraded from `0051a` to `0051b` with **all 61 pre-existing tables byte-equivalent by canonical row fingerprints**, including **94 account records and two saved appointments**. Original source and normal-project demo databases were preserved. Only the new copy was upgraded; no operational migration or reset occurred. Matching code needs a controlled stop/backup/upgrade/restart and one fresh login for pre-fix cookies. [Operations](../database-operations.md).

The professor diff retains the reviewed evidence cleanup (420 redundant files removed, 68 representative captures retained). Fresh raw output stays ignored under build; compact counts/hashes and all valid tests remain. No C++ strategy/protocol, research implementation, CI workflow, governance or private preference service changed; the I3b fixture-only compatibility adjustment is documented below. The audit tool now correctly pins reviewed authentication commit `bf8f829`, instead of falsely asserting that session internals never changed. Main's existing untracked paths have no incoming collisions and were fingerprinted for preservation. Student PR #24 is already normally merged as `1969335`; no additional main integration was needed because current origin/main is already an ancestor.

## Hosted CI compatibility correction

The first push/proposed-merge projection job failed because the I3b test fixture directly constructed an obsolete login session without the format marker or random nonce. The new middleware correctly denied authentication; production projection/authorization was unchanged. A local reproduction failed with the same PermissionError. The fixture now supplies exactly those two required session fields before invoking real middleware. No research implementation, algorithm or test assertion changed, and the production authentication guard was not weakened. The source audit verifies that these two lines are the entire research diff.

Fresh local rerun: **47 projection tests passed, zero failures/errors/skips (319.075 seconds)**, followed by **eight identity tests passed (30.363 seconds)**. The full application/C++/browser results above remain the previously executed integration gates on unchanged production/root-test code, not new post-correction executions. Corrected-head hosted CI must pass before merge. [Failure, narrow correction and exact rerun evidence](integration-verification.json).

## Historical logout correction - 4 November 2026

The original five-role browser failed after Teaching Assistant logout (403 instead of anonymous 302). A controlled real-Flask/Edge/PostgreSQL diagnostic then demonstrated authenticated 200 after a late notification response refreshed the cleared cookie. That failure and the previous 726-case regression result remain explicitly historical in the verification record.

Logout now commits a durable per-login denial before clearing the cookie. Every authenticated HTTP request checks it, so even a delayed Set-Cookie cannot restore access. Only the SHA-256 random nonce digest is persisted; no cookie/CSRF secret is stored. Other concurrent browser logins remain valid, including the same account. Global revocation, CSRF, role permissions, passwords and eight-hour sliding lifetime are preserved. Cookies predating the fix require one fresh login because historical logouts cannot be safely reconstructed.

Fresh verification on the corrected code: **91 targeted regressions passed, zero failures/errors/skips, 252.84 seconds**; **17 migration/schema compatibility executions passed, zero failures/errors/skips, 77.037 seconds**. These are **104 distinct cases / 108 executions**, including all 15 new security/migration regressions. Existing tests were retained. Fourteen existing schema checks now expect the declared Alembic head and additional table/count, preserving their other integrity/history assertions.

The deterministic real-browser race passed for **all five roles**: late refreshed cookie present, protected GET 302, replayed calendar POST 400, independent login 200 and new login 200. Exactly **five session denials** committed; account versions were unchanged and no attempted calendar block persisted. The original failed browser now passes: **41 POST executions / 28 independently verified outcomes**, appointment approval/rescheduling/cancellation, notifications, ownership, calendar views, keyboard and responsive checks. All five owned browser schemas are absent and servers stopped; two unrelated pre-existing schemas were preserved.

Additive migration **0051b** creates `logged_out_session` (**62 application tables**). Existing account data, eligibility decisions, published reservations and engine contracts are unchanged. Empty downgrade/re-upgrade succeeds; populated downgrade refuses denial loss. Denials survive account deletion/reprovision and concurrent global revocation. No automatic purge is introduced. Operational rollout requires stopping old workers, backup, upgrade and matching code restart; mixed authentication workers are unsafe. **No operational or persistent demo database was migrated.** Restarting the existing synthetic demo launcher upgrades it without reseeding. [Migration and retention procedure](../database-operations.md).

Student PR #24 remains merged normally as `196933506469ae25d3214a91ef2fd457356d096d`; the professor branch already incorporated it as `da7851efe640d720aa683ba8751cc58633271eff`. Student worktree is clean. Scheduling/C++ source, academic eligibility, repository, CDMCS research/governance and workflows remain unchanged by this correction. Current source audit retains 652 backend test methods and counts **741 current methods**, verifies 67 reachable templates and 68 screenshot hashes. Those scoped results preceded the fresh full integration gates above; they are not counted as new executions. Hosted publication/merge and final combined-main verification remain subsequent release steps.

Integration cleanup removes **420 redundant generated files (45,658,932 bytes)**, retains **68 unchanged representative screenshots**, and compacts duplicate inline control vectors in browser metadata. All 606 original tracked professor evidence files were archived and individually SHA-256 verified before removal; unchanged Git history preserves revision `937adcc`. [Every removed path/hash/reason](artifact-cleanup.csv), [archive/compaction proof](artifact-cleanup.json). The [378-signature control summary](PROF-UI-08/browser/control-summary.csv) preserves the 5,892 classified control occurrences; the compact browser results retain all view, keyboard, destination, network and error metadata. Important failure traces, final full test output, module summaries, persistence checks, use cases and backend matrices remain.

No production code, valid test, migration or C++ source is removed by cleanup. Audit tooling now pins the approved Student cleanup head and the actual merged main base, while retaining Student-source preservation checks. Raw future reports/captures remain local unless deliberately reviewed for inclusion.

## Historical independent UI-08 scope and Git isolation

Audit start: `6545a4aaf0b4f17311f80679f329a219209e9894`. Corrected implementation/test head: `8696adbd04acce1efe25f59acafb4c6744a1f560`. All 24 intervening branch commits, including backend work and the seven frontend phases, are recorded in [reviewed-commits.json](PROF-UI-08/reviewed-commits.json). The complete [changed-file inventory](changed-files.json) is relative to merged main `1969335`, with Student `747c925` separately recorded; `frontendBase` separately identifies reviewed backend `5a7f0b0`.

All nine original use-case PDFs and the 12 original handoff files were read and hash-checked. Their instructions are reference material; the user's later approved eligibility, legacy and revision policies govern this release. The [approved contracts](../srs/professor-workflows.md), [full frontend/backend matrix](traceability.md), [screen inventory](screen-coverage.md) and [shared component architecture](frontend-plan.md) remain the authoritative maintained documents.

The historical UI-08 audit was local at `937adcc`, with Student PR #24 then unmerged and main at `d9a63f3`. The final integration authorization supersedes that publication restriction: Student PR #24 is now merged as recorded above; its worktree remains clean, and CDMCS governance/research is preserved. Professor work remains on `codex/professor-services-v1` pending fresh integration gates. [Current Git proof](git-isolation-current.json).

## Use-case and frontend completion

| Use case | Verified backend connection and result | Frontend / disposition |
|---|---|---|
| UC01 Office hours | `/appointments/availability` -> AppointmentService publish/remove -> owned ProfessorAvailability, exclusions, calendar revision and confirmed-commitment protection -> persisted own patterns | PROF-UI-01/03; implemented |
| UC02 Student appointments | `/appointments/` and detail/decision/cancel -> AppointmentService -> C++ availability where required, own professor decision, Appointment/Event/Commitment/Notification -> current progress, confirmation, history and calendar | PROF-UI-01/02; implemented. Student rescheduling invalidates all professor approvals; no professor-initiated creation |
| UC03 Personal availability | `/appointments/calendar` -> PersonalScheduleService plus AppointmentService block/unblock -> own CalendarBlock and commitment validation -> own dated schedule / safe conflict errors | PROF-UI-03/06; implemented |
| UC04 Optional room invitations | `/rooms/` and `/<id>/invitation` -> RoomRequestService.respond -> room-attendance engine / own RoomInvitation and notifications -> persisted optional response; faculty approval/reservation unchanged | Shared room pages from Home; implemented, no staff approval authority |
| UC05 University calendar | `/calendar/`, academic detail and existing notification pages/feed/read -> UniversityCalendarService / NotificationService -> authorized source records and explicit date bindings -> month/week/day, filters, private/public projections and recipient read state | PROF-UI-06; implemented. Declared teaching responsibility is never inferred |
| UC06 Exam declarations | `/professor/requests/new?type=Exam` and academic API -> ProfessorService -> shared Repository / ResourceRequest, ExamDetails, slots, RequestEligibility -> self-owned Pending Eligibility Review; reviewed inputs alone reach existing C++ and publication | PROF-UI-04; implemented, including supported split/shared-resource declarations |
| UC07 Teaching declarations | Same intake with OneTime/Recurring -> existing slot/subtype persistence, resource constraints and eligibility -> submitted without reservation; reviewed allocation uses existing strategies | PROF-UI-04; implemented |
| UC08 Committee declarations | Same intake with CommitteeMeeting -> RequestParticipant/slots, ownership and participant-role validation -> eligibility review then original participant-aware allocation | PROF-UI-04; implemented, distinct from student appointments |
| UC09 Own requests/results | `/professor/requests`, detail and unpublished revise -> ProfessorService owner projection/revision -> eligibility/history/current RequestDecision and Allocation/date-binding records -> separate review, processed outcome, actual room and calendar state | PROF-UI-05; implemented. Material revision resets eligibility; active published requests remain read-only |

PROF-UI-01 Home uses only real authorized read projections; PROF-UI-07 verifies shared integration. All seven delivered frontend groups were rechecked in PROF-UI-08. Academic notifications, academic cancellation and versioned published replacements remain visibly deferred. The complete matrix records parameters, actor, route, service, persistence/engine, response and tests for every supported action, including shared authentication/navigation and administrator controls.

## Confirmed findings and local corrections

1. **Internal allocation guard:** a no-op duck-typed `assert_allocation_ready` wrapper could send a pending request to the real C++ engine. The reproduction produced an Approved calculation, but no publication or allocation row. The default gateway now requires exact canonical repository input types and invokes canonical validation directly. Forged wrappers/subclasses/overridden instance methods are denied before subprocess execution; canonical reviewed snapshots, copies and deep copies still execute the real engine. Explicit standalone fixture opt-in remains unused by production allocation entry points. [Before-fix reproduction](PROF-UI-08/gateway-probe-before.json). Fix `d71461d`.
2. **Malformed participant input:** optional `participants: null` raised an unhandled exception; empty strings/objects could also be accepted as malformed collections. Non-list input now returns JSON 400 before persistence; valid empty lists remain supported. Tests cover ten malformed collection/type combinations and committed no-write state. [Before-fix probe](PROF-UI-08/input-probe-before.json). Fix `86d72e4`.
3. **Misleading administrator confirmation:** the saved page always claimed Pending review, and its review-labelled POST could actually run allocation after approval. It now reads current eligibility, links to genuine review and presents an explicit Run Allocation Now action only when eligible. Unknown IDs return shared 404 recovery rather than false success.
4. **Hidden review navigation:** the administration disclosure now remains expanded with the active eligibility destination on review pages. Existing server authorization remains authoritative.
5. **Confirmation overflow:** a valid long declaration produced a 6575px document at a 1440px viewport. Scoped card wrapping/bounded grid tracks fix all five tested widths. [Original failure/cleanup](PROF-UI-08/browser-diagnostic/browser-output.txt). Findings 3-5 are fixed in `0de18dc`.
6. **Evidence gap:** earlier control inventories inspected main content only. The independent mode also captures global navigation, open account/notification menus, mobile drawers, local helpers and JavaScript calls, with role-scoped destination and keyboard checks. Migration reversal coverage was strengthened. Tests/evidence correction `8696adb`.

No scheduling algorithm, JSON engine protocol, resource conflict rule, role permission, database schema or migration changed during this audit. Valid regression tests were retained.

## Administrative gate, migration and data integrity

Eligibility, allocation and dated publication remain separate. Instructor input is self-owned and pending; review requires an active authorized administrator, a reason and matching request/review revisions. Self-review and foreign ownership are denied. Material parent/subtype/slot/participant revisions invalidate approval and append history. Active published requests remain read-only at service/database boundaries, even after eligibility rejection.

Every default academic allocation path was traced: repository snapshot, session snapshot, start_run, gateway, run-now, batch/strategy runs, run persistence and publication. Pending/rejected inputs are excluded; canonical checks reject stale/tampered inputs, and immutable proofs/input revisions are rechecked before atomic publication. Review and publication serialize through ApplicationState/row locks and database triggers. Concurrent review/revision tests prevent stale publication. A formerly eligible in-flight calculation may finish after a later decision; its stale result cannot replace the active publication.

Migration `0051a` adds `faculty_declaration`, RequestEligibility, EligibilityEvent and AllocationEligibility (61 application tables). It is unchanged in this audit: SHA-256 `a609a0af4331b517bab13977cb4c27ac37ee5ee47e5e1e76b89074706eeaf742`. Legacy provenance is not guessed: all legacy requests start pending explicit individual review. Relevant outstanding legacy reviews block both a run and replacement publication, with an actual list and explanation. Rejection preserves current reservations/decisions/calendar applicability until authorized replacement; historical rows remain after replacement. Individual approval itself allocates nothing.

Four real PostgreSQL migration tests passed: populated upgrade, review/rejection and reservation preservation, refusal of populated destructive downgrade, and empty-schema downgrade to `0050b` followed by upgrade. Failed populated downgrade rolls back with version/history/eligibility/publication intact. Empty reversal works; populated reversal intentionally refuses data loss. [Migration results](PROF-UI-08/verified-regression/tests.json), [source/integrity proof](PROF-UI-08/source-integrity.json), [fresh legacy browser persisted outcomes and real engine inputs](PROF-UI-08/legacy-gate/persistence-verification.json).

Publication still invokes the existing appointment/student-room commitment and room-publication conflict guards before changing the active pointer. Room closures/unresolved date protection is retained. No operational migration ran. Operational rollout requires separately reviewed maintenance: stop old workers, back up, upgrade and restart matching code, then review legacy requests individually.

## Automated regressions

| Execution | Run | Passed | Failures | Errors | Skipped | Seconds |
|---|---:|---:|---:|---:|---:|---:|
| [Final full regression (4 workers)](PROF-UI-08/verified-regression/tests.json) | 668 | 667 | 0 | 0 | 1 | 2308.02 |
| [Gateway recheck](PROF-UI-08/gateway-recheck/tests.json) | 54 | 53 | 0 | 0 | 1 | 149.8 |
| [UI/input correction recheck](PROF-UI-08/corrections-recheck/tests.json) | 13 | 13 | 0 | 0 | 0 | 213.76 |
| [Earlier overlapping full attempt](PROF-UI-08/regression/tests.json) | 666 | 663 | 1 | 1 | 1 | 2574.72 |
| [Second overlapping full attempt](PROF-UI-08/final-regression/tests.json) | 667 | 665 | 0 | 1 | 1 | 2622.56 |
| [Initial focused diagnostic](PROF-UI-08/focused/tests.json) | 32 | 31 | 1 | 0 | 0 | 241.69 |
| [Initial confirmation diagnostic](PROF-UI-08/confirmation/tests.json) | 11 | 10 | 0 | 1 | 0 | 96.27 |

The final full suite executed all 53 modules with exit 0: **668 executed, 667 passed, zero failures/errors, one skip**, in **2308.02 seconds**. No PostgreSQL workflow was skipped. The single skip is the POSIX executable-permission check on Windows; Linux verification remains outstanding. [Final exact transcript](PROF-UI-08/verified-regression/tests.txt). Command: `PROFESSOR_TEST_WORKERS=4`, then `python -B tests/professor/run_tests.py --parallel PROF-UI-08/verified-regression`, with the disposable local PostgreSQL URL/tool directory and real built backend configured.

The complete suite includes all five roles, authentication/session/CSRF, cross-user read/write, professor workflows, eligibility decisions/revisions/races, direct SQL protections, allocation/publication, legacy upgrades, Student appointments/rooms/equipment/waiting lists/feedback, notifications/calendars and administrator workflows. Final module counts/results are recorded in JSON rather than inferred from discovery.

Earlier attempts are not counted as passing. They exposed a missing synthetic TA identity in a new assertion and a temporary missing error-handler import, both corrected and rechecked. Two overlapping full runs recorded a recurring-workflow DatabaseBusy lock timeout; the final four-worker full run passed that module 25/25 and all others. The existing five-second application-state lock timeout was not changed. Original failed result/transcript evidence is retained.

C++: `tests/run_tests.ps1` freshly compiled and executed **192 passed, zero failed**, exit 0. Both clean-slot and normal-dataset runtime smokes passed. [Complete C++ output](PROF-UI-08/cpp-tests.txt). All C++ sources remain identical to Student base; no CDMCS activation or engine modification occurred.

Static checks: all **60 changed Python sources** parse; all **nine changed JavaScript/CJS files** pass `node --check`. The targeted import/contract review parsed 18 new professor sources, found no unused imports, verified 52 matrix test references and all 12 handoff hashes. [Syntax](PROF-UI-08/syntax.json), [contract/source audit](source-review.json).

## Fresh real browser and persistence evidence

| Execution | Views | Main keyboard steps | Actual POSTs | Independently verified domain/rejection outcomes |
|---|---:|---:|---:|---:|
| [PROF-UI-01](PROF-UI-08/phases/PROF-UI-01/browser-results.json) | 30 | 745 | 7 | 1 |
| [PROF-UI-02](PROF-UI-08/phases/PROF-UI-02/browser-results.json) | 15 | 70 | 13 | 9 |
| [PROF-UI-03](PROF-UI-08/phases/PROF-UI-03/browser-results.json) | 26 | 351 | 10 | 8 |
| [PROF-UI-04](PROF-UI-08/phases/PROF-UI-04/browser-results.json) | 25 | 590 | 6 | 5 |
| [PROF-UI-05](PROF-UI-08/phases/PROF-UI-05/browser-results.json) | 35 | 335 | 10 | 6 |
| [PROF-UI-06](PROF-UI-08/phases/PROF-UI-06/browser-results.json) | 30 | 765 | 5 | 3 |
| [Independent sweep](PROF-UI-08/browser/browser-results.json) | 200 | 2604 | 32 | 20 |
| [UC01-05 / five roles](PROF-UI-08/existing-workflows/browser-results.json) | 41 | 927 | 41 | 28 |
| [Legacy / real C++ replacement](PROF-UI-08/legacy-gate/browser-results.json) | 32 | 452 | 28 | 21 |
| **Total** | **434** | **6,839** | **152** | **101** |

All nine fresh browser scripts exited 0. They use the actual Flask server, disposable PostgreSQL schemas, synthetic accounts and the real C++ binary where applicable. Each retains `browser-results.json`, `post-states.json`, `persistence-verification.json` and `cleanup.json`. Counts represent executions, not unique workflows; authentication/session operations are additional to domain/rejection outcomes.

The 200-view independent sweep verifies **1440, 1024, 768, 390 and 320px**, long persisted input, professor pages, eight Student surfaces, real invalid/private/published-error states and administrator confirmation/review states. Its [whole-document control trace](https://github.com/najib-attar/resource-allocation-system/blob/937adcc75e23af79e37c394c932e99bc330e6a1b/docs/professor-services/PROF-UI-08/browser/control-trace.json) classifies **5,892 rendered instances**: 4,193 destinations, 750 form/local inputs, 374 form actions, 285 local helpers, 285 native disclosures and five intentionally disabled empty-state Mark all read controls. All **167 actor-scoped unique GET destinations returned 200**, and all **156 recorded JavaScript responses returned 200**. The five-role backward browser also verified 164 actor destinations and 78 successful JavaScript responses; these overlap and are not summed as unique destinations.

No unexplained disconnected/defective control remains in the inspected states. Forms/helpers were exercised with committed-state checks, invalid parameters, repeat submission, conflicts, stale revisions, private IDs and cross-role rejection. The administrator run-now POST and legacy replacement actually invoked C++; recorded engine inputs contained eligible IDs only. No new professor administrative authority was exposed.

There were no application JavaScript exceptions, unexpected HTTP errors, horizontal overflow or unlabeled tested visible fields. Expected 400/403/404/409 error paths remain recorded. Main keyboard walks include skip links, focus visibility/scrolling and native controls; 53 additional account/notification/drawer panel checks passed. Responsive screenshots were visually compared with the approved Campus Space reference and retained shared Student components. Automated keyboard/visual checks do not claim screen-reader certification or formal WCAG conformance.

The [screenshot inventory](screenshots.json) verifies dimensions, SHA-256 and PNG chunk CRCs for **68 representative unchanged application PNGs** after integration cleanup. The original 414-capture audit (142 fresh and 272 prior) remains in the hash-verified archive and unchanged Git revision `937adcc`. Fresh examples: [desktop Professor Home](PROF-UI-08/browser/home-1440.png), [320px exam form](PROF-UI-08/browser/form-Exam-320.png), [320px request allocation](PROF-UI-08/browser/allocated-320.png), [320px long saved confirmation](PROF-UI-08/browser/pending-confirmation-320.png), [published reservation after eligibility rejection](PROF-UI-08/phases/PROF-UI-05/rejected-eligibility-still-allocated-320.png), and [legacy rejection warning](PROF-UI-08/legacy-gate/legacy-rejected-reservation-preserved.png). These are Flask output, not prototype evidence.

All nine current owned browser schemas are confirmed absent and servers stopped. The final read-only catalog check leaves two pre-existing unowned disposable namespaces untouched. [Cleanup proof](PROF-UI-08/cleanup.json). Browser recorders omit credentials/cookies/CSRF values. No operational data was read or modified.

## Security and code cleanup

Student, Instructor, Teaching Assistant, Staff and Administrator boundaries passed. Inactive accounts, foreign private IDs, forged owner inputs, self-review, staff/custodian actions, professor allocation attempts, cross-recipient notification changes, invalid CSRF and stale writes remain server-protected. Failed operations are verified against unchanged committed state. Session/CSRF/authentication internals and existing appointment/room/equipment/calendar/notification services remain preserved; approved professor guard/landing changes are separately identified in the source review.

All 67 templates are reachable, including dynamic `spaces.html`/`table.html`. New selector classes and JavaScript helpers have actual callers. The original Student Home/CSS declarations and all **617 Student-base test methods** remain; **652 reviewed-backend methods** remain; current total is **668**. No test was removed, renamed or consolidated. Five regression methods were added during this audit and existing checks strengthened. [Source/reachability and retention](portal-source-audit.json), [whole-branch preservation](PROF-UI-08/source-integrity.json).

The original PROF-UI-08 audit deleted no file; the later integration cleanup is documented above. No additional implementation was removed: no further unused implementation could be proven across all roles/states/layouts. The prior six promotions of Student assets/components into shared Campus Space paths remain justified and retained; repeated appointment rows share one macro. Active legacy `style.css`, dynamic templates and valuable tests were retained. No dependency/framework was introduced. Failed/intermediate raw screenshots stay in ignored build storage; their diagnostic result and cleanup proof remain, while useful current and historical evidence is retained.

## Local audit commits and remaining decisions

| Commit | Purpose |
|---|---|
| `d71461d6ea62f075fffd4f8f6c536de6a2970f08` | Canonical checked academic engine inputs and regression |
| `86d72e4efb27ead7d20c5a99c175e1b8d3cd5797` | Reject malformed optional participant collections before writes |
| `0de18dcbb5bd2847d2e03aab0cdeb2b0d87cfb57` | Live confirmation states/actions, safe 404, review navigation and scoped overflow correction |
| `8696adbd04acce1efe25f59acafb4c6744a1f560` | Independent whole-shell browser checks, test preservation and migration reversal coverage |

The final documentation/evidence commit follows these implementation/test commits; its SHA is reported in delivery and Git history. Earlier acceptance/evidence remains available at `6545a4a`, including [prior full rollout results](portal-acceptance-regression/tests.json) and all phase artifacts; it is not counted as fresh audit execution.

Outstanding scope/rollout limits:

1. Academic notifications, cancellation and versioned replacements of published requests remain deferred and visibly explained. No unsupported control is advertised as functional.
2. Weekly academic allocations require explicit administrative date bindings for calendar commitments; course/faculty declarations establish no affiliation or private teaching responsibility.
3. Existing personal blocks do not cancel overlapping academic allocations; existing appointment/student-room conflict rules remain authoritative.
4. Linux permission verification and manual assistive-technology review remain separate. The existing bounded lock timeout may return a safe busy error under heavy contention; no performance guarantee is claimed.
5. Student PR #24 is merged and its dependency is incorporated. Final merged-main verification follows hosted checks and normal merge; operational deployment remains separate.

The final integration authorization permits a Professor Services PR and normal merge only after fresh local/hosted checks pass. Migration assumptions remain explicit, and deployment is excluded. The historical independent audit passed within its documented limits; the integration gates above remain authoritative.

**FRESH LOCAL VERIFICATION PASSED - HOSTED AND FINAL MAIN GATES STILL REQUIRED**
