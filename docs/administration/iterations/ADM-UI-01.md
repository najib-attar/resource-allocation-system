# ADM-UI-01 — Administration Home

Backend prerequisite: accepted at `54111d3`. Commit: introducing commit
`feat(admin): introduce Campus Space administration home`; exact SHA in final inventory.

Added a dedicated `/administration/` Home and current-capability login destination.
The original `/` allocation dashboard remains available. Home presents real scoped
queues, filters, allocation/inventory/Inbox summaries, source service links and
configuration access. No new mutation or permission. Campus Space base/service
components, tokens and responsive shell are reused; operational staff retain their
existing workspace. Technical actions remain accessible in Allocation & records.

Files: admin_routes, administration Home/error templates and scoped stylesheet;
shared base/service/navigation and Student Home heading; security home destination;
app registration/read-model pin exclusion; new Flask page tests and real browser
harness; existing shell/default-destination test expectations deliberately updated.
The old admin navigation block was removed only after moving its reachable links
to the new admin branch/Home; it was unreachable in the remaining non-admin branch.

Tests: **35 passed, 0 failures/errors/skips**, 97.53s (`test_administration_ui`,
`test_student_portal_ui`, `test_professor_portal`). Initial run had four assertion
failures: one heading regression, one collapsed-menu regression and two outdated
legacy-admin-style expectations. Corrected without weakening service authorization.

Live Flask/Edge/PostgreSQL final populated and fully empty browser runs each
verified **15 views** at **1440/1024/768/390/320px**, native form labels, keyboard,
focus, menus and zero horizontal overflow. Populated run: **265 keyboard steps**.
All five roles signed in through actual POSTs; non-admin roles received 403 for
Home. Each run performed five real logins; Home has no domain mutation. No
unexpected console/HTTP errors. Link destinations were requested and checked.
Visual review corrected the secondary-menu contrast and compacted empty queues.
Screenshots/raw control evidence: ignored `build/administration/browser/ADM-UI-01-final`
and `ADM-UI-01-empty`; representative final captures will accompany acceptance.

Each owned server stopped and schema was verified absent. No operational DB,
account, C++ or research change. Limitations remain those of backend acceptance.
Conclusion: verified; proceed to academic administration.
