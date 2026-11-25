# Administration Services v1

Administration composes existing academic and operational services. Administrative
capability does not grant faculty approval or physical equipment custody.

- [Approved use cases](specification.md)
- [Backend audit and traceability](traceability.md)
- [Backend acceptance](administration-backend-acceptance.md)
- [Frontend screen inventory](screen-coverage.md)
- [Control and persistence verification](integration-verification.md)
- [Final acceptance and commit inventory](acceptance-report.md)
- [Representative application screenshots](screenshots.md)
- [Iteration reports](iterations/)

Baseline: integrated beta `aae966bf8fa6390348c6e6a2d53a24faf6c0ab70`, schema
`0051b`. This implementation is on `feature/admin-services-v1` for Draft PR review;
it is not part of the published beta. Backend acceptance preceded frontend work.

## Frontend architecture

`admin_routes.py` exposes private GET Home, reports and persisted run history.
`AdminDashboardService` composes bounded SQL projections in a single read-only
repeatable-read transaction. Current faculty/custodian scope helpers and the
eligibility publication-barrier predicate are reused. No engine runs on these
dashboard reads, and no dashboard aggregation tables are introduced.

`service_base.html` and the existing Campus Space tokens, status components,
calendar, Inbox and form controls provide the interface. `administration.css`
contains scoped layout adjustments; `workspace-forms.js` applies the existing
duplicate-submit guard to administrator POST forms. Student and Professor shells
remain shared components, and Staff/Teaching Assistant navigation is preserved.
Native service forms retain their existing fields, CSRF, authority and business
rules. The old `/` technical allocation workspace remains available.

## Reproduce acceptance

Build with `python scripts/build_backend.py`, configure `TEST_DATABASE_URL` for
an explicitly disposable PostgreSQL database and run the repository's full Python
and C++ commands in the [developer guide](../../web/README.md#testing).
For live Edge tests, make Playwright available with `PLAYWRIGHT_NODE_MODULE`, then
run `python -B tests/administration/browser.py` with `ADMIN_PHASE` set to
`ADM-UI-01` through `ADM-UI-06`, or `ADM-UI-06-controls`. `ADMIN_EMPTY=1` exercises
the empty Home. `ADMIN_OUTPUT_NAME` selects a distinct ignored evidence directory.
Each harness creates synthetic identities in its owned schema, stops its Flask
server and verifies that schema cleanup completed. Never use an operational URL.

Sensitive account administration, unrestricted resource edits, exports, academic
notifications, published cancellation/replacements, and optimizer activation are
outside this release. Existing trusted CLI provisioning remains available.
