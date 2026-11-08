# ADM-UI-03 — Rooms, equipment and directories

Base: `77c265d`. Commit: introducing commit
`feat(admin): unify scoped resource operations and directory search`;
exact SHA in final inventory.

Room policy/approver/closure configuration, faculty equipment inventory and
custodian assignments reuse the Campus Space service layout. Existing room and
equipment list/detail/action components remain authoritative. Added literal,
case-insensitive read-only search to existing user/space projections; user role
filter combines with search. No account/resource CRUD beyond existing custodian
inventory actions. Non-student equipment empty-state guidance is now relevant to
assigned staff. Clarified whitelist emptiness and approver replacement behavior.

Files: app directory presentation; users/table and room/equipment configuration
templates; equipment empty state; browser fixtures/persistence checks and directory
regression. Existing scope checks, schema and C++ protocols unchanged.

Fresh automated results: **39/39 passed**, 205.90s (room workflows, equipment web,
administration pages, PostgreSQL views); additional literal/escaped directory
search and authorization test **1/1 passed**, 6.06s. Zero failures/errors/skips.

Live browser: **50 views, 448 keyboard steps**, 1440/1024/768/390/320px;
**8 real POSTs / 6 verified domain outcomes** (two logins). Independent committed
reads proved room confirmation/reservation, equipment approval without collection,
actual two-unit handover, verified one-unit partial return and unique asset
registration. Duplicate registration rejected with unchanged state. Other-faculty
inventory and foreign staff loan access denied. Empty directory search, combined
role/search, source links, labels, keyboard/focus and overflow were checked.
No unexpected console/HTTP errors. Inventory screenshot visually reviewed.

Evidence: ignored `build/administration/browser/ADM-UI-03`; owned server stopped,
schema verified absent. Seeding uses synthetic clocks only to create a collection
window covering real test time; browser/server handover and return use the real
clock and actual backend. No operational data changed.
Conclusion: verified; continue to calendar, waiting lists and feedback.
