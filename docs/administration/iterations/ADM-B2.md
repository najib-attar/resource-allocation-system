# ADM-B2 — Operational administration verification

Base: ADM-B1 `daecc18`. Commit: introducing commit
`test(admin): verify scoped operational administration`; exact SHA is in the
final acceptance commit inventory.

Reused RoomRequestService, EquipmentService, WaitingListService, FeedbackService,
NotificationService and the recurring reservation infrastructure. No operational
business rule, authorization, engine contract or schema changed.

Command: `python -B tests/professor/run_tests.py --child administration/ADM-B2
test_room_requests test_equipment test_equipment_web test_waiting_lists
test_resource_feedback test_recurring_policy test_recurring_workflows
test_notifications` with isolated TEST_DATABASE_URL and rebuilt real engine.

Fresh result: **187 executed, 187 passed, 0 failures, 0 errors, 0 skips**;
1950.22 seconds. Raw evidence remains ignored under
`build/professor-tests/administration/ADM-B2/`.

Covered all five roles and designated faculty/custodian checks; foreign faculty
and cross-user denial; CSRF, stale revisions, retries, concurrent processes,
rollback, real reservations, recurring partial decisions, physical handover,
verified partial returns, overdue custody, queue preapproval/assignment/withdrawal,
private issue response/clarification and recipient-scoped read state. Tests verify
committed PostgreSQL records in owned random schemas. No demo records accessed.

Files changed: this report. Screenshots: backend-only stage, not applicable.
Limitation preserved: changing a faculty approver does not rewrite a pending
room request's recorded approver. An organizer may need to revise/resubmit so a
current approver can decide it; this does not authorize a staff override.
Conclusion: **verified**, continue to administration read models.
