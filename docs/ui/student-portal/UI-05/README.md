# UI-05 Equipment

The equipment hub, borrowing catalog/form, loan detail, recurring loan states and
error pages use the shared student service components, with sage service accents.
All existing quantities, exact specifications, faculty selection, dates, notes,
recommendations and explicit alternatives remain available. Entered values survive
server recommendation responses. Editing a result labels it stale and clears its
preview token; the existing signed-preview check still enforces complete recurring
review on the server.

Details show actual collected-unit and verified-return counts, the original asset
records, overdue warning, extension decisions and history. A keyboard-focusable
scroll region preserves all collection/return columns on narrow screens. Custodian
approvals, physical handover and inspection remain behind their original service
and template guards. Borrower return intent never releases equipment.

The phase includes catalog/list/detail/recurring/error/forbidden captures at all
four widths, CSRF/keyboard/overflow checks, and real borrowing recommendation,
submission, cancellation, partial-return, extension and signed recurring-preview
browser flows. Automated results cover equipment, web, recurring workflows/views
and partial-approval policy suites in separate processes against owned schemas;
the combined report verifies discovery and execution counts. See `tests.json`,
`tests.txt`, `browser-results.json` and `workflow-results.json` for exact evidence.
