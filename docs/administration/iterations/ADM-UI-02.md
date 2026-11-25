# ADM-UI-02 — Academic administration

Base: `3796b88`. Commit: introducing commit
`feat(admin): connect academic review allocation and run history`; exact SHA in final inventory.

Academic review, request creation/list/detail, strategy/allocation, results,
schedules and technical data now reuse service_base and Campus Space controls.
Eligibility validation errors recover to administration; safe workspace failures
also cover administrators. Eligibility, active allocation and explicit dated
calendar visibility remain distinct. Added private paginated persisted run history
and recent-run links. Existing native forms retain fields, CSRF and server checks;
the shared POST submission guard now also protects administration forms.

Tests: **44/44 passed**, 197.74s (academic eligibility, professor portal,
save-only confirmation, PostgreSQL views and administration pages); subsequent
complete administration-page module **6/6 passed**, 32.00s. No failures/errors/skips
in these automated passes. Existing tests retained; two new history cases cover
real persisted results, denied ownership and invalid parameters.

Final live browser: **50 views, 369 keyboard steps**, five required widths,
**6 POSTs / 4 independently verified domain outcomes** (two logins). Actual
eligibility approval persisted without allocation; stale review rejected unchanged;
strategy revision committed; real C++ run activated only eligible inputs. Professor
tracking displayed the assignment and denied administrative history access.
History missing-ID and conflict/error states were exercised. No unexpected
console/HTTP errors or horizontal overflow in the final pass.

Confirmed browser defects fixed: expanded administrative tools covered the approval
button in mobile bottom navigation; populated allocation cards expanded a grid
beyond tablet width. Tools remain available from Home/Academic on mobile; desktop
disclosure is retained. Scoped minmax grid sizing keeps result tables within their
scrollable containers. Failure evidence remains local; final evidence is ignored
under `build/administration/browser/ADM-UI-02-final`.

Files: academic templates, run template/admin routes, Home history, app error
presentation, eligibility error recovery, shared submission guard inclusion,
scoped CSS and browser/page tests. No database schema, C++ rule/protocol,
authorization or scheduling behavior changed. Only disposable schemas mutated;
owned server stopped/schema verified absent. Academic notifications/cancellation
and versioned published replacement remain deferred.
Conclusion: verified; continue to room/equipment administration.
