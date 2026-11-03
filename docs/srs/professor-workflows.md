# Professor Services v1 — reviewed contracts and decisions

This review uses the supplied nine UC-PROF PDFs and `Codex-Professor-Handoff.md` as reference material. The user's subsequent instructions and explicit policy clarification control implementation. The supplied `professor-backend-audit.md` is historical input, not evidence that the current code behaves as described.

## Reviewed revision and isolation

Student UI-01–UI-10 is committed through `747c925b14c29368e6cb9bc8b2e2d9d33c494462` on `design/student-portal`. It was clean, pushed without force, and is in **Draft PR [#24](https://github.com/najib-attar/resource-allocation-system/pull/24)** targeting `main`; all 18 student commits were verified in the PR. It has not been merged.

Professor development uses **`codex/professor-services-v1`**, a separate worktree based on that exact student revision. It therefore depends on PR #24. No professor branch was pushed or professor PR created. After student merge, the dependency must be reviewed against the resulting main revision before preparing a professor PR; this work does not rewrite or merge the student commits.

Fetched `origin/main` was `d9a63f3ef0f5f22b56a79af670c740a13f7bb6ad`; common ancestor `610c104`. The student/professor base is 18 commits ahead and seven behind main. Those seven commits cover B2/CDMCS governance, cost-policy services/tests/docs and CI. They do not change the appointment, resource-request persistence or professor ownership contracts reviewed here. They were inspected, not merged, modified or activated. CDMCS and C++ sources remain unchanged.

## Authorized roles and declarations

The backend role is **Instructor**, not a new Professor role. Ordinary Instructors may manage their own appointment availability and dated blocks, decide required appointment invitations, respond to optional student-room invitations and read their own academic requests. A room invitation does not grant faculty review rights. Staff faculty approvers, equipment custodians and administrators retain their existing separate permissions. Student and TeachingAssistant accounts gain no Instructor authority.

The user explicitly approved allowing any active Instructor to submit a **self-owned** academic request, with course/faculty/activity descriptions treated as declarations rather than verified affiliations. Requester identity must come from the session, never a client field. However, the user also required **administrative eligibility review before any unreviewed or rejected request reaches the allocation engine**. The latter requirement blocks intake on the current backend.

## Blocking gap: eligibility review before allocation (UC-PROF-06–08)

Observed path: administrative `/add-request` → `Repository.save_request` → ResourceRequest/subtype rows and `RequestHistory(kind=saved, message=pending allocation)` → `Repository.start_run` → `snapshot_from_session` → `EngineGateway.execute` → `Repository.publish_run`. The snapshot iterates **every** ResourceRequest. There is no administrative review state, reviewer, approved revision or eligibility filter. Pending means absence of a published engine decision; it is not a human approval gate. `RequestDecision.Approved/Rejected` is an engine outcome, not eligibility review.

Consequently, no professor create/update endpoint or functional submission button is implemented. Existing administrator behavior is preserved. Merely inserting a Pending request would violate the user's condition even if only administrators could start allocation.

Separate authorization/design review is required for:

1. Persistent eligibility lifecycle (unreviewed, eligible, rejected), reviewer identity/time, explanation, and the precise reviewed request revision.
2. Administrator-only review/rejection actions and audit history; editing a reviewed request must invalidate eligibility.
3. Snapshot construction that includes only currently eligible reviewed revisions, enforced at the server boundary, for every strategy and engine entry point. Unreviewed/rejected rows must never be sent to C++.
4. Transactional input revision handling and stale-run checks when review decisions or request revisions change.
5. A migration and explicit treatment of historical administrator/imported requests, existing active publications, retries and review rejection notifications. Do not silently classify legacy records as approved.
6. Regression/security tests proving the gate, all five roles, cross-user protection, zero reservation on submission and unchanged engine JSON/algorithms.

These require schema and scheduling-input policy changes. They are **documented, not implemented**. Existing explicit `spaceId`, weekday/minute slots, ExamDetails and CommitteeMeeting participant contracts remain authoritative. Recurring academic requests are not the separate student recurring-reservation workflow. CommitteeMeeting is not a student-professor appointment.

## Safe implementation: UC-PROF-09 owner-only reads

`GET /professor/academic-requests` and `GET /professor/academic-requests/<id>` require a signed-in active, enabled Instructor account. Both the HTTP guard and the service enforce role; queries restrict `requester_id` to that actor before loading details. Unknown and non-owned IDs receive the same private error. Administrator flags, public calendar visibility, instructor attribution and committee participation do not bypass this owner-only scope.

List filters are `type` (Exam, OneTime, Recurring, CommitteeMeeting), `status` (Pending, Approved, Rejected), `limit` (1–100; default 50), `offset` (0–2147483647). List order is newest submission first. Status/allocations come only from `ApplicationState.active_run_id` when that run is successful. No current decision means Pending. Previous active results remain visible if a newer run fails; changed inputs produce an explicit warning. Approved means an active engine allocation, never human eligibility approval.

Detail includes declared exam metadata, weekly slots, mandatory committee participants/roles, requested resource/constraints, active allocation rooms/counts, request history and explicit academic period bindings. It does not expose global engine snapshots, raw decision payloads, other requests, login records or private peer calendars. Reads use one PostgreSQL repeatable-read, read-only transaction. Responses are private/no-store. Invalid inputs return 400, unavailable/private requests 403, database failures a generic 503. Authentication/session/CSRF internals are unchanged. There is no academic mutation endpoint.

Dates are never inferred from weekly slots. Calendar projection remains in `UniversityCalendarService` and requires successful active allocations plus explicit academic bindings. Public instructor attribution is display metadata, not ownership or an enrollment/teaching assignment. The current public/relevant calendar behavior is retained; a new private attribution-based schedule entitlement requires separate approval.

## Additional limitations

- Academic ResourceRequest notifications have no supported source: Notification requires an appointment, room, equipment or feedback event. Adding academic notification events, source foreign keys, producers, recipient policy and authorized destinations requires a separately reviewed schema change. UC-PROF-09 academic notifications are deferred; current appointment/room notifications remain supported.
- Existing hour deletion refuses removal while the Instructor has future confirmed appointments; this conservative compatibility behavior is preserved.
- Administrative calendar publication, period bindings, allocation strategy and execution remain inaccessible to ordinary Instructors.
- This increment delivers backend verification and a read API, **not the professor frontend**. See [traceability](../professor-services/traceability.md), [frontend plan](../professor-services/frontend-plan.md) and [acceptance report](../professor-services/acceptance-report.md).
