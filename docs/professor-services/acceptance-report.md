# Professor Services v1 — backend review and safe increment

**CHANGES REQUIRED — academic intake is blocked by the missing administrative eligibility gate.**

The user approved self-owned requests by any active Instructor and declared course/activity metadata, but explicitly required unreviewed/rejected requests to be excluded from allocation. The current backend does not enforce that gate. UC-PROF-06–08 intake was therefore stopped as instructed. No schema, engine contract, scheduling semantics or eligibility policy was silently introduced.

## Git preparation and reviewed source

- Completed student branch: `design/student-portal`, clean at `747c925b14c29368e6cb9bc8b2e2d9d33c494462`; pushed normally. All 18 student commits are in **Draft PR [#24](https://github.com/najib-attar/resource-allocation-system/pull/24)** targeting main. The PR is unmerged and mergeable; four reported check runs succeeded. The legacy combined commit-status API says pending and is recorded separately, not interpreted as an additional successful gate.
- Professor branch/worktree: `codex/professor-services-v1`, separately created from that exact completed student commit. It inherits the shared Campus Space components and explicitly depends on PR #24. No professor push or PR was made.
- Latest reviewed main: `d9a63f3ef0f5f22b56a79af670c740a13f7bb6ad`. Seven main-only governance/CI/cost-policy commits were inspected; no merge, rebase, reset or CDMCS edit occurred. Student and research worktrees were preserved.
- [Remote/PR commit proof](git-preparation.json), [source and handoff integrity](source-review.json). All nine individual PDFs, combined PDF and two handoff Markdown files match the supplied ZIP bytes. The inherited Student UI-10 acceptance report, feature matrix and screenshots were reviewed as prior evidence, not substituted for this increment's actual tests.

## Use-case outcome

| Use case | Status | Result |
|---|---|---|
| UC-PROF-01 Appointment hours | Verified existing | Own dated hours/exclusions, role/CSRF/ownership, invalid inputs and protected removal; existing future-confirmed-appointment restriction retained |
| UC-PROF-02 Student appointments | Verified existing | Required-professor current-revision approval/rejection, all four participant combinations, unanimous confirmation, optional students, rescheduling/invalidation, cancellation, history/calendar/notifications |
| UC-PROF-03 Personal schedule/blocks | Verified existing | Own dated blocks and timetable, cross-user denial, no override of confirmed commitments, privacy |
| UC-PROF-04 Student room invitations | Verified existing | Optional acceptance/decline with conflict checks; no faculty approval/custody authority or exclusive reservation |
| UC-PROF-05 Calendar/Inbox | Verified existing | Month/week/day, filters/date navigation, source-scoped details, recipient read/unread behavior; public academic attribution remains metadata |
| UC-PROF-06 Exam requests | **Blocked intake** | Existing engine/read support verified; no administrative eligibility gate before engine snapshots |
| UC-PROF-07 Teaching/recurring requests | **Blocked intake** | Existing OneTime/Recurring engine/read contracts verified; same gate prevents professor submission |
| UC-PROF-08 Academic committee requests | **Blocked intake** | Existing CommitteeMeeting engine/read contract verified; separate from appointments; same gate blocks new intake |
| UC-PROF-09 Own academic tracking | **Implemented read API; partial UC** | Strict owner list/detail, filters/pagination, active Pending/Approved/Rejected results, allocations, declarations, history and explicit bindings. Professor frontend is planned; academic notifications need separately approved persistence/producer support |

The [exact endpoint/service/database/engine/result matrix](traceability.md) covers the existing controls, new API and denied/deferred capabilities. [Approved policy clarification and required gate changes](../srs/professor-workflows.md). [Reproduced snapshot proof](approval-gate-evidence.json): a saved Pending request enters the administrative engine input without any review state; the proof deliberately did not invoke the engine or publish a reservation.

## Implementation, security and cleanup

New `ProfessorService` and `/professor/academic-requests` GET endpoints enforce active enabled Instructor identity and `requester_id=actor` in SQL before details are loaded. They expose only active successful publication decisions and owner-scoped relations, with read-only repeatable-read transactions. Failed later runs do not replace active results; changed inputs warn explicitly. Unknown and non-owned identifiers return the same private error. Neither public visibility, instructor attribution, committee participation nor an administrator flag grants owner access. Responses are private/no-store; validation is bounded; database errors omit SQL details.

The new namespace has an explicit Instructor guard and bypasses the old global result-adapter loading path. Existing login/session/CSRF internals, administrator endpoints and all business services are unchanged. There are no academic POST endpoints, allocation/strategy/publication permissions, new notification sources, migrations or new dependencies.

A confirmed existing calendar accessibility issue was corrected: native keyboard scrolling left an inline week/day heading link partly clipped at tablet width. A 15-line calendar-specific focus handler reveals the full target inside its horizontal scrollport. The final browser test walks the week grid for all five roles and the full professor views at four widths. An attempted CSS-only adjustment did not resolve the defect and was removed; no redundant CSS remains.

No shared legacy code or valid regression test was removed or consolidated. New Python sources were parsed and checked for unused imports; existing protected persistence/authentication/business/C++ sources were verified unchanged. One temporary native-picker diagnostic screenshot was relocated to ignored build storage; the 22 final application screenshots and state-transition proof remain. The PDFs are requirement references, not screenshot evidence of implementation.

| Changed files | Purpose |
|---|---|
| `web/professor_service.py`, `web/professor_routes.py` | Owner-only academic read model and GET API |
| `web/app.py`, `web/security.py` | Blueprint registration, scoped legacy-adapter exclusion and explicit Instructor namespace guard |
| `web/static/calendar.js`, `web/templates/university_calendar.html` | Calendar-only keyboard scroll correction and script inclusion |
| `tests/test_professor_services.py`, `tests/test_professor_existing_workflows.py` | 17 additional PostgreSQL/engine/HTTP/security regression methods |
| `tests/professor/run_tests.py`, `review_contracts.py`, `browser_review.py`, `browser_review.cjs` | Reproducible test, contract-gap and real-browser verification tools; these four paths share `tests/professor/` |
| `docs/srs/professor-workflows.md`, `docs/professor-services/` | Reviewed contract decisions, traceability, frontend plan and exact acceptance evidence |
| Imported `Codex-Professor-Handoff.md`, `docs/srs/professor-backend-audit.md`, nine `docs/use-cases/UC-PROF-*.pdf`, `reference/Professor-Use-Cases-Combined.pdf` | Original supplied requirement/reference material preserved |

## Executed verification

Dedicated owner-read suite: **14/14 passed**, zero failures/errors/skips, 106.44 seconds. Additional existing-workflow contracts: **3/3 passed**, zero failures/errors/skips, 30.25 seconds. The earlier 13-test read run also passed before the all-four-type real-engine case was added. [Read results](owner-reads-final/tests.json), [existing contracts](existing-contracts/tests.json).

Full application C++ regressions: **192 passed, zero failed**, with both `clean-slot` and `normal-dataset` runtime smokes passing. The runner exited 0 and cleaned its owned temporary build directory. [Complete C++ output](cpp-tests.txt).

The broader Python/PostgreSQL verification covers **25 relevant modules / 391 selected tests**. The accepted latest results are **390 passed, zero failures/errors, one Windows platform skip**. This is not a rerun of unrelated backup/recovery and inactive cost-policy suites.

| Actual execution | Run | Passed | Failures | Errors | Skipped | Seconds |
|---|---:|---:|---:|---:|---:|---:|
| Original broader run | 391 | 389 | 0 | 1 | 1 | 1024.56 |
| Appointment protocol recheck after artifact repair | 5 | 5 | 0 | 0 | 0 | 12.91 |

The initial protocol error was a missing default `build/backend/allocation_system.exe` in the new worktree: one test calls the default resolver directly instead of the configured external artifact. The source/binary hashes of the existing unchanged Student artifact and manifest were verified, then copied to the new worktree's default ignored build path without replacing any existing file. The unchanged five-test module passed on recheck. **The original failed transcript is preserved; no new complete run is claimed.** [Original exact results/log](regression/tests.json), [full transcript](regression/tests.txt), [successful recheck](protocol-artifact-recheck/tests.json), [artifact integrity](backend-artifact.json), [accepted result accounting](accepted-results.json).

All appointment, room, equipment, waiting-list (49/49), feedback, recurring workflow/policy, calendar, schedule, notification, account/session, student dashboard/UI, gateway and application entry-point modules in this selected set passed after that setup repair. **No database test was skipped.** The sole skip is `test_linux_execute_permission_is_checked`: “POSIX permission check runs on Linux.” Four independent module processes used owned disposable PostgreSQL schemas. Browser acceptance had completed before this broader run; no browser run overlapped it. The C++ run completed as the broader run started. Existing valid tests were retained unchanged.

Actual Flask/Edge browser acceptance: **41 views**, widths 1440/768/390/320, **884 keyboard steps**, including 45 native date/time/month picker subfocus steps; all five roles were exercised. No page overflow, unlabeled visible tested field, application JavaScript exception or unexpected page HTTP error was observed. Native picker subcontrols use Edge's own focus indication; a diagnostic capture was visually inspected rather than requiring an outer CSS outline that the browser does not expose during native subfocus. This is not a screen-reader certification.

**41 actual POSTs**, including genuine login/logout, availability, blocks, professor decisions, rescheduling, cancellation, invitation responses, read-state changes and denied attempts. **28 domain/rejection outcomes** were independently checked using fresh committed PostgreSQL transactions, including no mutation on rejected actions, exact current-revision approval/commitment transitions, no reservation from an optional room response, and persisted recipient read timestamps. The remaining POSTs are successful authentication/session operations; role redirects, CSRF rejection and logout were checked in the browser. No response or persistence mocks were used for the browser workflow.

Exact split: **15 successful domain mutations, 13 rejected POSTs with unchanged captured domain state, 13 successful login/logout POSTs**. Passwords, CSRF tokens and cookies are omitted from tracked state evidence; identities and activities are synthetic.

[Browser results](browser/browser-results.json), [control inventory](browser/controls.json), [raw before/after states](browser/post-states.json), [independent persistence checks](browser/persistence-verification.json), [cleanup proof](browser/cleanup.json). The review server stopped and the last owned review schema was verified absent. Earlier failed harness attempts also ran fixture cleanup; failure reasons were a missing synthetic academic binding, a form `action` property collision in the control collector, native-picker outer-outline assertions and the reproducible calendar focus defect. No such attempt is reported as a pass.

22 real application screenshots are inventoried in [screenshots.json](screenshots.json), with SHA-256/dimensions/PNG verification. Representative views: [hours 320](browser/hours-320.png), [appointment 1440](browser/appointment-1440.png), [week 320](browser/calendar-week-320.png), [room invitation 320](browser/room-invitation-320.png), [rescheduled approvals](browser/reschedule-invalidated-approvals.png). The existing shared shell was preserved; these captures do not claim completion of the future professor Campus Space frontend.

## Remaining decisions and delivery sequence

1. Approve a separate eligibility-review design/migration: review state, reviewer/audit, reviewed revision and invalidation, admin-only actions, filtering every allocation snapshot, stale-run safety, legacy/import treatment and regression/security proof. The C++ JSON schema and algorithms can remain unchanged by filtering eligible inputs in the Python persistence boundary, subject to that review.
2. Separately approve academic notification source/schema, producers, recipient/destination policy and migration. Existing appointment/room notifications need no replacement.
3. Decide any future private attribution-based teaching entitlement explicitly. Current public metadata does not establish ownership or an enrollment relationship; the read API does not add such a permission.
4. Implement the [bounded professor frontend sequence](frontend-plan.md): Home/navigation → appointments/hours → personal schedule → read-only academic tracking → intake only after the gate → calendar/Inbox → cross-role/mobile acceptance. Reuse shared components and services; do not independently redesign Campus Space.

This safe backend increment can be reviewed locally. The full Professor Services v1 is **not ready** for acceptance while intake and academic notification contracts remain unresolved. Preserve Student Draft PR #24's dependency and inspect the eventual merged main revision before proposing a professor Draft PR. No professor push, PR, merge, deployment, operational database change or research edit is authorized by this report.

## Local commits

| SHA | Focus |
|---|---|
| `19457e4aea950b34bfbba4e38dda031a6013fd08` | Handoff import, reviewed source/contracts and blocked gate |
| `9a751c6ba383bce06d7875cd358e33af6c1a93f7` | Owner-only read API and 14 real database/engine/security tests |
| `4bf6f7c3bde8f4915cbc2f6f8e70aa7b3692a450` | Calendar keyboard correction and browser/persistence evidence |
| `3c3af41928f0a3dae55a70bdc743b0ee83785ee7` | Additional three existing-workflow tests, contract-gap and C++/artifact proof |

The final documentation/evidence commit follows these four local commits. Its SHA is available from `git log -1`; no professor commit is on the remote. The original student HEAD/remote and main were rechecked unchanged at final verification.

**CHANGES REQUIRED**
