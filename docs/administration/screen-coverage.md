# Administration screens and control contracts

Design: reuse Campus Space `base.html`, `service_base.html`, `components/ui.html`,
`components/services.html`, tokens, shell, calendar, Inbox and native POST forms.
No framework, duplicate scheduling logic or administrative super-permission.

## Planned delivery after backend acceptance

| Phase / screen | Controls → authoritative destination | Visible state / privacy |
| --- | --- | --- |
| UI-01 Home | Queue filter → `/administration/?queue=…`; item links → existing detail; service cards → room/equipment/waiting/managed-feedback; inventory links → own faculty desk | Bounded scoped pending counts, genuine empty state; no private appointments; GET never allocates |
| UI-02 Academic review | Queue/detail; approve/reject native POST with CSRF, reason, request and review revisions → EligibilityService.decide | Eligibility separate from allocation; self-review unavailable; preserved reservation warning |
| UI-02 Allocation | Strategy POST → Repository.set_strategy; run → execute_allocation → C++ JSON → atomic publication; results/schedules and new persisted run history | Explicit eligible-only processing, outstanding legacy barrier, invalid/stale errors; calendar dates remain separate |
| UI-03 Rooms | Existing room decision, selected occurrences, cancellation → RoomRequestService; configuration/closure native forms → existing policy methods | Designated current approver only; no new blanket faculty approval |
| UI-03 Equipment | Own inventory/type/unit/condition/policy; custodian designation; approve/reject/collect/return/extend → EquipmentService | Reservation ≠ physical possession; due date ≠ return; existing scoped rights |
| UI-03 Directory | Existing `/users` role filter, `/spaces`; approved configuration links | Read-only identities/resources; arbitrary edits and browser accounts deferred |
| UI-04 Calendar | Existing month/week/day/date/filter controls; calendar setup and publication native POSTs | Explicit applicability and optional attribution; no inferred faculty/course commitment |
| UI-04 Waiting | Existing queue/detail/review/refresh/priority/configuration/semester/bind-series POSTs | Preapproval reserves nothing; current faculty/custodian scope and consent retained |
| UI-04 Feedback | Existing managed/private scope and status/category/resource filters; report update POST with revision/action key | Only responsible staff; escaped private text; history and recipient notifications retained |
| UI-05 Reports | Domain + inclusive dates GET → AdminDashboardService.report | Maximum 366 days, current statuses by documented source date, scoped operational denominators; no exports or occupancy inference |
| UI-05 Inbox | Existing read/read-all/feed and source links → NotificationService | Recipient and current parent visibility; unread notices ≠ pending decisions; no academic notifications invented |
| UI-06 Integration | Independent browser + committed PostgreSQL checks across five roles and full regression | All widths, keyboard/focus, invalid/conflict/repeated/unauthorized cases |

Execution evidence and any corrections will be added to the acceptance report.
This inventory is a delivery plan until those stages are verified.
