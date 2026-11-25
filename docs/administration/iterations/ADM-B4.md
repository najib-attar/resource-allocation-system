# ADM-B4 — Sensitive extensions deferred

Base: `0db8d03`. Commit: introducing commit
`docs(admin): preserve sensitive extension boundaries`; exact SHA is in the final inventory.

No sensitive extension implemented. The existing trusted account provisioning and
explicit reset CLI remain unchanged. Browser password reset, account disabling,
privilege delegation, arbitrary identity/resource CRUD, broad PII exports,
academic notifications, published cancellation/versioned replacement, SIS import
and institutional optimizer activation require separate policy/security contracts.
No placeholder controls will present them as functional.

Tests in this stage: **not run (0 passed, 0 failed, 0 skipped)**, because no
application code changed. Existing boundary verification is recorded in B1/B2.
Database effects: none. Schema, accounts, C++ and research: unchanged.
Files: this report. Screenshots: not applicable.
Conclusion: intentionally deferred; continue to backend acceptance.
