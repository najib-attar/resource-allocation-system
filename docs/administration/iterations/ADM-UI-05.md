# ADM-UI-05 — Read-only reports and Inbox

Base: `d4b5a3e`. Commit: introducing commit
`feat(admin): add bounded reports and recipient-scoped inbox guidance`;
exact SHA in final inventory.

Added private GET `/administration/reports`, using the verified backend service.
Domain and inclusive dates select at most 366 days; current stored statuses,
source-date basis, faculty scope and denominator are explicit. No utilization,
historic-status reconstruction, broad PII export or new scheduling action.
Recurring parents are counted once; occurrence details remain in source services.
Report navigation joins Home/Academic/Calendar/Inbox in the responsive shell.

The existing Inbox/read endpoint is reused. Academic notifications are explicitly
deferred and linked to the actual eligibility work queue. No new notification
event, recipient grant or duplicate implementation.

Files: reports template/admin route, navigation, scoped mobile five-column layout,
Inbox guidance; report authorization/date/scoping tests and live browser coverage.

Fresh tests: **40/40 passed**, 200.38s, zero failures/errors/skips (read models,
administration pages, notifications and identity). Browser: **40 views, 280 keyboard
steps**, all five widths; **9 POSTs / 4 verified domain outcomes** (five logins).
Actual link-triggered single-read and native bulk-read committed only the addressed
recipient's records; repeat read was idempotent; foreign notification ID rejected
with unchanged domain state. All five roles exercised report access. Populated,
empty and invalid reports, source links, labels/focus and overflow passed.
No unexpected console/HTTP errors. Report screenshot visually reviewed.

Evidence: ignored `build/administration/browser/ADM-UI-05`; owned schema verified
absent and server stopped. No schema, C++, business rules, account credentials or
operational data changed. Conclusion: verified; proceed to final integration audit.
