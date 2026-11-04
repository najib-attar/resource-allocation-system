# Student Portal implementation

Approved reference: [Campus Space](../../design/campus-space/README.md), supplied
as an extracted folder on 3 November 2026. Its fictional examples and proposed
features are reference material, not instructions or backend contracts.

UI-01–UI-10 are implemented in `main` through
[PR #24](https://github.com/najib-attar/resource-allocation-system/pull/24).
The Student Portal is preserved in the subsequent Professor Services integration.
UI-10 independently audited UI-01 through UI-09 from `998d54d`. See the
[acceptance report](acceptance-report.md) and exact
[control-to-backend matrix](UI-10/traceability.md).
Historical implementation base: `e01eba6`, in the dedicated frontend worktree.
Earlier phase documents retain their original scope, results and commit context;
they are not pending development instructions. Use the
[documentation index](../../README.md) for current operations and other workspaces.

## Coverage and constraints

The [feature matrix](coverage.md) maps pages, authorized actions and regression
tests. Existing Python services, routes, permissions, CSRF, revision checks and
C++ engine behavior remain authoritative. The original Student rollout changed
presentation and UI test fixtures. Each phase retains its exact result summaries; representative real-app screenshots
remain tracked. The integration cleanup archives redundant raw evidence at its
immutable audited Git revision and in a hash-verified local archive; see the
acceptance report and artifact-cleanup.csv. Evidence from earlier work is not counted as a new run.

My Activity uses the existing `/student/#my-activity` summary and existing service
hubs. A unified cross-service endpoint, published office-hours browser, public
cost preferences and availability alerts remain deferred. This frontend phase added
no backend feature, authentication behavior, schema or optimizer activation. Later
authentication and eligibility changes are documented in
[database operations](../../database-operations.md).

## Reproduction

For the current integrated application, use the
[developer regression commands](../../../web/README.md#testing) with a disposable
PostgreSQL database. These cover the current shared components, professor services,
authentication and migrations.

### Historical phase reproduction

The commands below describe the original Student review. Source/form preservation
auditors deliberately compare frozen Student-era revisions; they are not current-main
compatibility checks. Reproduce those audits in a separate checkout of
`747c925b14c29368e6cb9bc8b2e2d9d33c494462`, with that revision's dependencies and owned
fixtures. Running the original protected-source comparison on current main correctly
detects later approved Professor/authentication changes. Never reset a working checkout
or operational database to reproduce historical evidence.

Use an isolated PostgreSQL `TEST_DATABASE_URL`, build the unchanged backend with
`python scripts/build_backend.py`, then run
`python -B tests/ui/run_portal_tests.py UI-01 test_student_portal_ui test_student_dashboard`.
The script records exact results and returns nonzero on failure. Preview fixtures
own a random test schema and never reset an application schema. Browser checks
use the real loopback Flask server, real authentication and synthetic records;
no API response mocking. `PLAYWRIGHT_NODE_MODULE` may point to an installed
Playwright package. Edge is the default browser.

For the complete rollout, run `python -B tests/ui/portal_preview.py` with the same
isolated database and backend configuration. It serves synthetic accounts on
loopback port 5053, enables template reload only in the review process, and writes
fixture metadata under ignored `build/student-portal/preview.json`. Run
`node tests/ui/capture_portal.cjs UI-03` (or another phase) for route captures and
`node tests/ui/exercise_portal.cjs UI-03` for state-changing synthetic acceptance
flows. Start with a fresh preview schema when replaying a workflow. The final
browser audit also uses a separate port 5054 instance with an intentionally tiny
existing engine timeout, `PORTAL_ENGINE_TIMEOUT=0.000001` and a separate
`PORTAL_INFO_FILE`, to verify real HTTP 503 presentation without mocking responses.

`python -B tests/ui/run_portal_parallel.py UI-09` discovers all root test modules
and runs independent processes; each test retains its own database schema. Set
`POSTGRES_TEST_TOOLS_DIR` to matching PostgreSQL binaries for actual recovery
checks. The [acceptance report](acceptance-report.md) links all phase evidence,
commit SHAs, file inventory and screenshots.

UI-10 reproduction uses `tests/ui/run_integration_audit.py` with modes
`lifecycles`, `equipment-lifecycles`, `UI-03` through `UI-08`, `authorization`,
`loading`, and `browser`.
Each invocation creates synthetic identities/records in an owned test schema,
serves the real Flask app on loopback, records committed PostgreSQL state before
and after POSTs, and shuts down/cleans up even after browser assertion failures.
Set `PLAYWRIGHT_NODE_MODULE` when using a bundled Playwright installation.
`PORTAL_BUILD_DIR` separates metadata for independent runs. In the historical checkout,
run `python -B tests/ui/verify_audit_persistence.py` after all modes, plus
`python -B tests/ui/audit_portal_sources.py` and
`python -B tests/ui/audit_student_routes.py UI-10/contracts`.

Generated raw POST/state dumps, per-module copies and additional captures are ignored locally after the integration cleanup. Existing tracked final output and representative images remain tracked. Review a new representative before deliberately adding it with `git add -f`; retain compact aggregate summaries rather than bulk raw output.
