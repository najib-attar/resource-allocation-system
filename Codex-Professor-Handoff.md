# Codex — Professor Use Cases v1: Backend-first implementation handoff

> Historical implementation handoff. Professor Services is now merged through
> [PR #25](https://github.com/najib-attar/resource-allocation-system/pull/25).
> Original task instructions below are preserved as provenance; they do not
> describe current development status. See the
> [Professor Services guide](docs/professor-services/README.md) and approved contracts.

You are implementing the next part of the University Resource Allocation and Scheduling System: **Professor Services**.

The accompanying handoff package contains `professor_use_cases_v1.pdf`, separate one-page `UC-PROF-01.pdf`–`UC-PROF-09.pdf`, and `professor_backend_audit.md`. Read all of them.

## Ground rules

- **Do not assume UI-10 is already merged.** Before touching code, inspect the actual repository/worktrees, Git branch status, `docs/ui/student-portal/acceptance-report.md`, traceability and commits; report whether the reviewed student frontend is on `main`, a Draft PR, or a local-only branch.
- Work in a **new dedicated professor worktree** and branch (for example `feature/professor-services`) based on an explicitly selected, reviewed base. Never modify the running Student UI worktree or the separate CDMCS research worktree.
- The role is `Instructor` in the backend. Do not create a duplicate `Professor` role. All endpoints, queries, permission checks, forms and tests must enforce the existing account/session identity.
- Preserve the C++ JSON engine protocol, PostgreSQL operational model, existing appointment service, student room approval semantics, privacy rules and existing backend behavior.
- Do not implement all nine use cases blindly: UC-PROF-01..05 are **existing**, while UC-PROF-06..09 are **proposed capabilities** needing role-scoped backend work.

## Stage 0 — Evidence and gap analysis (do first)

1. Read `web/security.py`, `web/app.py`, relevant route/service/models files, availability/calendar projections, academic request forms and test suites.
2. Compare against the latest local checkout and student UI acceptance report; don't rely on old GitHub `main` findings if the local code has changed.
3. Produce a use-case-to-backend matrix: actor/authorization, endpoint, validation, transaction, C++ call, persistence, notifications, result display, tests and missing parts.
4. Resolve role distinctions: ordinary Instructor, staff faculty-room approver, equipment custodian, administrator, TeachingAssistant and Student.
5. Identify any open domain decisions that would introduce new authorization, lifecycle policy, data model or engine changes. **Do not guess or silently change those contracts.** Escalate material policy decisions as documented blockers.

## Stage 1 — Verify existing professor behavior

Verify and, where needed, correct UC-PROF-01..05 in focused commits:

- Own appointment hours: dates, exclusions, add/remove, no cross-user modification.
- Required-professor appointment approval: current revision, all required professors, conflict rechecks, cancellation, optional students never veto.
- Dated personal blocks and own calendar, no private third-party events.
- Optional invitation to student room requests: accept/decline with conflicts, **never** staff room approval authority.
- Scoped calendar, notifications and authorized details.

Do not rewrite these stable services merely for consistency. Do not grant ordinary Instructor access to admin request pages or staff-only inventory/review actions.

## Stage 2 — New professor academic requests (one small PR/commit group per type)

Implement UC-PROF-06, 07 and 08 only where the existing domain contracts make it safe:

- Authenticated Instructor can submit **only an Instructor-owned** Exam, OneTime/Recurring teaching, or CommitteeMeeting academic request through a new role-scoped intake. Never accept arbitrary user IDs from forms.
- Reuse existing validators, Request repository, occurrence/participant models and C++ request types. Do not remove `spaceId` from a contract that currently requires it; if a new user experience needs additional mapping, document and test the mapping before implementing it.
- Exam requires course code, course name, exam type and split flag; room capacity/facilities constraints and time must be validated.
- CommitteeMeeting requires mandatory committee participants with roles; this remains **separate** from student appointment approvals.
- Academic resource requests remain Pending until authorized allocation results are published. **Do not let ordinary instructors run the university allocation engine, change strategies, publish calendar events or assign themselves rooms**.
- Audit transactions, retries, owner visibility, conflicts and errors. Do not invent a new per-request administrative approval state unless explicitly authorized; distinguish existing engine decisions from possible future human approval policy.
- If implementation needs schema changes, new access policy, or a different engine contract, report the exact reason and stop that part for decision rather than making an unreviewed change.

## Stage 3 — Academic request results and assignments

Implement UC-PROF-09 using owner-scoped list/detail/read models only. Provide status, allocation result, appropriate calendar linkage and explanatory messages. Explicit academic calendar instructor attribution is *metadata*, not a verified teaching relationship, and publication remains admin-only. Do not invent dated activities where academic period binding is unresolved.

## Stage 4 — Professor frontend, after backend contract review

Use the accepted Student Portal (Campus Space) design system for shared layout, components, status semantics, typography, responsiveness and interaction. Create a professor-oriented Home and service pages **without copying all student services into professor navigation**. Suggested navigation: Home; My Appointments; Office Hours; My Schedule; Academic Requests; Calendar; Inbox. Show only services that genuinely exist and are authorized. Do not show placeholders as functional buttons.

Deliver UI in bounded groups: Professor Home; Meetings/availability; Academic requests (Exam, Teaching, Committee); Outcomes/calendar; Notifications; final acceptance. Each form and action must be verified end-to-end against the real backend.

## Stage 5 — Verification and documentation

- Test all six use-case categories and special cases with actual isolated PostgreSQL fixtures, **at least** Instructor, Student, Staff, TeachingAssistant and Administrator roles, and unauthorized cross-user/IDOR attempts.
- Run relevant Python/PostgreSQL, C++, engine runtime smoke, browser 1440/768/390/320, keyboard/assistive-technology checks.
- Trace each displayed button to its endpoint, service, DB/engine operation and resulting UI. Verify actual POST persistence and calendar/notification consequences, not only screenshot rendering.
- Keep valuable tests. Remove only proven dead code after cross-role reference checks.
- Add `docs/srs/professor-workflows.md` (or update an existing equivalent), use-case PDFs, feature matrix, architecture note and acceptance report; avoid duplicative documents.
- Make focused local commits and report exact SHA, tests, failures, screenshots and open risks.

## Delivery and boundaries

Stop on material policy ambiguity, unexpected local/remote branch changes, role leaks, engine contract changes or unsupported database migrations. Continue across unblocked page groups autonomously.

Do not push, create a PR, merge, deploy, change production DBs, modify CDMCS, or rewrite student UI commits without explicit permission.

Final status must be **READY FOR PROFESSOR ACCEPTANCE REVIEW** or **CHANGES REQUIRED**, with a completed feature-to-backend traceability table. Do not claim the professor portal complete from visual tests alone.
