# Administration use cases — approved v1 scope

**Requirements baseline:** `aae966bf8fa6390348c6e6a2d53a24faf6c0ab70`.
The original status classifications below describe that baseline, before this
implementation. They are retained as specification history. Current delivery and
verification are recorded in [traceability](traceability.md),
[screen coverage](screen-coverage.md) and [acceptance](acceptance-report.md).

| ID | Use case | Current state / scope |
| --- | --- | --- |
| UC-ADM-01 | Administration Home and Action Queue | PROPOSED COMPOSITION; EXISTING UNDERLYING SERVICES |
| UC-ADM-02 | Inspect University Directory and Resource Configuration | PARTIAL: READ-ONLY DIRECTORY / EXISTING ROOM POLICY; NEW GENERAL EDITING DEFERRED |
| UC-ADM-03 | Provision and Revoke Administrative Access Safely | PARTIAL: CLI PROVISIONING EXISTS; WEB SECURITY UI PROPOSED / GATED |
| UC-ADM-04 | Review Professor Academic Eligibility | IMPLEMENTED |
| UC-ADM-05 | Run and Inspect Campus Academic Allocation | IMPLEMENTED; PRE-RELEASE PRODUCTION HARDENING OUTSIDE SCOPE |
| UC-ADM-06 | Configure Academic Calendar and Publication | IMPLEMENTED; UNRESOLVED LEGACY BINDINGS REQUIRE REVIEW |
| UC-ADM-07 | Configure Room Approval and Decide Student Room Requests | IMPLEMENTED; APPROVAL SCOPE IS FACULTY-BASED |
| UC-ADM-08 | Manage Equipment Inventory, Custody and Loan Lifecycle | IMPLEMENTED FOR DESIGNATED STAFF / ADMINISTRATORS |
| UC-ADM-09 | Administer Waiting Lists and Recurring Reservation Policy | IMPLEMENTED WITH EXPLICIT CONFIGURATION |
| UC-ADM-10 | Review Resource Feedback and Maintenance Issues | IMPLEMENTED FOR AUTHORIZED STAFF |
| UC-ADM-11 | Inspect Operational History and Produce Read-Only Reports | PARTIAL: AUDIT DATA EXISTS; UNIFIED ADMIN REPORTING PROPOSED |
| UC-ADM-12 | Receive Administrative Work Updates and Inbox | PARTIAL: EXISTING SERVICE NOTIFICATIONS; ACADEMIC REQUEST ALERTS DEFERRED |

## Out of scope / future policy proposals

- **UC-ADM-F01 Institutional preference and cost-policy activation** — database/governance foundations exist, but public admin controls, validated weights, actual scheduler activation and authority bootstrap do not. **Do not build UI or enable optimizer.**
- **UC-ADM-F02 Production database operations** — backups, migrations and worker restarts remain documented operator tasks; do not add a web button for arbitrary backup, SQL, rollback or deployment.
- **UC-ADM-F03 Published academic request cancellation and versioned replacement** — explicitly deferred in Professor Services; requires a separate reservation-safe lifecycle and approval policy.
- **UC-ADM-F04 Real university SIS/İTÜ import or enrollment verification** — postponed; do not ingest real faculty/student records or infer course teaching ownership.

## Prioritization

**P0 — verify and unify existing behavior:** ADM-04 through ADM-10, ADM-12 (existing notices only) and security boundary tests.

**P1 — usable administration workspace:** ADM-01 and read-only components of ADM-02/ADM-11; shared frontend using actual roles, actions and service statuses.

**P2 — controlled extensions needing policy review:** web-side account management, mutable resource directory, exports and new academic notifications. Avoid implementation until separately approved.

## State distinction

Academic **eligibility** (Pending/Eligible/Rejected), C++ **allocation** (Pending/Approved/Rejected) and calendar **publication** are independent. Room confirmation, equipment reservation, equipment physical handover and waiting-list preapproval are different lifecycles. Every admin surface must respect these differences.

## Use-case specifications

### UC-ADM-01 — Administration Home and Action Queue
**Status:** PROPOSED COMPOSITION; EXISTING UNDERLYING SERVICES
**Primary actor:** University administrator with an authorized account
**Other actors:** Academic reviewers; faculty approvers; equipment custodians
**Goal:** Present one operational landing page with accurate, authorized actions and cross-service status, without treating a request as a reservation.
**Preconditions:** Authenticated administrator; read access to the underlying scoped services.
**Main success scenario:**
1. Open Administration Home and view bounded counts for pending academic reviews, allocation runs, room and equipment decisions, feedback and waiting-list activity.
2. Open a queue item and navigate to the existing authoritative service page.
3. Use separate status badges for academic eligibility, engine allocation and calendar publication.
4. Refresh a filtered queue; counts and records come from a consistent authorized PostgreSQL read model.
**Alternative outcomes and constraints:**
- An empty queue displays a genuine empty state; never fabricate metrics or actions.
- Unavailable data or a stale decision shows a safe error, never a synthetic success.
- Do not disclose unrelated private appointments or student records.
**Result:** An authorized read-only overview links to real service actions; it creates no reservation.
**Implementation boundary:** NEW AdminDashboardService and role-aware Home; reuse service read models. No new scheduling engine, aggregation table, or administrative global visibility by default.

### UC-ADM-02 — Inspect University Directory and Resource Configuration
**Status:** PARTIAL: READ-ONLY DIRECTORY / EXISTING ROOM POLICY; NEW GENERAL EDITING DEFERRED
**Primary actor:** Authorized university administrator
**Other actors:** Designated faculty staff; university users
**Goal:** Inspect users, spaces, ownership and resource constraints; direct operators to approved configuration workflows.
**Preconditions:** Authenticated administrator; resources and ownership are explicitly recorded.
**Main success scenario:**
1. Browse and search existing user and space records with accurate role, space-type, capacity and feature metadata.
2. Inspect ownership/approver configuration without exposing unnecessary user data.
3. Open the existing room policy/configuration screen when authorized.
4. Record unsupported metadata corrections as a review item rather than silently editing operational identities or resources.
**Alternative outcomes and constraints:**
- A missing faculty owner or approver remains unconfigured; never infer one from a professor label.
- A space with published reservations must not be destructively changed without a separate approved policy.
- Bulk imports, arbitrary resource CRUD and external university synchronization are outside the accepted v1 contract.
**Result:** Verified directory visibility and authorized access to existing room policy actions.
**Implementation boundary:** Reuse /users, /spaces and /rooms/configuration. General web resource CRUD, campus restructuring, class enrollment and imports require a separate approved data/authorization specification.

### UC-ADM-03 — Provision and Revoke Administrative Access Safely
**Status:** PARTIAL: CLI PROVISIONING EXISTS; WEB SECURITY UI PROPOSED / GATED
**Primary actor:** Trusted account administrator
**Other actors:** Existing university account holders
**Goal:** Manage legitimate access using existing university identities without self-service role escalation.
**Preconditions:** An existing university identity is verified; a trusted provisioning channel is available.
**Main success scenario:**
1. Verify the university identity, actual role, and explicit administrator capability before issuing access.
2. Provision or reset the account via the existing trusted CLI process and prompted secret input.
3. Confirm the resulting account can access only its permitted routes.
4. Verify password-reset or disable/revocation behavior using isolated test accounts and session checks.
**Alternative outcomes and constraints:**
- A non-existent or unauthorized identity is rejected.
- Never enable browser-based admin role grants, password display or bulk account editing until separately approved.
- A staff/Instructor role is not automatically equal to administrator capability; logout/revocation is enforced server-side.
**Result:** Access is managed through the existing trusted workflow and all sessions/permissions respect service rules.
**Implementation boundary:** Existing scripts/manage_accounts.py and web/account_service.py. A web admin account console is HIGH-RISK PROPOSED SCOPE: no implementation until threat model, authority, recovery and audit rules are approved.

### UC-ADM-04 — Review Professor Academic Eligibility
**Status:** IMPLEMENTED
**Primary actor:** Authorized university administrator
**Other actors:** Instructor/requester; academic allocation workflow
**Goal:** Confirm an instructor-owned academic request may be considered for allocation, without allocating space.
**Preconditions:** Academic request exists and is Pending Eligibility Review at a known request/review revision.
**Main success scenario:**
1. Open the academic eligibility review queue and inspect the current request and declared academic context.
2. Confirm the reviewer is eligible and is not the requester.
3. Record Eligible or Eligibility Rejected with reason and exact revision/version.
4. Review immutable decision history and ensure only current Eligible revisions are admitted to future allocation.
**Alternative outcomes and constraints:**
- Concurrent material revision invalidates the review; return a refresh/conflict response.
- Reviewer cannot approve their own academic request, even if they hold administrative privileges.
- Prior published reservations remain intact until an authorized replacement; no automatic publication follows review.
**Result:** Audited eligibility decision only; no booking or calendar publication.
**Implementation boundary:** Existing /academic-eligibility/, web/academic_eligibility.py, revision 0051a. Preserve separate eligibility/allocation/publication axes and legacy review requirements.

### UC-ADM-05 — Run and Inspect Campus Academic Allocation
**Status:** IMPLEMENTED; PRE-RELEASE PRODUCTION HARDENING OUTSIDE SCOPE
**Primary actor:** Authorized technical administrator
**Other actors:** Instructor requesters; C++ allocation engine
**Goal:** Execute an approved resource-allocation strategy against eligible requests and publish only validated current results.
**Preconditions:** Verified C++ executable; PostgreSQL active; required eligible revision and published-run preconditions satisfied.
**Main success scenario:**
1. Inspect eligible request queue and choose one existing strategy from supported choices.
2. Start allocation from the authorized technical dashboard and create a consistent, ordered snapshot.
3. Execute validated C++ JSON protocol outside the database transaction.
4. Validate revision proofs and results; atomically publish the run if still current.
5. Inspect assignments, rejections, suggestions, audit/history and schedule projections.
**Alternative outcomes and constraints:**
- Pending/rejected or stale academic revisions are excluded.
- Engine timeout, invalid response or concurrent revision change must not replace the active run.
- Do not equate an engine allocation with published dated university events where period binding is absent.
**Result:** A validated active allocation run with traceable outcomes and no partial publication.
**Implementation boundary:** Reuse /, /run-allocation, /set-strategy, /allocation-summary, /requests and web/allocation_workflow.py. Keep JSON v1/C++ contracts and strategy semantics unchanged.

### UC-ADM-06 — Configure Academic Calendar and Publication
**Status:** IMPLEMENTED; UNRESOLVED LEGACY BINDINGS REQUIRE REVIEW
**Primary actor:** Authorized university administrator
**Other actors:** Instructors; affected calendar viewers
**Goal:** Bind only verified academic applicability and control publication visibility without inventing dates or enrollments.
**Preconditions:** Existing academic result or saved campus commitment; real applicability dates and publication permissions are known.
**Main success scenario:**
1. Inspect records that lack explicit academic period/calendar binding.
2. Configure only supported applicability and calendar setup inputs.
3. Review resulting dated academic events and authorized audience.
4. Publish/unpublish permitted academic metadata and optionally attribute an Instructor as display metadata.
5. Verify that only authorized participants see private information.
**Alternative outcomes and constraints:**
- Missing/unresolved dates produce a warning, not guessed event dates.
- Instructor attribution does not grant course ownership or edit rights.
- Calendar visibility does not automatically create a new allocation or appointment approval.
**Result:** Audience-scoped academic calendar events reflect explicit, approved publication and date binding.
**Implementation boundary:** Existing /appointments/calendar-setup and /calendar/publications; web/university_calendar.py. Preserve date-aware, permission-scoped reads and separate source workflows.

### UC-ADM-07 — Configure Room Approval and Decide Student Room Requests
**Status:** IMPLEMENTED; APPROVAL SCOPE IS FACULTY-BASED
**Primary actor:** Designated faculty approver (eligible Staff/Administrator)
**Other actors:** Student organizer; invited professors
**Goal:** Approve or reject eligible student room reservations using correct faculty authority and current availability.
**Preconditions:** Approver assignment is explicitly configured; request is pending and user has authority.
**Main success scenario:**
1. Inspect room ownership and configured faculty approvers.
2. Review the request, recommended room, participants, date or recurring occurrence preview.
3. Recheck capacity, conflicts, policy and current request revision.
4. Approve all required or selected eligible occurrences per supported consent, or reject with reason.
5. Verify reservation, notifications and release behavior when cancelled.
**Alternative outcomes and constraints:**
- A professor merely invited to a room event cannot grant faculty approval.
- Pending or rejected requests reserve nothing.
- Partial recurring approval uses only the student-approved series policy; stale or conflicted decisions fail.
**Result:** Auditable room decision and correct resource reservations when confirmation succeeds.
**Implementation boundary:** Existing /rooms/configuration and /rooms/<id>/decision, RoomRequestService. Preserve designated authority, recurring semantics and idempotency.

### UC-ADM-08 — Manage Equipment Inventory, Custody and Loan Lifecycle
**Status:** IMPLEMENTED FOR DESIGNATED STAFF / ADMINISTRATORS
**Primary actor:** Authorized equipment custodian or administrative inventory manager
**Other actors:** Student borrower; faculty inventory owner
**Goal:** Manage tracked physical assets and execute approval, handover, return and extension actions without treating reservation as possession.
**Preconditions:** Faculty ownership, custodian assignment and individual asset identifiers exist.
**Main success scenario:**
1. Review faculty equipment inventory, types, specifications and custodian assignments.
2. Inspect borrower requests, required quantities, dates and supported recurring periods.
3. Approve/reject with actual availability; approved means reserved, not handed over.
4. Record physical asset handover, verified partial/full returns, condition and any permitted extension.
5. Review overdue warnings and audit history while preserving actual asset location.
**Alternative outcomes and constraints:**
- Only designated custodian may perform custody operations; not every Instructor qualifies.
- Due date must never be treated as automatic physical return.
- Concurrent availability or asset-state conflicts reject stale operations.
**Result:** Resource inventory and actual custody state remain consistent and auditable.
**Implementation boundary:** Existing /equipment/inventory/<faculty_id>, /equipment/custodians and /equipment/<id>/<action>, web/equipment_service.py. No assumed procurement or purchasing module.

### UC-ADM-09 — Administer Waiting Lists and Recurring Reservation Policy
**Status:** IMPLEMENTED WITH EXPLICIT CONFIGURATION
**Primary actor:** Authorized university policy administrator / designated faculty reviewer
**Other actors:** Students; faculty approvers; existing room/equipment services
**Goal:** Maintain bounded, fair waiting-list and recurring reservation behavior under explicit campus policy.
**Preconditions:** Requested policy/semester belongs to supported configuration and actor is authorized.
**Main success scenario:**
1. Review waiting-list queue, faculty preapprovals, ranking and eligibility.
2. Set explicit minimum advance notice and permitted priorities where authorized.
3. Configure semesters and recurring request quotas/weekly limits using supported controls.
4. Review only permitted priority overrides with recorded reasons.
5. Trigger/review safe rechecks; booking occurs only through existing matching and reservation services.
**Alternative outcomes and constraints:**
- No hidden default semester or notice is invented.
- Preapproval is not a reservation; actual availability and ownership must be rechecked.
- Canceled/expired requests cannot be silently resurrected; access remains faculty scoped.
**Result:** Explicit versioned policies and auditable waiting-list decisions without duplicate booking authority.
**Implementation boundary:** Existing /waiting-lists/configuration, review/refresh/priority routes and WaitingListService. Preserve FCFS and recurring series contracts.

### UC-ADM-10 — Review Resource Feedback and Maintenance Issues
**Status:** IMPLEMENTED FOR AUTHORIZED STAFF
**Primary actor:** Authorized responsible staff/administrator
**Other actors:** Eligible student reporter; resource owner
**Goal:** Review private resource issues, respond and track resolution without disclosing confidential report content.
**Preconditions:** A feedback report exists for an eligible room or equipment use.
**Main success scenario:**
1. Open authorized managed feedback with filters by resource, status and category.
2. Inspect the report and current revision/priority without exposing unrelated private reports.
3. Record review, response, status/priority update or reporter clarification through existing transitions.
4. Verify saved history, notification effects and any permitted reopening.
**Alternative outcomes and constraints:**
- Unauthorized staff or a third-party user must not see report details.
- Stale report revisions or duplicate mutations are rejected.
- Maintenance notes do not automatically cancel a published reservation or take an asset out of service without existing authorized policy.
**Result:** Private auditable issue workflow records the real staff decision.
**Implementation boundary:** Existing /feedback/, /feedback/<id>/update and FeedbackService. Do not invent new repair-ticket/automatic room-blocking contracts.

### UC-ADM-11 — Inspect Operational History and Produce Read-Only Reports
**Status:** PARTIAL: AUDIT DATA EXISTS; UNIFIED ADMIN REPORTING PROPOSED
**Primary actor:** Authorized technical administrator
**Other actors:** Service managers; project supervisor as demo observer
**Goal:** Inspect relevant allocation and service histories and generate reproducible aggregate reports without broad personal-data exposure.
**Preconditions:** Source services contain actual persisted history and current visibility rules.
**Main success scenario:**
1. Select a date/period and bounded domain (academic allocation, room, equipment, feedback, waiting).
2. Load existing authoritative status/historical records under an explicit administrator permission.
3. Show counts with clearly defined states and denominators; link back to source items for authorized detail.
4. Download a minimal safe export only if explicit field-level export access is approved.
**Alternative outcomes and constraints:**
- No cross-service counts are inferred from unrelated statuses.
- Missing data is shown as unknown/empty, not zero success.
- Bulk CSV/PII export, deletion of audit records and real-time system monitoring are not granted by default.
**Result:** Trustworthy administrative overview; read-only reporting until export policy is approved.
**Implementation boundary:** Existing /raw-data, /requests, /allocation-summary and service histories. NEW scoped aggregate reporting is optional; define privacy/export contract before implementing.

### UC-ADM-12 — Receive Administrative Work Updates and Inbox
**Status:** PARTIAL: EXISTING SERVICE NOTIFICATIONS; ACADEMIC REQUEST ALERTS DEFERRED
**Primary actor:** Authorized administrator or designated staff recipient
**Other actors:** Students; Instructors; notification service
**Goal:** Track real service notices and pending decisions without duplicating workflow state or leaking recipient data.
**Preconditions:** The signed-in actor has addressed notifications or authorized queue access.
**Main success scenario:**
1. Open recipient-scoped inbox and view unread updates from supported workflows.
2. Follow notices to an authorized request detail page and perform the original service action there.
3. Mark items read without changing approval or booking status.
4. Use service queues for tasks not currently backed by notifications.
**Alternative outcomes and constraints:**
- Unread count is not equal to pending decisions.
- Academic request eligibility notifications are currently deferred; show eligibility work queue separately.
- Do not deliver personal notifications to every administrator by default.
**Result:** Recipient-scoped notice tracking remains separate from approvals and allocations.
**Implementation boundary:** Reuse /notifications, NotificationService and existing service links. New academic notification events require separately approved recipients/idempotency/privacy design.

