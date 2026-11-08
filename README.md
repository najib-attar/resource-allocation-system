# University Resource Allocation and Scheduling System

A university scheduling application with Student and Professor Portals, administrative
resource allocation, and durable PostgreSQL records. The Campus Space interface uses
Flask/Jinja; a C++17 engine evaluates scheduling constraints and allocation strategies.

The project addresses a shared campus problem: coordinating rooms, equipment and
people without treating a pending request as a confirmed reservation. Requests,
approvals, physical equipment handovers and calendar publication have distinct
lifecycles and role-specific permissions.

## Implemented capabilities

### Student Portal

- Request appointments with one or multiple professors, invite optional students,
  select recommended times or propose a time, and track approvals and history.
- Request suitable rooms, inspect availability, register participants and use
  supported recurring reservations and occurrence actions.
- Browse equipment, request loans, track collection/partial returns and extensions,
  and see overdue warnings. Physical handover remains a custodian operation.
- Join eligible room/equipment waiting lists, track review and assignment, or withdraw.
- Submit private feedback and issue reports for eligible resource use.
- Use month/week/day calendars, personal schedule blocks and a persistent Inbox.

### Professor Portal

- Review student appointments and record only the professor's own approval or decline.
- Publish bounded weekly office hours and exclusions, and manage personal blocks.
- Respond to optional room invitations and view authorized calendar events and notices.
- Submit self-owned Exam, OneTime, Recurring and CommitteeMeeting academic requests.
- Track eligibility decisions, allocation results, assigned resources and history;
  revise unpublished requests with eligibility review invalidation.

Course, faculty and activity details in academic requests are declarations, not
verified teaching affiliations. Professors cannot operate administrative allocation
controls or inspect another professor's private requests.

### Administration and resource operations

Academic requests start as **Pending Eligibility Review**. An authorized administrator
records an eligibility decision and reason. Only eligible current revisions enter
allocation; eligibility approval does not reserve a room or guarantee an assignment.
Allocation results and dated calendar publication remain separate.

Legacy requests require individual review. Existing published reservations survive
review or rejection until an authorized replacement publication; outstanding relevant
legacy reviews block replacement. Active published requests are read-only.

The application also supports designated faculty room approvals, equipment custody,
waiting-list policy/review and private issue handling. These permissions are enforced
by the backend, independently of which controls appear in the interface.

The [Administration v1 guide](docs/administration/README.md) covers the shared
Campus Space Home, scoped action queues, allocation history and bounded reports
proposed for review on this branch. Sensitive account/resource extensions remain
deferred; these changes are not included in the published beta release.

## Architecture

```text
Browser -> Flask/Jinja + authentication, CSRF and role/ownership checks
        -> PostgreSQL services and revision-bound request snapshots
        -> C++17 engine over validated JSON -> transactional results/publication
```

- **C++:** allocation rules, availability checks and meeting recommendations. Five
  existing allocation strategies cover greedy, priority, multi-room and shared-room exams.
- **Flask:** server-rendered pages, workflow coordination and authorized read models;
  no separate frontend framework.
- **PostgreSQL:** application source of truth, reservations, histories, notifications
  and session revocations; SQLAlchemy, psycopg and Alembic manage persistence.
- **CSV:** explicit import and standalone C++ CLI compatibility, not live web storage.

See the [web developer guide](web/README.md), [database design](docs/architecture/database-design.md)
and [engine protocol](docs/engine-protocol.md).

## Project structure

| Path | Purpose |
| --- | --- |
| `src/` | C++ domain models, rules, strategies, services and JSON boundaries |
| `web/` | Flask routes/services, Jinja templates, shared Campus Space assets and persistence |
| `migrations/` | Alembic schema history; current head `0051b` |
| `scripts/` | Backend build, trusted account provisioning, import and local demo tools |
| `tests/` | C++, Python/PostgreSQL, security and real-browser regression tests |
| `docs/` | Requirements, architecture, operations, portal coverage and historical reports |
| `research/cdmcs/` | Isolated experimental scheduling research; not the live scheduler |
| `data/` | Offline CSV inputs for import/CLI demonstrations |

## Run locally

Prerequisites: **Python 3.12 or 3.13**, **PostgreSQL 17 tools**, and **g++ with C++17
support**. Run commands from a cloned repository's root. Python dependencies are
pinned in [requirements.txt](requirements.txt).

With Python and `g++` on PATH, build first, then start an isolated Windows demo
with generated fictional users and persistent data:

```powershell
python scripts/build_backend.py
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_demo.ps1
```

Open `http://127.0.0.1:5000`. The launcher prints the demo accounts and generated
password, verifies the built engine, applies migrations to its owned demo database and
starts Flask. Rerunning the same profile preserves accounts, passwords, appointments
and requests. Keep private `build/local-demos/` settings out of Git.

To sign in as a student and professor simultaneously, use separate browser profiles
or a normal window and an InPrivate/incognito window. Follow the
[appointment walkthrough](docs/demo-walkthrough.md#appointment-walkthrough).
The launcher accepts `-PythonPath`, `-CompilerPath`, `-PostgresBin` and `-WebPort`;
it does not install system tools. For the initial build, `--compiler PATH` selects
a compiler outside PATH. Build before launching on a fresh checkout: Windows
PowerShell can stop at the launcher's missing-engine check before its fallback.
New profiles use an explicit fictional January
2030 period; navigate to the configured dates when exploring calendars.

For a manually configured database or Linux setup, follow
[development setup](web/README.md#development-setup) and
[database operations](docs/database-operations.md). `.env.example` is a reference,
not an automatically loaded configuration. Never point demo seeding or destructive
tests at an operational database.

## Testing

Install dependencies and build the authoritative engine:

```powershell
python -m pip install -r requirements.txt
python scripts/build_backend.py
```

With `TEST_DATABASE_URL` set to a **separate disposable PostgreSQL database**:

```powershell
python -B -m unittest discover -s tests -p "test_*.py" -v
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\run_tests.ps1
python scripts/generate_database_diagrams.py --check
```

Database/recovery tests need the configured PostgreSQL service and matching backup
tools; missing prerequisites produce skips, not complete verification. See
[test configuration](web/README.md#testing), [Student evidence](docs/ui/student-portal/acceptance-report.md)
and [Professor evidence](docs/professor-services/acceptance-report.md) for browser
reproduction, exact historical results and representative real-app screenshots.
GitHub workflows run application and isolated research regression gates.

## Documentation and boundaries

Start with the [documentation index](docs/README.md) for operations, requirements,
portal traceability, screenshots and development history.

This is an academic project with a working local application, not a production
deployment package. The Flask development server should remain loopback-only.
Trusted account provisioning is implemented; public registration and password
recovery are not offered.

Academic-request notifications, academic-request cancellation and versioned
replacements of published academic requests are deferred. Appointment notifications
and authorized appointment cancellation are implemented. Weekly academic inputs
need explicit date bindings for calendar use; enrollment and teaching assignments
are not inferred from participant counts or course declarations.

**CDMCS remains experimental and inactive in application scheduling.** Its synthetic
comparisons, read-only projection boundary and research measurements are documented
separately in the [research guide](research/cdmcs/README.md). Private preference and
institutional cost-policy foundations do not activate an optimizer or establish
calibrated university weights.
