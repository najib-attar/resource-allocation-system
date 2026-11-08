# Flask application developer guide

The application serves the Student Portal, Professor Portal and administrative
workspaces from one Flask/Jinja codebase. PostgreSQL is the source of truth.
C++17 owns allocation rules, availability and scheduling recommendations; Python
coordinates authorized workflows without reimplementing those algorithms.

## Architecture

| Layer | Main modules | Responsibility |
| --- | --- | --- |
| Application and security | `app.py`, `security.py`, `account_service.py` | Blueprint registration, login/logout, sessions, CSRF and role boundaries |
| Service workspaces | `student_routes.py`, `professor_routes.py`, appointment/room/equipment/calendar/notification routes | Authorized forms, navigation, errors and responses |
| Academic intake/review | `professor_service.py`, `academic_eligibility.py`, `eligibility_routes.py` | Owner-only intake/revisions, administrative decisions and audit history |
| Allocation integration | `allocation_workflow.py`, `engine_gateway.py`, `backend_executable.py` | Revision-bound snapshots, verified executable and validated engine responses |
| Persistence/read models | `persistence/`, `database_result_adapter.py`, dashboard services | Transactions, durable records and consistent authorized presentation |
| Presentation | `templates/`, `static/` | Shared Campus Space shell, service components, scoped CSS and page JavaScript |

```text
Authenticated form/API -> service authorization and validation -> PostgreSQL commit
Eligible snapshot -> EngineGateway -> verified C++ executable over JSON
Validated response + current revision proof -> atomic result persistence
Authorized database read model -> Jinja page / JSON response
```

C++ runs outside the snapshot transaction. Concurrent changes invalidate stale
results rather than silently publishing them. State locks, run ordering and
revision proofs protect publication. Each rendered database result view uses one
consistent snapshot. CSV/local JSON files are never a persistence fallback.
See [engine protocol v1](../docs/engine-protocol.md) and
[database architecture](../docs/architecture/database-design.md).

## Routes and permissions

| Entry point | Authorized use |
| --- | --- |
| `/login`, POST `/logout` | Trusted accounts; logout requires authenticated CSRF |
| `/student/` | Student Home |
| `/professor/` | Instructor Home |
| `/appointments/`, `/appointments/<id>` | Participant-scoped list/details and role-specific appointment actions |
| `/appointments/new` | Student-organized appointment requests |
| `/appointments/availability` | Instructor office-hour management |
| `/appointments/calendar` | Own timetable and personal blocks for signed-in roles |
| `/rooms/`, `/equipment/`, `/waiting-lists/`, `/feedback/` | Student/borrower/participant actions and designated staff operations; service checks apply |
| `/calendar/`, `/notifications/` | Authorized calendar and recipient-scoped Inbox |
| `/professor/requests`, `/professor/requests/new`, `/professor/requests/<id>` | Instructor-owned academic forms and tracking |
| `/professor/requests/<id>/revise` | Own unpublished academic revisions only |
| `/administration/`, `/administration/reports`, `/administration/runs/<id>` | Administrative Home, bounded read-only reports and persisted allocation-run history |
| `/professor/academic-requests`, `/professor/academic-requests/<id>` | Owner-scoped JSON list/detail; collection POST supports intake |
| `/academic-eligibility/`, `/academic-eligibility/<id>` | Administrative review queue and reasoned decisions |
| `/`, `/add-request`, `/requests`, `/request/<id>`, `/allocation-summary`, `/schedules`, `/raw-data` | Administrative technical workspace and allocation management |

The five university roles are Student, Instructor, TeachingAssistant, Staff and
Administrator. Administration is an explicit account capability; faculty approval,
custody and record ownership are checked separately. A role name alone does not
authorize an operation on another person's request.

Default login destinations are Student Home, Professor Home, the administrative
dashboard for an administrative account, and Appointments for other signed-in
roles. A local `next` destination is supported; destination authorization still
applies. Legacy technical redirects remain for compatibility.

The [Administration guide](../docs/administration/README.md) describes the v1
workspace proposed for review on this branch. Administrative capability does not
replace designated faculty room approval, equipment custody or private record
ownership. Dashboard/report reads use bounded, consistent SQL projections and do
not invoke the allocation engine. The technical `/` route is preserved.

## Authentication and authorization

Accounts are provisioned for existing university identities with scrypt password
hashes. There is no public registration, role selection or password recovery.
Signed sessions are HttpOnly/SameSite=Lax with an eight-hour sliding lifetime;
use Secure cookies behind HTTPS. State-changing requests require a form
`csrf_token` or `X-CSRF-Token`, including JSON submissions and logout.

Identity is resolved from the database on each authenticated request. Account
revocation and durable per-login logout denials reject replayed or delayed cookies.
Logout commits its denial before clearing the browser cookie; another independent
login remains valid. Keep a stable private secret across normal restarts.
See [session rollout and retention](../docs/database-operations.md#current-schema-0051b).

## Student–professor appointments

Students select a faculty, required professors, optional student invitees, purpose,
duration and date. Recommendations and manual proposals both pass the existing
C++ `--appointments-json` feasibility operation. Published professor hours,
explicit calendar applicability and existing mandatory commitments remain binding.

Every required professor must approve the current revision. Pending requests hold
no time; rescheduling clears approvals. Rejection prevents confirmation. Authorized
cancellation releases commitments; optional student decline does not cancel the
meeting. PostgreSQL stores approvals, histories, private notifications and half-open
mandatory-person reservations atomically. Professors cannot approve for a peer or
initiate a student appointment. See [appointment design](../docs/architecture/appointments-design.md).

## Academic eligibility and allocation

An active Instructor may submit an own Exam, OneTime, Recurring or CommitteeMeeting
request for an existing campus resource. Faculty/course/activity fields are
declarations. Committee resource requests are separate from dated student appointments.
Supported weekly slot contracts and existing exam splitting/sharing rules remain
unchanged; professors cannot select or run administrative strategies.

1. Submission commits **Pending Eligibility Review** and reserves nothing.
2. An authorized administrator other than the requester records approval/rejection
   with a reason, request revision and review version.
3. Only **Eligible current revisions** enter any academic allocation snapshot.
4. Allocation produces outcomes and actual assignments; eligibility alone guarantees neither.
5. Calendar visibility requires the existing explicit publication/applicability records.

Material unpublished revisions invalidate eligibility. Inputs in the active
publication remain read-only, including after a later eligibility rejection.
Legacy requests are not automatically approved: outstanding relevant reviews block
replacement, and current reservations remain until authorized replacement publication.
Immutable history and snapshot proofs protect concurrent review/revision/run operations.
See [approved professor contracts](../docs/srs/professor-workflows.md) and
[control-to-backend traceability](../docs/professor-services/traceability.md).

Supported allocation strategies are `greedy`, `priority`, `multi_room_exam_greedy`,
`multi_room_exam_best_fit` and `shared_room_exam_best_fit`. The web strategy setting
is persisted in PostgreSQL. The standalone CSV CLI independently uses `data/config.txt`.

## Development setup

Use Python 3.12/3.13, PostgreSQL 17 and a C++17 `g++` compiler. Commands below run
from the repository root in PowerShell. For the owned, persistent fictional Windows
demo, use the [demo launcher](../docs/demo-walkthrough.md) instead of manual seeding.

For a manually configured **new development database**:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python scripts/build_backend.py
```

Create a dedicated PostgreSQL database and application role using your PostgreSQL
administration tools. Set the connection privately; substitute the placeholder with
your own URL (URL-encode special password characters):

```powershell
$env:DATABASE_URL = '<your private postgresql+psycopg:// connection URL>'
$env:RESOURCE_ALLOCATION_SECRET_KEY = (python -c "import secrets; print(secrets.token_hex(32))")
$env:RESOURCE_ALLOCATION_TIMEZONE = 'Europe/Istanbul'
python -m alembic upgrade head
```

The secret-generation command is suitable for this shell session. For repeatable
startup, store the generated value in private local configuration and load the
same value each time; never commit it. `.env.example` is **not automatically loaded**.

To load the repository's offline inputs into an empty development database:

```powershell
python scripts/import_csv.py --data-dir data --dry-run
python scripts/import_csv.py --data-dir data
python scripts/manage_accounts.py --user-id EXISTING_USER_ID --username CHOSEN_USERNAME
```

Replace `EXISTING_USER_ID` with an imported university identity. For an explicitly
authorized administrative account, add `--administrator`. Passwords are prompted,
not passed in command arguments; existing accounts require explicit `--reset-password`
to change credentials. Import refuses populated targets. Default demo/imported
academic requests need review before allocation; do not bypass eligibility to seed results.

Start the development server:

```powershell
python web/app.py
```

Open `http://127.0.0.1:5000`. Keep this loopback development server private.
On Linux use `python3 -m venv .venv`, `source .venv/bin/activate` and `export` for
the same environment settings; the subsequent Python commands are unchanged.

### Engine build and environment

`scripts/build_backend.py` writes `build/backend/allocation_system.exe` on Windows
or `build/backend/allocation_system` on Linux, plus its `.build.json` manifest.
Flask checks current source and binary hashes; stale/root/check binaries are not
fallbacks. Use `--compiler PATH` if `g++` is not on PATH. For an intentional alternate
artifact, build with `--output PATH` and set `RESOURCE_ALLOCATION_BACKEND` to that
same path. Relative paths resolve from the repository root.

| Setting | Meaning |
| --- | --- |
| `DATABASE_URL` | Dedicated PostgreSQL URL using psycopg; required |
| `RESOURCE_ALLOCATION_SECRET_KEY` | Stable private random secret, at least 32 characters; required |
| `RESOURCE_ALLOCATION_TIMEZONE` | IANA university zone; default `Europe/Istanbul` |
| `RESOURCE_ALLOCATION_BACKEND` | Optional explicit manifest-verified engine path |
| `RESOURCE_ALLOCATION_DB_LOCK_TIMEOUT` | Database lock timeout in seconds; default 5 |
| `RESOURCE_ALLOCATION_ENGINE_TIMEOUT` | Engine timeout in seconds; default 30 |
| `RESOURCE_ALLOCATION_ROOM_STRATEGY` | Student room recommendation strategy; default `best_fit` |
| `RESOURCE_ALLOCATION_SECURE_COOKIE` | `1` for HTTPS; local HTTP needs `0` |
| `RESOURCE_ALLOCATION_DEBUG` | Development debug flag; default `0` |

Busy database writes return 503 with retry information. Engine failures/stale inputs
preserve the previous active result; database failures never switch to file storage.

### Migrations and existing data

The current chain ends `0050b -> 0051a -> 0051b`:

- `0051a` adds independent academic eligibility, immutable review history, per-run
  eligibility proofs and faculty declarations. Old inputs await explicit review;
  existing published results/reservations are preserved.
- `0051b` adds durable logout denials without changing account credentials or saved
  appointments/allocations. Pre-fix cookies require fresh sign-in.

For an existing database: back up, stop old workers, run `python -m alembic upgrade head`
against the intended database, then start matching code. Do not mix old/new
authentication workers, automatically approve legacy inputs or discard logout
denials. Populated downgrades refuse audit/revocation loss. See
[database operations](../docs/database-operations.md) for controlled rollout,
backup/restore and verification; a passing test is not permission to migrate real data.

## Testing

After dependency installation and the verified engine build, configure a separate
disposable PostgreSQL `TEST_DATABASE_URL`; never use `DATABASE_URL` as a test target.
Set `POSTGRES_TEST_TOOLS_DIR` to matching PostgreSQL binaries for backup/recovery
tests. Individual fixtures own random schemas.

```powershell
python -B -m unittest discover -s tests -p "test_*.py" -v
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\run_tests.ps1
python scripts/generate_database_diagrams.py --check
```

The PowerShell runner compiles/runs C++ tests and both isolated runtime smokes in
owned temporary directories. Linux CI provides PostgreSQL and its own C++ build
commands in the [application workflow](../.github/workflows/backend-postgresql-regression.yml).

Real-browser suites use synthetic accounts, actual Flask POSTs and disposable
PostgreSQL schemas. See [Student reproduction](../docs/ui/student-portal/README.md#reproduction),
[Professor evidence](../docs/professor-services/acceptance-report.md) and
[browser fixtures](../tests/professor/). Playwright/installed Chromium requirements
are separate from the runtime dependencies; `PLAYWRIGHT_NODE_MODULE` can select a
tool installation. Missing database/native/browser prerequisites are unavailable
coverage or skips, not proof of a full pass. Historical counts belong to their
recorded revisions.

## Limitations and related documentation

Deferred academic features: request notifications, cancellation and versioned
replacement of published requests. Appointment notifications/cancellation already
work. Calendar dates/teaching responsibility are not inferred from declarations.
A standalone student office-hours browser and unified cross-service activity API
are not implemented. Campus Space prototypes contain proposed controls and fictional
data; they are visual references, not executable feature contracts.

CDMCS and cost/preference research are not active scheduling strategies. No
production deployment configuration, public registration or password recovery is
provided. Start with the [documentation index](../docs/README.md) for current
requirements, operations, architecture and historical verification records.
