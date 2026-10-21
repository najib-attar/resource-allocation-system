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
$env:RESOURCE_ALLOCATION_SECRET_KEY = '<at least 32 random characters; keep private>'
$env:RESOURCE_ALLOCATION_TIMEZONE = 'Europe/Istanbul'
python scripts/manage_accounts.py --user-id EXISTING_ADMIN_USER_ID --username campus-admin --administrator
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

Open `http://127.0.0.1:5000` and sign in with the provisioned identity. Use Run Allocation after import to publish the first
database result. Before that, requests are pending; existing generated result files
are **not** an operational fallback. The standalone C++ CSV CLI still works in an
isolated working directory and does not update the database.

## Accounts and appointment calendars

Provision accounts only for existing university users. Passwords are entered via
`getpass`, never command-line arguments or stored demo defaults. The utility refuses
overwrite unless `--reset-password` is explicit; resets revoke old signed sessions.
Student and Instructor roles come from the university identity, not a client-selected
role. Use `--administrator` only for trusted management accounts. Legacy technical
dashboard/raw-data/weekly views require administration; appointment records and
dated calendars are participant-scoped. Signed sessions expire after eight hours;
all POSTs, including login/logout and legacy forms, require CSRF tokens.

Generate the secret using `python -c "import secrets; print(secrets.token_hex(32))"`
and configure it privately. Set `RESOURCE_ALLOCATION_SECURE_COOKIE=1` behind HTTPS.
The local development server binds loopback and debug is disabled unless explicitly
enabled with `RESOURCE_ALLOCATION_DEBUG=1`; it is not a production server.

Migrations 0042a/0042b add the dated foundation and aggregate integrity checks.
Migration permissions must permit installing the standard `btree_gist` extension;
the runtime application account should not have migration/DDL privileges. Restore
schema-only dumps into a new database with that extension installed in public
before restoring GiST constraints. Full-database backups should include extensions.

Professors publish weekday hours with explicit validity dates and exceptions.
Students/professors manage dated personal blocks in My Schedule. Europe/Istanbul
is explicitly configured; all stored instants are aware, intervals half-open, and
ambiguous/nonexistent local times rejected. Changing server/browser timezone does
not assign dates to legacy records.

Administration Calendar Setup associates exactly one legacy busy record or resource
request with a named academic period, optionally a specific Monday planning week
and excluded dates. Blank week means recurrence only within the entered validity.
Use actual known dates; never guess an old record's semester from today's date.
Unknown mandatory calendar applicability yields an actionable configuration error.
Optional invitees with unresolved calendars are not counted known-free.

Pending appointments reserve nothing. All required professors must approve the
same revision, with C++ availability rechecked before confirmation. Time changes
reset approvals; cancellation releases mandatory commitments. Optional invitations
need no acceptance and may decline without cancelling. Calendar mutations that
invalidate confirmed reservations are refused until the appointment is cancelled
or rescheduled. Removing published hours conservatively requires first resolving
all future confirmed appointments for that professor.

Search is bounded to 32 days, publication patterns to two years per pattern, duration
to one day, and returned recommendations to the first 20 by default. Manual valid
proposals are not restricted to the 15-minute recommendation grid. These are
transport/search bounds, not inferred academic calendar rules. Known university
participants are requesters and explicit committee members; attendee counts do
not provide a student enrollment roster.

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
Uncoordinated manual SQL can bypass revision checks. Room allocation rebuilds a
complete weekly batch, separately from the dated appointment reservation workflow.
Shared-room exams retain their existing capacity-sharing policy, so a
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

For a one-command Windows setup including login accounts and explicitly dated
appointment availability, use `powershell -NoProfile -ExecutionPolicy Bypass -File
scripts/run_demo.ps1`. See the [demo walkthrough](demo-walkthrough.md). This launcher
owns one local PostgreSQL cluster under Git-ignored
`build/local-demos/university-demo/`. Its saved settings select the single
application database (`resource_allocation` for new setups), shared by academic
allocations, appointments, student room requests and equipment borrowing. It does
not reset existing data or connect to an unrelated database from your normal
shell. The current local walkthrough uses this database directly; no second
operational demo database is needed. Disposable test and recovery databases remain
isolated and must be removed when their verification finishes.

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

## CSV Compatibility

| Category | Current treatment |
|---|---|
| Standalone C++ CSV CLI | `src/data/` readers/writers and no-argument CLI preserved. |
| Optional import/export | Validated `scripts/import_csv.py`, offline snapshot parsing and standalone CLI exports preserved. |
| Regression fixtures | Original `data/` and `tests/fixtures/` files preserved untouched. |
| Historical documentation | Previous iteration reports preserved; active guides describe PostgreSQL. |

`BackendResultAdapter` is file-free presentation code; `DatabaseResultAdapter`
pins one coherent repository view and exposes `get_table("requests")`, not a CSV
reader. `engine_result_projection.py` shares input/result display projections and
`result_table_schema.py` defines their columns. Old Raw Data URL selectors remain
aliases for database views, not filesystem paths. `CsvInputs` and its DTO conversion
are confined to the explicit importer. Request validation is shared independently
of import machinery. Suggestions are presented only from structured engine data.
Normal workflows, cold restart and database failures are tested with
CSV/config/lock/local-result IO forbidden.

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

## Student room configuration

Apply Alembic head before using UC-STU-02 and the notification inbox. These additive migrations do
not infer resource owners or academic dates. As a trusted university administrator,
open **Room Policies**: designate the faculty's active administrative approver,
set each known room's owning faculty/categories and optional user whitelist, and
publish dated closures where needed. An unconfigured room is intentionally not
student-bookable. A missing/disabled approver prevents selection/approval.

`RESOURCE_ALLOCATION_ROOM_STRATEGY=best_fit` is the default student single-room
selection; `greedy` is also supported. This is independent of the five existing
academic allocation strategies. The engine is called with `--rooms-json`, never
shared CSV/config. See [room architecture](architecture/student-room-design.md).

Pending requests reserve nothing. Faculty approval rechecks the exact room and
current revision, then commits the room and organizing student's commitments
together. A stale selection needs a new revision. Cancellation releases time but
retains history. Optional professor RSVP is not an exclusive personal reservation.
Existing academic allocations still require explicit calendar bindings before
their applicability can be treated as known. Later academic runs cannot overwrite
confirmed student bookings or closures. Do not bypass these application services
with ad-hoc SQL updates to schedules/policies.

The fictional [demo walkthrough](demo-walkthrough.md#student-room-request-demonstration)
uses the same primary local profile as appointments and equipment, an explicit
fictional academic period, and real engine results.
Existing profiles are not automatically assigned invented room owners. Their
stored data and credentials are preserved on restart.

## Scope boundaries

The shared notification bell uses transactional appointment/room history and
per-user PostgreSQL read state. Migration `0043c` preserves existing data and
backfills relevant history. Restart the application after upgrading; the local
demo launcher performs `alembic upgrade head` automatically. Photo uploads and
availability-watch alerts are not implemented; the header uses an initials avatar.

Iteration 42 includes authentication and dated appointment approvals/invitations;
it does not deploy the application publicly or infer dates for undated records.
Do not expose the Flask development server publicly. Weekly room schedules remain
weekday/minute intervals, while appointment calendars use explicit dates/timezones.
PostgreSQL persists both workflows; CSV remains an offline compatibility/import tool.

## Equipment borrowing

Upgrade to Alembic head before serving equipment pages. The nine additive
inventory/loan tables bring the application total to 47. Existing room/appointment
data is preserved; `notification` additionally references equipment events.
See the [equipment guide](equipment-borrowing-guide.md) for authorized custodian
assignment, inventory registration, policy configuration and fictional seeding.
New local-demo profiles include equipment; existing profiles are never reseeded.
The explicit `scripts/seed_equipment_demo.py` utility refuses existing equipment
configuration and requires acknowledgement of a development database.

Backups/restores must include the entire application schema, not only inventory
tables: requests, physical loan records, lifecycle history and notification receipts
are one consistent dataset. The existing pg_dump/pg_restore procedure remains
applicable. Never repair an overdue loan by deleting reservations or recording an
unverified return. A busy faculty/engine error rolls back the current equipment
operation; it does not publish a partial reservation.

## Unified calendar

Run `python -m alembic upgrade head` before serving the unified calendar (`0045a`).
The additive migration preserves all existing requests and adds private-by-default
academic publication metadata; there are still 47 application tables. Back up
existing databases before upgrades using the procedure above.

All roles use **Calendar**. Month/week/day navigation and filters read live records;
refresh after changes in another window. Personal blocks remain in **My Schedule**.
Administrators may publish academic titles, times, locations and optional instructor
labels using **Academic Publication**, after explicitly binding the relevant period
in **Calendar Setup**. Do not publish a private title or guess legacy academic dates.
Committees cannot be published. Published schedules do not imply enrollment, and
instructor labels do not create new scheduling commitments.

No calendar-specific seed, result file or background synchronization task is needed.
Equipment reminders depend on actual loan/reservation records; a due date is not
a verified return. Cancellation and rescheduling remain in the original workflows.

## Resource waiting lists

Back up first, then run `python -m alembic upgrade head` before serving waiting-list
pages (revision `0047a`). This is additive: original room, equipment, appointment
and academic records are retained. There are now 48 application tables plus Alembic.

An administrator must open **Administration -> Waiting-list Policy** and explicitly
set positive minimum advance-notice minutes. No university default is assumed.
Until configured, students may consent/join and staff may review, but no automatic
assignment occurs. Larger minima already recorded for entries are not reduced.

Students join from an unavailable eligible room/equipment form after reading and
accepting policy `waiting-lists-v1`. **Waiting Lists** displays their own queue;
responsible faculty staff use the same page for scoped pre-approval/rejection.
Release/return and relevant configuration actions trigger rechecks after commit.
Equipment must be physically returned; a due date alone releases nothing.

For periodic expiry, recovery after interruption, or explicit external maintenance:

```powershell
python scripts/process_waiting_lists.py
python scripts/process_waiting_lists.py --kind equipment
```

Use the application's existing `DATABASE_URL` and authoritative engine build.
An operating-system timer may run this command. It is idempotent; no job broker or
second persistence system is needed. Post-commit refresh errors are logged while
the completed physical return/cancellation stays committed. Retry after fixing
engine/database availability; never manually insert a fake confirmation.

See [queue architecture, notice, privacy and limitations](architecture/waiting-lists-design.md)
and [current requirements](srs/UC-STU-05-requirements.md). Live verification uses
isolated PostgreSQL schemas, never the operational demonstration database.
