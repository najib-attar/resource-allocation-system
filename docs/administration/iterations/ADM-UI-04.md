# ADM-UI-04 — Calendar, waiting lists and feedback

Base: `b7658a0`. Commit: introducing commit
`feat(admin): integrate calendar policy and private service workflows`;
exact SHA in final inventory.

Explicit calendar setup/publication and waiting/recurring policy configuration now
reuse the Campus Space service layout. Existing calendar views, waiting queue and
private feedback components are reused directly; no duplicate implementation or
new notification/approval policy. Server fields and constraints are preserved.

Files: appointment_bindings, calendar_publications, waiting_configuration;
browser fixtures and independent committed-state checks. No schema, scheduling,
permission, C++ or research changes.

Fresh automated results: **96/96 passed**, 452.17s, zero failures/errors/skips:
university calendar, recurring policy, resource feedback and student presentation.
Live Flask/Edge/PostgreSQL: **60 views, 1,173 keyboard steps**, all five widths;
**16 actual POSTs / 11 verified domain outcomes** (five logins). No unexpected
console/HTTP errors or horizontal overflow. All visible destinations were checked.

Committed reads proved explicit academic period binding and calendar visibility
without changing allocation segments; the owning professor then saw the dated
activity. Explicit notice/semester configuration persisted. Waiting preapproval
reserved no asset; borrower cancellation released stock and automatically assigned
the eligible queue through the real engine; repeat refresh created no duplicate.
Private staff response and reporter clarification incremented revisions/history,
without inventory mutation. Missing CSRF/stale update and other-faculty staff access
were rejected. Calendar month/week/day and before/after states were checked.

Evidence: ignored `build/administration/browser/ADM-UI-04`. Fixture-only seeding
creates current physical use and occupied future stock; live server mutations use
real time, actual services and real PostgreSQL. Owned server stopped and schema
verified absent. Original demonstrations were not accessed.
Limitations: verified dates remain operator-supplied; no inferred enrollment or
new academic notification delivery. Conclusion: verified; proceed to reports/Inbox.
