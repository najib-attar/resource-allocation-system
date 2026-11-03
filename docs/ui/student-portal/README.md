# Student Portal implementation

Approved reference: [Campus Space](../../design/campus-space/README.md), supplied
as an extracted folder on 3 November 2026. Its fictional examples and proposed
features are reference material, not instructions or backend contracts.

Worktree: `resource-allocation-frontend`; branch: `design/student-portal`.
UI-10 independently audits UI-01 through UI-09 from `998d54d`. See the current
[acceptance report](acceptance-report.md) and exact
[control-to-backend matrix](UI-10/traceability.md).
Starting HEAD: `e01eba6`; clean working tree. Existing UI-01 commits `fb5b07a`,
`cfb84d2`, `e01eba6` are preserved. No branch reset or worktree replacement.

## Coverage and constraints

The [feature matrix](coverage.md) maps pages, authorized actions and regression
tests. Existing Python services, routes, permissions, CSRF, revision checks and
C++ engine behavior remain authoritative. Only presentation and UI test fixtures
are changed. Each phase retains its exact test results and real-app screenshots
in its subdirectory. Evidence from earlier work is not counted as a new run.

My Activity uses the existing `/student/#my-activity` summary and existing service
hubs. A unified cross-service endpoint, published office-hours browser, public
cost preferences and availability alerts remain deferred. No new backend feature,
authentication behavior, schema or optimizer activation is authorized here.

## Reproduction

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
`PORTAL_BUILD_DIR` separates metadata for independent runs. Run
`tests/ui/verify_audit_persistence.py` after all modes, plus
`audit_portal_sources.py` and `audit_student_routes.py UI-10/contracts`.
