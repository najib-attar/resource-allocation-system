# PostgreSQL setup and safe operations

Iteration 41 makes PostgreSQL the normal web application's source of truth.
The C++ engine still receives JSON protocol v1 and has no SQL dependency.
See [database design](architecture/database-design.md) for the ER diagram and
[engine protocol](engine-protocol.md) for the unchanged execution contract.

## Setup

Use Python 3.12 or 3.13, PostgreSQL 17, and g++ with C++17 support. From the
repository root, create/activate your Python virtual environment, then:

```powershell
python -m pip install -r requirements.txt
python scripts/build_backend.py
$env:DATABASE_URL = 'postgresql+psycopg://USER:PASSWORD@localhost:5432/resource_allocation'
python -m alembic upgrade head
python scripts/import_csv.py --data-dir data --dry-run
python scripts/import_csv.py --data-dir data
python web/app.py
```

Create a **new empty** `resource_allocation` database and an appropriate local
role beforehand, using your PostgreSQL administration tools. Substitute your own
credentials; URL-encode special password characters. The application does not
create databases, auto-run migrations, or silently fall back to files. For Linux,
use `export DATABASE_URL='...'`; the Python commands are unchanged.

`.env.example` documents settings but is not loaded automatically. Configure
environment variables in your shell/service. Keep actual `.env` files and secrets
out of Git. Use a non-superuser application account and restrict network access;
use authenticated TLS connections for a remote database. CI's trust-authenticated
database is disposable test infrastructure, not a production configuration.

Open `http://127.0.0.1:5000`. Use Run Allocation after import to publish the first
database result. Before that, requests are pending; existing generated result files
are **not** an operational fallback. The standalone C++ CSV CLI still works in an
isolated working directory and does not update the database.

## Import safeguards

- Back up original CSVs before cutover and keep that independent backup. The
  importer only reads files and never deletes or rewrites them.
- Dry-run validates files, IDs, types, numeric/time fields and references without
  writing to PostgreSQL. Missing optional auxiliary files produce explicit warnings.
- Actual import refuses any populated application target. There is no overwrite,
  truncate or destructive-reset switch. Do not use an existing database as a test target.
- All inserts commit together or roll back together. IDs, profile metadata,
  resource/request order, recurring slots, participants and busy slots are preserved.
- Unknown columns, duplicate identities and invalid references are reported rather
  than silently discarded. Correct the source or decide its meaning before retrying.
- Generated CSVs/local result JSON are not trustworthy migration inputs: they may
  be stale. Preserve them as offline artifacts and regenerate verified results.

Schema upgrades use reviewed Alembic revisions. Before future production upgrades,
take a PostgreSQL backup (`pg_dump`) and verify a restore into a separate database.
This iteration performs no destructive migration of an existing application DB.

## Workflow and failures

Save Only commits the request, participants and history, without invoking C++.
Submit and Run commits the request first and then starts allocation. Engine errors,
timeouts or publication failures leave that request saved/pending and keep the
previous successful run visible. A lost HTTP response does not undo a committed save.
Each rendered request form carries a random submission key. An exact retry with
the same key reuses the existing request ID without another save/history/revision;
different content with that key returns HTTP 409. Keys are retained with requests,
not expired automatically. Imported records and unkeyed legacy POST clients keep
their existing semantics: each unkeyed save is a new request. This is not an
authentication or CSRF token.

Submit and Run retries can run the engine again after reusing the saved request.
Runs have distinct correlation IDs; only one successful run is active. Engine
execution is not deduplicated or scheduled automatically, and a changed input
revision still requires a fresh run. There is no retry loop hidden in Flask.

Each run captures its strategy and ordered inputs in PostgreSQL. The engine runs
outside a transaction. Short `application_state` row locks coordinate input changes
and result publication. Publication verifies the captured input revision, rejects
stale runs and prevents older runs from replacing newer completed runs. All result
records and the active-run pointer commit atomically. Every response pins one
repeatable-read database view; suggestions are structured, not recovered from text.

`RESOURCE_ALLOCATION_DB_LOCK_TIMEOUT` defaults to 5 seconds. Lock contention returns
HTTP 503 with `Retry-After: 2` and no partial input writes. Engine timeout defaults
to 30 seconds (`RESOURCE_ALLOCATION_ENGINE_TIMEOUT`). Missing configuration/database
errors produce explicit failures, not CSV fallback; SQL parameters and connection
credentials are not echoed in web errors/logs. A worker crash releases DB locks.
A run interrupted outside a transaction may remain marked `running`; it never
becomes authoritative without successful publication. Administrative retention/
abandoned-run cleanup is not automated yet.

Keep all operational writes through the repository's transaction/revision protocol.
Uncoordinated manual SQL can bypass revision checks. The application rebuilds a
complete weekly allocation batch; it is not yet a dated appointment reservation
system. Shared-room exams retain their existing capacity-sharing policy, so a
blanket SQL room-overlap prohibition would be incorrect.

## Integrity upgrades and retention

Migrate to head before starting the current application. Revision `0041d` checks
old subtype data and installs deferred SQL constraints: every request has slots,
non-recurring requests have one slot, only exams have required exam details, and
only committee requests have participant mappings. Empty committees remain engine
inputs that may be rejected. Replacing slots/subtypes in one transaction is safe;
concurrent child edits serialize on the parent request. A malformed existing
subtype aborts the upgrade without deleting records. Back up and explicitly review
repairs; never silently remove a request to make a migration pass.

`0041e` adds nullable unique form retry keys and fingerprints; old/imported records
remain unchanged. Organizational forests are validated before initialization and
snapshot construction. A corrupt/manual cycle fails clearly before C++ execution.
The current application has no organizational editor; SQL bypassing the repository
is not a supported application write interface or revision protocol.

All runs, decisions and history are retained by default. This deliberately avoids
deleting audit evidence or an active publication without an approved retention
policy. An interrupted worker may leave a `running` record, but a new run is safe;
never classify it as failed solely because a timer expired. Use read-only inspection:

```sql
SELECT status, count(*), min(created_at), max(created_at)
FROM allocation_run GROUP BY status;
SELECT active_run_id, input_revision FROM application_state WHERE id = 1;
SELECT count(*), coalesce(sum(pg_column_size(snapshot)), 0) AS snapshot_bytes
FROM allocation_run;
```

Automatic pruning, abandoned-run reconciliation and engine-job deduplication are
administrative lifecycle work requiring a retention/retry policy, not missing
storage for current features. They are not enabled in this iteration. Monitor
growth, preserve backups, and obtain approval before any destructive cleanup.

## Fictional demonstration database

Create a **new empty development database**, configure `DATABASE_URL`, and migrate
to head. Then seed directly into PostgreSQL, not into the regression CSV fixtures:

```powershell
python scripts/seed_demo_database.py --seed 41 --dry-run
python scripts/seed_demo_database.py --seed 41 --run-allocation
python web/app.py
```

Default data: 106 users across all five roles, 20 classrooms/laboratories/meeting
rooms, six faculty/department units, 120 requests covering all four types, and
12 professor busy slots. Committee participants, room/participant conflicts,
features, capacities, recurring teaching and compatible multi-room exams are
included. Names/IDs are fictional; email addresses use `example.invalid`.
Only the real C++ engine generates decisions/allocations/suggestions.

`--size large` uses 1,060 users, 200 resources, 1,200 requests and 120 busy slots.
`--seed` makes input generation reproducible; allocation remains strategy-dependent.
An empty seed creates pending requests; `--run-allocation` explicitly invokes C++.
If the engine fails afterward, the seed remains saved and pending, with no partial
results published. Inspect Users, Spaces, Requests, Allocation Summary and Schedules.

The tool refuses **every populated target** and has no reset/force switch. To
start another demo, create another empty development database. No reset is
automated: any later reset of existing development data needs separate explicit
approval and a verified backup; production data must never be reset by this tool.

## Backup and recovery

Use PostgreSQL client tools matching the server major version. Store backups
outside the repository with restricted permissions; they may contain personal
information in a real installation. Keep passwords in environment/service secrets
or a protected PostgreSQL password file, not command arguments or committed URLs.

```powershell
# PGHOST/PGPORT/PGUSER and protected authentication settings identify the server.
pg_dump --format=custom --file=resource-allocation.dump --dbname=resource_allocation
createdb resource_allocation_restore_check
pg_restore --exit-on-error --no-owner --no-privileges --dbname=resource_allocation_restore_check resource-allocation.dump
```

The destination must be **new and empty**. Do not use `--clean`, overwrite a live
database or delete the original while verifying recovery. A real operational
restore also requires provisioned roles/privileges and reviewed configuration;
`--no-owner --no-privileges` above is for an isolated verification destination.
Point a separate application instance to the restored database, compare entity
counts, active-run decisions/allocations/suggestions and next generated request ID,
then verify dashboard/schedules. Restore the schema's Alembic version with the
dump and run normal upgrades only when reviewed. Backup creation alone is not
evidence that recovery works.

The automated recovery test uses `pg_dump`/`pg_restore`, creates a unique
`ras_restore_<uuid>` database and verifies exact published results, identity
continuation and a new Flask process. It retains that isolated database rather
than deleting any existing database. Local test schema cleanup never affects it.

## CSV dependency classification

| Category | Current treatment |
|---|---|
| Standalone C++ CSV CLI | `src/data/` readers/writers and no-argument CLI preserved. |
| Optional import/export | Validated `scripts/import_csv.py`, offline snapshot parsing and standalone CLI exports preserved. |
| Regression fixtures | Original `data/` and `tests/fixtures/` files preserved untouched. |
| Historical documentation | Previous iteration reports preserved; active guides describe PostgreSQL. |
| Obsolete operational persistence | `web/shared_file_state.py` and runtime file-generation publication removed. |
| Historical compatibility tests | Coordinator/result-publication fixtures live only in `tests/legacy_*`; unused legacy strategy writer removed. |

`result_table_schema.py` contains display/import column constants, not storage.
Legacy-named `read_csv_table` adapter methods return in-memory database projections
in normal Flask workflows. Renaming all template/view keys would add risk without
changing authority. The explicit offline CSV display adapter is still used by
CLI parity tests; it cannot become a fallback when PostgreSQL fails.

## Tests and CI

Create a separate disposable test database and set:

```powershell
$env:TEST_DATABASE_URL = 'postgresql+psycopg://USER:PASSWORD@localhost:5432/resource_allocation_test'
python -m unittest discover -s tests -p 'test_*.py' -v
powershell -ExecutionPolicy Bypass -File tests/run_tests.ps1
```

Database tests create unique owned `ras_test_<uuid>` schemas, migrate them, and
clean up only those schemas. They never reset the configured database's public
schema or use SQLite as a PostgreSQL substitute. The test role needs schema
creation rights **only in that disposable database**. Without `TEST_DATABASE_URL`,
database tests explicitly skip; that is not full migration verification.

Real recovery additionally needs `CREATEDB` on the **isolated test server** and
matching client tools. Set `POSTGRES_TEST_TOOLS_DIR` to their directory locally.
CI runs matching clients through its PostgreSQL service container using the
step-scoped `POSTGRES_TEST_TOOLS_CONTAINER`. Without tools, recovery explicitly
skips; that is incomplete recovery verification. Do not grant the production web
role these test/admin permissions.

The Linux GitHub Actions job provisions PostgreSQL 17.11, installs pinned direct
dependencies, builds the authoritative engine, and runs the C++ and Python suites.
Windows verification uses real PostgreSQL too. Linux-specific permission checks
cannot be claimed verified by a Windows local run. The implementation branch is
published only when authorized; inspect the draft PR's actual Actions results
before merge rather than treating local lint as remote verification.

## Scope boundaries

No authentication, appointment approvals/invitations, date/timezone migration or
public deployment is included. Do not expose the Flask debug server publicly.
Weekly schedules remain weekday/minute intervals. PostgreSQL stores all currently
implemented roles/resources/requests/allocations/availability/history/configuration;
future appointment workflows require a separately reviewed feature iteration.
