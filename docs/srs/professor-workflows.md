# Professor Services v1 — approved contracts

The nine supplied UC-PROF PDFs and handoff audit are reference material. The user's later eligibility, legacy-data and published-revision decisions govern implementation. Original handoff files remain unchanged.

## Reviewed source and isolation

`codex/professor-services-v1` uses a separate worktree based on completed Student UI-10 commit `747c925b14c29368e6cb9bc8b2e2d9d33c494462`. Student Draft PR [#24](https://github.com/najib-attar/resource-allocation-system/pull/24) targets main and remains an explicit dependency. Professor work is local; no professor push, PR, merge or deployment is authorized.

Reviewed main was `d9a63f3ef0f5f22b56a79af670c740a13f7bb6ad`. Its seven main-only governance/cost-policy commits were inspected, not merged or edited. C++ strategies, protocols, CDMCS and authentication/session internals remain unchanged.

## Identity and supported inputs

The existing role is **Instructor**. An active enabled Instructor may submit, read and revise only self-owned academic requests. Identity comes from the signed session and is checked again in the service. Administrator flags, committee participation, public attribution and declarations grant no access to a peer's private request.

Exam, OneTime, Recurring and CommitteeMeeting reuse ResourceRequest, explicit resource IDs, weekday/minute slots, exam details and required participants. Faculty/course/activity descriptions are declarations, not verified affiliations. New exams require course code/name and a supported examination type. Committees require at least one active, unique participant; they do not create student-professor appointments. Existing resource/role/conflict rules still determine allocation.

Academic recurrence uses the existing weekly-slot contract, not the dated student reservation-series contract. Dated commitments require existing explicit period bindings; no dates, enrollment or faculty entitlement are inferred.

## Three independent state axes

| Axis | Authoritative state | Meaning |
|---|---|---|
| Administrative eligibility | Pending Eligibility Review / Eligible / Eligibility Rejected, reviewer/reason/time, reviewed revision and review version | Human review; never a reservation or guarantee |
| Allocation | Existing Pending / Approved / Rejected from the active successful run | Existing C++ outcome; Pending means no active decision for this revision |
| Calendar publication | Existing academic bindings, publication metadata and visibility | Dated projection; review does not change existing commitments |

New records begin Pending Eligibility Review. A different active administrator may approve/reject with a reason and current request/review revisions. Self-review is prohibited, including administrator-owned legacy requests; another administrator is needed. Review alone changes no reservation or calendar commitment.

Only Eligible records reviewed at the current request revision enter allocation. All repository snapshot/start/publication paths enforce this. Presentation snapshots retain all records but cannot be executed. The production Python gateway refuses raw unguarded academic inputs; standalone protocol fixtures require an explicit opt-in unused by production. C++ JSON is unchanged and its CLI has no database publication authority.

## Revisions, concurrency and audit

Owners may revise unpublished requests with an expected revision. Material revisions reset eligibility, clear the reviewer/reviewed revision and record history. Database triggers also invalidate reviewed parent/subtype/slot/participant edits outside the service.

Every request included in the active publication is read-only, including engine-rejected outcomes and requests whose eligibility was later rejected. Service and database checks cover direct requests and concurrency. Professor revisions and eligibility decisions leave existing reservations, request inputs and calendar commitments intact until authorized replacement excludes the request. Separate existing administrative calendar-publication metadata operations retain their own permissions and semantics. Versioned replacement requests are explicitly deferred.

Academic inputs, eligibility decisions, run capture and publication serialize through ApplicationState. Runs store input revision plus immutable per-request revision/review-version proof. The gateway revalidates captured inputs before execution. A later edit/review makes an in-flight run stale; publication refuses it and retains previous results. It does not retroactively rewrite already captured engine input.

Eligibility events and run proofs cannot be rewritten, deleted or truncated. Request/review versions reject stale forms. Existing global CSRF covers all new POSTs. Professors receive no eligibility, allocation, strategy, staff room-review or calendar-publication authority.

## Legacy compatibility and migration

Migration `0051a` adds `faculty_declaration` and three tables: `request_eligibility`, `eligibility_event`, `allocation_eligibility` (61 application tables). All existing requests become Legacy / Pending Eligibility Review with baseline revision and audit record. None is automatically approved. Allocations, decisions, history, active publication and reservations are preserved.

Outstanding legacy reviews in the current published batch block a new run and replacement publication. The administrative queue lists their IDs and explains the block. Rejection excludes a legacy record from future snapshots but preserves its reservation until authorized replacement; the review screen warns about the pending change. Every legacy request requires individual review before future participation, including records outside the current publication.

Rollout requires a maintenance window: stop old workers, back up, apply Alembic through `0051a`, restart matching code. Migration increments input revision to invalidate old in-flight publications. No operational migration was executed. A populated downgrade refuses eligibility/provenance/history loss; archival/rollback needs separate review. Historical fixture replay is restricted to owned random test schemas and is not a production rollback tool.

New imports, repository saves and demo seeds remain pending by default. Local-demo `seed --review-academics` explicitly reviews only newly generated fictional data through the real administrator service; it does not approve existing profiles or legacy databases. Admin save/run shortcuts now lead to review first.

## Existing workflows and remaining scope

UC-PROF-01–05 retain appointment hours/approvals, personal blocks, optional room invitations, calendar and Inbox. Confirmed appointments prevent incompatible blocks/hour removal. Optional attendance grants no faculty approval or custody rights.

UC-PROF-06–08 have minimal shared Jinja intake/revision forms and JSON submission. UC-PROF-09 has owner list/detail filters, allocations, reasons/history and explicit bindings. Reads are private/no-store. Database failures return safe errors; invalid/private/stale operations commit no partial change.

Academic outcome notifications remain deferred: Notification has no ResourceRequest event source. Source/schema, producers and recipient/destination policy need separate approval. Existing notifications remain supported. The Professor Portal frontend now follows the implemented [frontend sequence](../professor-services/frontend-plan.md), reusing the Student Campus Space system. Academic notifications, cancellation and versioned published replacement remain deferred.

See [traceability](../professor-services/traceability.md) and [acceptance](../professor-services/acceptance-report.md) for executed evidence and limitations.
