# Resource Allocation Dashboard

The Flask/Jinja dashboard uses **PostgreSQL** for application persistence and the
existing C++17 engine for allocation. It does not implement allocation algorithms,
participant rules, exam sharing or meeting suggestions in Python.

```text
Flask forms -> PostgreSQL request/participant transaction
PostgreSQL ordered snapshot -> EngineGateway -> C++ --json
C++ structured result -> validated PostgreSQL publication
DatabaseResultAdapter -> dashboard/detail/schedule/technical views
```

## Setup and startup

Read [database operations](../docs/database-operations.md) for database creation,
credentials, safe import and tests. From the project root, with PostgreSQL running
and a new empty application database configured:

```powershell
python -m pip install -r requirements.txt
python scripts/build_backend.py
$env:DATABASE_URL = 'postgresql+psycopg://USER:PASSWORD@localhost:5432/resource_allocation'
python -m alembic upgrade head
python scripts/import_csv.py --data-dir data --dry-run
python scripts/import_csv.py --data-dir data
python web/app.py
```

The import refuses populated targets and does not modify source CSVs. `DATABASE_URL`
must be set before migration/startup; `.env.example` is not automatically loaded.
On Linux, export the same variable and use the same Python commands. Startup from
`web/` with `python app.py` remains supported after environment configuration.
Open `http://127.0.0.1:5000`. This is a development server, not a public deployment.

## Compile The C++ Backend

The authoritative backend artifact is `build/backend/allocation_system.exe` on
Windows and `build/backend/allocation_system` on Linux. `scripts/build_backend.py`
requires g++ on PATH and writes an adjacent `.build.json` manifest containing
source/binary hashes, compiler identity and build time. Missing, stale or mismatched
builds fail explicitly; old root/check executables are never fallbacks.

For an intentional alternate location:

```powershell
python scripts/build_backend.py --output 'build/custom/engine.exe'
$env:RESOURCE_ALLOCATION_BACKEND = 'build/custom/engine.exe'
```

Relative paths resolve from the project root; absolute paths and spaces are
supported. On Linux the artifact must be executable. Build before starting workers;
this is not automatic C++ hot reload or signed-artifact verification. The
[JSON protocol v1](../docs/engine-protocol.md) and freshness checks are unchanged.

## Request and allocation workflow

1. Add a OneTime, Recurring, Exam or CommitteeMeeting request.
2. Save Request Only commits the request, occurrences, exam metadata where relevant,
   selected committee participants and history without running allocation.
3. Submit and Run saves first, then invokes the C++ JSON engine. Failures/timeouts
   leave the saved request pending and keep previous successful results visible.
4. Review Requests, request details, Allocation Summary and Schedules.
5. Raw Data is a technical **database projection**, not a file browser. Old CSV-style
   tab names/URLs are retained for compatibility; no operational files are read.

Committee forms show instructor, teaching assistant, staff and administrator
participants. At least one is required, with a role such as Supervisor or
CommitteeMember. Professors' appointment approval is a future feature, not part of
committee request processing. C++ checks loaded busy slots and already approved
committee commitments and returns ranked feasible suggestions as structured data.

Normal time selectors remain Monday-Friday, 09:00-17:00 in 30-minute steps.
Recurring entry accepts the existing weekday/hour or minute syntax, for example
`2-09:00-10:30;4-13:15-14:00`, and is validated before persistence. Schedule views
remain weekly, not dated calendars.

## Strategy selection

Save Strategy updates PostgreSQL application configuration, not `data/config.txt`.
Each engine snapshot includes its own strategy. Supported choices remain:

- `greedy`: loaded request order.
- `priority`: request priority order.
- `multi_room_exam_greedy`: greedy splitting across available classrooms.
- `multi_room_exam_best_fit`: best-fit classroom combination.
- `shared_room_exam_best_fit`: compatible exams share remaining classroom capacity.

All decisions still belong to C++ strategies/rules. The no-argument standalone CSV
CLI retains its legacy `config.txt` behavior and four output writers.

## Transactions and consistent readers

PostgreSQL identities generate request IDs. Short state-row locks coordinate saves,
strategy updates, run snapshot capture and publication. C++ runs **outside** that
transaction, so inputs may be saved while it computes. A changed input revision
causes an explicit retry error rather than publishing stale decisions. Older runs
cannot replace newer completed runs.

Validated decisions, allocations, mandatory participants, suggestions, history and
the active-run reference commit together. Each Flask response reads one repeatable-
read database view. `DatabaseResultAdapter` reuses presentation formatting from
`BackendResultAdapter` but never reads local result JSON/CSV as a fallback.

Set `RESOURCE_ALLOCATION_DB_LOCK_TIMEOUT` (default 5 seconds) and
`RESOURCE_ALLOCATION_ENGINE_TIMEOUT` (default 30 seconds) as needed. Busy writes
return HTTP 503 with Retry-After. Database errors are explicit and do not expose
SQL credentials. Worker crashes cannot make partial results active; an abandoned
run record can remain non-authoritative until administrative cleanup.

## Pages

- `/`: strategy, run action, counts, recent requests and demo shortcuts.
- `/users` and `/spaces`: database profiles/resources; existing role filters retained.
- `/requests` and `/request/<requestId>`: queue, decisions, assignments and suggestions.
- `/add-request`: transactionally save any supported request type.
- `/request-added/<requestId>`: Save Only confirmation and explicit run action.
- `/allocation-summary`: grouped approvals/rejections/pending requests and exam rooms.
- `/schedules`: saved busy slots and allocation-derived user/resource events.
- `/raw-data`: technical projections, including request/allocation summary tabs.
- `/add-one-time`, `/add-exam`, `/exam-summary`, `/allocations`, `/results`: existing redirects.

Missing request IDs and invalid raw-data selectors retain safe responses. Before
the first DB allocation run, requests are pending and views ask the user to run it.
An unavailable database never falls back to legacy CSV results.

## Verification and limitations

Install dependencies, build the backend and configure a disposable
`TEST_DATABASE_URL`, then run:

```powershell
python -m unittest discover -s tests -p 'test_*.py' -v
powershell -ExecutionPolicy Bypass -File tests/run_tests.ps1
```

Historical file-coordination/publication helpers live only in
`tests/legacy_*`, not application runtime. Explicit offline CSV display/import/CLI
support remains. Exact keyed form retries reuse saved requests; unkeyed legacy
callers retain their original new-request semantics. Authentication, engine-job
deduplication, dated
appointments and production hardening are not delivered by this migration.
