# ADM-B3 — Bounded administration read models

Commit: introducing commit `feat(admin): add scoped read-only dashboard and reports`;
exact SHA is recorded in the final acceptance inventory.

Added AdminDashboardService: one repeatable-read, read-only PostgreSQL transaction
per response; current administrator validation; bounded action queues, active and
recent allocation summaries, scoped inventory totals and recipient unread count.
Room actions require both current faculty assignment and recorded request approver;
equipment/issue/waiting data retain their existing scopes. Queued parents are not
counted again as ordinary decisions. Self-owned academic requests are excluded
from the reviewable queue; the authoritative eligibility page still lists them.

Reports accept at most 366 inclusive dates and explicitly define current status
and source date. They do not calculate occupancy, historic status-at-date or PII
exports. Allocation history returns 50 decisions and 100 persisted segments per
page; engine snapshot/build JSON is not fetched for summary reads. No C++ execution,
new scheduling rule, cache table, migration, permission or notification event.
Frontend routes are intentionally connected only after backend acceptance.

Files: `web/admin_dashboard_service.py`, `tests/test_administration.py`, screen
inventory and corrected traceability names, this report.

Fresh verification: complete new module **11/11 passed**, 136.12s; subsequent
history pagination **2/2 passed**, 25.36s; final date/ID boundaries **2/2 passed**,
19.97s. **15 executions, 0 failures/errors/skips** in these final passes.
Initial synthetic fixture errors (duplicate seeded role; reporting before the
fixture activity began) were corrected; production validation was preserved.
Raw logs are ignored under `build/professor-tests/administration/ADM-B3-*`.

Tests prove concurrent committed submission cannot split count/row snapshots,
large queue SQL limits, all-role capability denial, assignment replacement,
private appointment exclusion, feedback/inbox scoping, date denominators and
real-engine persisted history. A static review also confirmed all three service
transactions are read-only and there is no engine import. Only isolated schemas
changed. No screenshots for this backend-only stage.
Conclusion: **verified**; sensitive extensions remain deferred.
