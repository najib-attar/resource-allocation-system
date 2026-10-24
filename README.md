# Resource Allocation System (Iterative Prototype)

Iteration 48 adds **private resource feedback and issue reporting** at `/feedback/`
for actual room participants and equipment borrowers. Optional reports, staff
review/resolution/reopening, maintenance audit and notifications share one workflow.
See the [use case](docs/use-cases/UC-STU-06-resource-feedback-issue-reporting.pdf),
[requirements](docs/srs/UC-STU-06-requirements.md) and
[architecture](docs/architecture/resource-feedback-design.md). Introduced with
Alembic `0048a`, this workflow preserves the existing C++ allocation behavior.
The [Iteration 48 report](docs/iteration-reports/Iteration_48.pdf) summarizes the
implementation, architecture and executed verification.

This repository contains an iterative C++ prototype for a university resource allocation system, with a Flask web dashboard for demonstration.

The project focuses on gradually developing a flexible allocation system for resources such as classrooms, laboratories, meeting rooms, exams, and committee meetings. The implementation follows an iterative software design approach, where each iteration introduces one or more new concepts into the prototype.

Iteration 41 adds PostgreSQL application persistence while preserving the [versioned Flask-C++ JSON execution boundary](docs/engine-protocol.md), C++ allocation engine and existing dashboard workflows. See the [database design](docs/architecture/database-design.md) and [setup/migration guide](docs/database-operations.md).

Iteration 42 adds authenticated student-professor appointments: real calendar dates,
bounded professor office hours/blocks, feasible recommendations, optional invitations,
unanimous revision-specific professor approval, rescheduling and cancellation. See
[appointment architecture](docs/architecture/appointments-design.md) and
[current requirements](docs/srs/UC-STU-01-requirements.md). Existing weekly room
allocation remains unchanged; legacy calendar applicability requires explicit configuration.
Technical dashboard views now require a trusted administrative account.
Students land on a personal Home page with an expandable current-month Monday-Friday hourly
timetable, their next confirmed meeting, pending requests, optional invitations and confirmed appointments
they organize. Counts and cards come from one student-scoped PostgreSQL snapshot;
pending requests are never presented as reservations.
All authenticated pages share a profile header with a circular initials avatar,
name, role and private notification bell. Appointment/room decisions and invitations
and equipment updates appear in the inbox; read state persists in PostgreSQL. Navigation remains role-aware
while backend permissions stay authoritative. See [frontend boundaries](docs/architecture/frontend-design.md).
Photo uploads and room/professor availability alerts are not enabled yet.
My Schedule is available to every signed-in user, with week navigation inside the
selected month. Appointment entry uses separate searchable participant lists,
one date and selectable feasible times. Existing commitments are shown only when
linked to the user and explicit calendar dates; course-enrollment rosters are not inferred.

Iteration 43 adds student-initiated single-room requests at `/rooms/`: C++ ranks
eligible rooms from stated needs; the selected room's designated faculty approver
revalidates before confirmation. Pending requests do not reserve rooms. Professor
invitations are optional; cancellation releases room/organizer commitments.
Existing rooms require explicit ownership/access configuration, never inferred dates
or faculty ownership. See the [student room demonstration](docs/demo-walkthrough.md#student-room-request-demonstration).
The [room architecture](docs/architecture/student-room-design.md),
[approved use case](docs/use-cases/UC-STU-02-student-room-allocation.pdf) and
[current requirements](docs/srs/UC-STU-02-requirements.md) describe the boundaries.
The [Iteration 43 report](docs/iteration-reports/Iteration_43.pdf) summarizes the
schema, workflow, architecture and verified regression evidence.

Backend presentation is file-free: database views use `get_table("requests")`, while
CSV conversion is confined to explicit import and standalone CLI compatibility.

Iteration 44 adds **student equipment borrowing** at `/equipment/`: faculty-owned
equipment types and individually tracked assets, deterministic C++ matching,
custodian approvals/reservations, physical handover, partial verified returns,
condition tracking, extensions, overdue attention flags and private notifications.
Pending requests hold nothing; due dates never imply physical return. See the
[use case](docs/use-cases/UC-STU-03-student-equipment-borrowing.pdf),
[equipment guide](docs/equipment-borrowing-guide.md), and
[architecture](docs/architecture/equipment-borrowing-design.md). The
[Iteration 44 report](docs/iteration-reports/Iteration_44.pdf) summarizes the
workflow, database additions, architectural decisions and executed verification.

Iteration 45 adds a **unified university calendar** at `/calendar/`, combining
authorized academic activities, appointments, room requests and equipment reminders
in month/week/day views without duplicating booking records or scheduling rules.
See the [calendar requirements](docs/srs/unified-calendar-requirements.md),
[architecture](docs/architecture/unified-calendar-design.md) and
[Iteration 45 report](docs/iteration-reports/Iteration_45.pdf).

The current frontend design prototype introduces a shared role-aware sidebar,
compact account/notification header, real-data student dashboard and grouped
professor-appointment form. Other service pages retain their existing interiors
while sharing the new shell. The broader visual rollout awaits review; see the
[frontend audit, design system and rollout plan](docs/architecture/frontend-design.md)
and the [Iteration 46 prototype report](docs/iteration-reports/Iteration_46.pdf).

## Current Prototype Features

Iteration 47 adds **resource waiting lists** at `/waiting-lists/` for unavailable
eligible room and equipment requests: versioned consent, owning-faculty review,
contextual FCFS positions and safe automatic assignment using existing C++ matching
and reservations. An administrator must explicitly configure minimum advance
notice; no default is invented. Physical equipment handover remains separate.
See [requirements](docs/srs/UC-STU-05-requirements.md),
[architecture and ER](docs/architecture/waiting-lists-design.md),
[acceptance cases](docs/testing/waiting-list-test-cases.md), and
[configuration/recovery](docs/database-operations.md#resource-waiting-lists), and
the [Iteration 47 report](docs/iteration-reports/Iteration_47.pdf).

The current prototype supports:

- abstract `Request` base class with inheritance
- request types:
  - `OneTimeRequest`
  - `RecurringRequest`
  - `ExamRequest`
  - `CommitteeMeetingRequest`
  - `InvalidRequest`
- request title and purpose metadata
- request lifecycle history logging:
  - created
  - evaluated
  - approved or rejected
  - exported
- request creation through `RequestFactory`
- invalid request capture for malformed rows, duplicate request IDs, unresolved users, unresolved spaces, and invalid time data
- allocation of multiple space types:
  - `Classroom`
  - `Laboratory`
  - `MeetingRoom`
- space creation through `SpaceFactory`
- user polymorphism through `UserFactory`:
  - `Student`
  - `TeachingAssistant`
  - `Staff`
  - `Instructor`
  - `Administrator`
- role-based request priority values
- space-type authorization through `UserRoleRule`
- request-type authorization through `RequestTypeRule`
- rule-based request evaluation using:
  - `RuleEngine`
  - `RuleEngineFacade`
- strategy-based allocation using:
  - `IAllocationStrategy`
  - `GreedyAllocationStrategy`
  - `PriorityAllocationStrategy`
  - `MultiRoomExamGreedyStrategy`
  - `MultiRoomExamBestFitStrategy`
  - `SharedRoomExamBestFitStrategy`
- strategy selection through `AllocationStrategyFactory`; PostgreSQL stores the web preference, while the standalone CSV CLI still uses `data/config.txt`
- exam resource sharing:
  - one exam can be split across multiple classrooms
  - best-fit room selection can reduce unused capacity
  - compatible exams can share the same room using remaining room capacity
- `assignedParticipants` stored in each `Allocation`
- minute-based `TimeSlot` support with backward compatibility for older hour-only data
- committee meeting support:
  - `RequestParticipant`
  - `data/request_participants.csv`
  - `UserBusySlot`
  - `data/user_busy_slots.csv`
  - `UserAvailabilityService`
  - `ParticipantAvailabilityRule`
  - `MeetingTimeSuggestion`
  - `MeetingTimeSuggestionService`
  - least-change ranked alternative meeting time suggestions
- centralized CSV loading and exporting through `DataController`
- backend workflow coordination through `ResourceAllocationSession`
- data-loading robustness:
  - duplicate user IDs are skipped with a warning
  - duplicate space IDs are skipped with a warning
  - auxiliary busy-slot and participant paths can be configured when loading data
- structured backend summary exports through `SummaryWriter`
- explicit export success/failure handling:
  - `AllocationWriter`, `RequestResultWriter`, and `SummaryWriter` return `bool`
  - `DataController` export methods return success/failure
  - `ResourceAllocationSession::exportResults(...)` returns `true` only when all exports succeed
- CSV export of:
  - allocations
  - request results
  - request summaries
  - allocation summaries
- Flask web dashboard for demo usage
- backend-result adaptation for Flask views through `BackendResultAdapter`
- web-based request creation, including committee meeting participant selection
- web-based `Submit and Run` workflow
- web-based request detail pages
- web-based Allocation Summary page
- web-based Raw Data page
- web-based Schedules page for user busy slots and room allocations
- rejection reasons and backend-generated meeting suggestions displayed in the dashboard
- PostgreSQL persistence through SQLAlchemy 2.x/psycopg 3, with Alembic schema migrations
- transactional request/participant saves, identifiable allocation runs, structured suggestions/history, and atomic result publication
- validated, non-destructive CSV import with dry-run and preserved IDs/submission order

## Implemented Rules

The prototype currently evaluates requests using the following rules:

- `RequestTypeRule`
- `UserRoleRule`
- `ParticipantAvailabilityRule`
- `CapacityRule`
- `FeatureRule`
- `StatusRule`
- `LocationRule`
- `AvailabilityRule`

`RequestTypeRule` checks whether a requester can submit the selected request type. `UserRoleRule` checks whether the requester can use the requested space type. `ParticipantAvailabilityRule` checks required human participants for `CommitteeMeetingRequest` objects against loaded busy slots and already approved committee allocations, even in different rooms. Meeting suggestions respect these same participant commitments. `AvailabilityRule` checks physical room time availability.

The effective normal rule order is:

```text
RequestTypeRule
-> UserRoleRule
-> ParticipantAvailabilityRule
-> CapacityRule
-> FeatureRule
-> StatusRule
-> LocationRule
-> AvailabilityRule
```

## Repository Structure

- `docs/srs/` : Software Requirements Specification
- `docs/analysis/` : Initial domain analysis and domain model
- `docs/iteration-reports/` : Iteration reports, including Iterations 33-49
- `docs/design/class-diagrams/` : class diagram exports, including Iterations 33-40
- `docs/testing/` : backend testing and verification reports
- `docs/use-cases/` : user-facing feature requirements; not a list of implemented features
- `src/` : C++ prototype implementation
  - `src/models/` : domain models, requests, factories, users, spaces, allocations, time slots, participants, busy slots, and suggestions
  - `src/rules/` : rule engine, rule facade, and individual request rules
  - `src/services/` : backend workflow session, allocation service, user availability service, and meeting time suggestion service
  - `src/strategies/` : allocation strategy interface, greedy strategy, priority strategy, and multi-room exam strategies
  - `src/data/` : CSV loading, export, and structured summary writer components
  - `src/utils/` : console output helpers
- `web/` : Flask routes, presentation adapters, engine gateway, allocation workflow and PostgreSQL persistence
- `migrations/` : versioned Alembic database schema
- `data/` : offline CSV import/CLI fixtures and generated CLI outputs, not operational web persistence
- `tests/` : lightweight backend unit, integration, regression, and smoke tests
- `external/` : third-party single-header libraries, if present locally

### Design Documentation

- [Design Patterns and Principles Report](docs/design/design-patterns-and-principles/Design_Patterns_and_Principles_Report.pdf)
- [LaTeX Source](docs/design/design-patterns-and-principles/Design_Patterns_and_Principles_Report.tex)

### Project Documentation

- [Existing Engine Protocol](docs/engine-protocol.md): compatibility contract for Flask-C++ execution.
- [Database Design](docs/architecture/database-design.md): entities, ER diagram, constraints and transactional workflow.
- [Database Operations](docs/database-operations.md): setup, safe import, testing and failure behavior.
- [Iteration 41 Report](docs/iteration-reports/Iteration_41.pdf): PostgreSQL persistence, database tables, diagrams, migration and verification.
- [Iteration 42 Report](docs/iteration-reports/Iteration_42.pdf): authenticated dated appointments, calendar coexistence, approval integrity and verification.
- [Student-Professor Appointment Use Case](docs/use-cases/UC-STU-01-student-professor-appointment.pdf): requirements for the implemented appointment workflow.

## Data Files

PostgreSQL is the source of truth for normal web operations. The following `data/` files remain for explicit migration/import and the standalone C++ CSV CLI:

- `users.csv`
- `spaces.csv`
- `requests.csv`
- `request_participants.csv`
- `user_busy_slots.csv`
- `config.txt`
- `allocations.csv` (generated output)
- `request_results.csv` (generated output)
- `request_summaries.csv` (generated output)
- `allocation_summaries.csv` (generated output)

CSV inputs use UTF-8 (an optional BOM is accepted), comma separators, and standard double-quote escaping compatible with Python's `csv.writer`. Quote fields containing commas, quotes, or line breaks, and represent a literal quote as `""`. Empty optional fields retain their existing defaults; LF and CRLF record endings are supported. The backend warns and skips malformed user/space/auxiliary records, while malformed request records become rejected `InvalidRequest` objects. An unterminated quoted field consumes the remaining input as one malformed record rather than guessing new row boundaries.

The standalone CSV CLI strategy is configured in `data/config.txt`. The current fixture configuration is:

```text
allocation_strategy=shared_room_exam_best_fit
```

## Testing and Verification

A formal backend testing report source is available under `docs/testing/`:

- [Backend_Testing_Report.tex](docs/testing/Backend_Testing_Report.tex)

PDF exports are also stored in `docs/testing/` when generated.

The current lightweight test suite is run with:

```powershell
powershell -ExecutionPolicy Bypass -File tests\run_tests.ps1
```

The latest verified result is:

```text
Running 187 test(s)
Result: 187 passed, 0 failed
```

The test runner compiles and runs the backend smoke executable, then compiles and runs the unit and integration tests. Its executables are created in an owned temporary directory and removed on success or failure; existing build artifacts and data are not deleted.

After installing `requirements.txt`, building the authoritative backend, and configuring an isolated `TEST_DATABASE_URL`, run `python -m unittest discover -s tests -p 'test_*.py' -v` for database integrity/concurrency, migrations, gateway, JSON/legacy parity and Flask smoke checks. Configure matching PostgreSQL backup tools as described in the [database guide](docs/database-operations.md) to run recovery tests. Without the URL/tools, relevant tests explicitly skip; such a run is not full verification. Linux CI provides a real PostgreSQL service.

Iteration 50 local verification: 491 Python tests run, 490 passed and one expected
Windows skip (POSIX executable permissions). All 187 C++ tests and both isolated
CLI smokes passed. Desktop/mobile checks cover 52 authenticated role-specific
page views. The serial test runner still exercises actual concurrent actors and
worker processes; database tests require the isolated PostgreSQL setup above.
See the [Iteration 50 report](docs/iteration-reports/Iteration_50.pdf) for the
maintenance decisions, measured calendar loading and complete local verification.

## Iterative Development Summary

- Iterations 1-4: basic one-time request support and initial allocation rules
- Iterations 5-6: recurring requests and day-based time slots
- Iterations 7-10: feature, status, location, and rejection-reason support
- Iteration 11: CSV-based data loading
- Iteration 12: abstract `Request` base class and request polymorphism
- Iteration 13: centralized `RuleEngine` and `RuleEngineFacade`
- Iteration 14: structured user roles and role-based authorization
- Iteration 15: request priority support integrated with the request model
- Iteration 16: `DataController` introduced with CSV-based request loading and result exporting
- Iteration 17: request lifecycle history logging added and exported in request results
- Iteration 18: allocation strategy pattern introduced with `IAllocationStrategy` and default `GreedyAllocationStrategy`
- Iteration 19: explicit greedy batch processing
- Iteration 20: `AllocationStrategyFactory` and config-based strategy selection
- Iteration 21: `PriorityAllocationStrategy`
- Iteration 22: user polymorphism and `UserFactory`
- Iteration 23: `RequestFactory`
- Iteration 24: request title and purpose metadata
- Iteration 25: `ExamRequest`
- Iteration 26: `RequestTypeRule`
- Iteration 27: `assignedParticipants` and strategy access to the full space pool
- Iteration 28: `MultiRoomExamGreedyStrategy`
- Iteration 29: `MultiRoomExamBestFitStrategy`
- Iteration 30: minute-based `TimeSlot` support
- Iteration 31: extended user and organization model
- Iteration 32: `SharedRoomExamBestFitStrategy` for exam-to-exam same-room capacity sharing
- Iteration 33: `UserBusySlot`, `UserAvailabilityService`, and `user_busy_slots.csv`
- Iteration 34: `CommitteeMeetingRequest`, `RequestParticipant`, and `request_participants.csv`
- Iteration 35: `ParticipantAvailabilityRule` added to the rule pipeline
- Iteration 36: common available time suggestions for rejected committee meetings
- Iteration 37: least-change ranking for valid meeting time suggestions
- Post-Iteration-37 cleanup: duplicate user/space ID handling and configurable auxiliary data paths
- Iteration 38: `ResourceAllocationSession` added as a backend workflow facade/session
- Iteration 39: structured backend summary exports through `SummaryWriter`
- Iteration 39 robustness improvement: explicit export success/failure handling across writers, `DataController`, `ResourceAllocationSession`, and `main.cpp`
- Iteration 40: `SpaceFactory` introduced for centralized space creation and `BackendResultAdapter` introduced to reduce duplicated Flask result parsing
- Iteration 41: PostgreSQL replaces operational CSV/config/local-result persistence; database snapshots feed the unchanged C++ JSON protocol, with transactional allocation publication and database-backed views
- Iteration 42: authenticated student-professor appointment workflows, explicit dated calendar applicability, C++ feasibility/recommendations and transactional unanimous approval

## How to Compile and Run Backend

From PowerShell in the project root:

```powershell
python scripts/build_backend.py
```

Run:

```powershell
.\build\backend\allocation_system.exe
```

The backend loads CSV files, reads `data/config.txt`, processes requests with the selected strategy, prints request outcomes, and exports `allocations.csv`, `request_results.csv`, `request_summaries.csv`, and `allocation_summaries.csv`.

The build script requires `g++` on PATH (or `--compiler <compiler-path>`) and writes the authoritative executable plus its build manifest under `build/backend/`. On Linux, run `./build/backend/allocation_system`. Flask validates the manifest, binary hash, and current C++ source hash before execution; old root/check executables are never fallbacks. See [web configuration](web/README.md#compile-the-c-backend) for an explicit executable override.

## How to Run Web Dashboard

For a ready-to-explore Windows demo with fictional students, professors, login
accounts and appointment calendars, run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_demo.ps1
```

This installs the pinned Python packages and reuses one private PostgreSQL
application database for every service, populated with fictional data. The default
local profile is `build/local-demos/university-demo/`; new setups name the database
`resource_allocation`. Existing settings and data are never reset. Read the
[step-by-step demo walkthrough](docs/demo-walkthrough.md) for accounts, explicit
fictional dates, student/professor approval and administrator screens.

Install application dependencies and initialize a dedicated PostgreSQL database following the [database guide](docs/database-operations.md):

```bash
python -m pip install -r requirements.txt
python -m alembic upgrade head
python scripts/import_csv.py --data-dir data --dry-run
python scripts/import_csv.py --data-dir data
```

Run from the project root:

```bash
python web/app.py
```

Open:

```text
http://127.0.0.1:5000
```

Set `DATABASE_URL` before migrations and web startup; `.env.example` is a reference, not automatically loaded. Import refuses populated targets. The web dashboard does not implement allocation logic: it builds ordered PostgreSQL snapshots, calls `EngineGateway`, and persists validated results transactionally. `DatabaseResultAdapter` supplies one pinned database view per response. No normal web operation reads/writes CSV persistence or `engine-result.json`. C++ retains rules, strategies, availability and suggestions. JSON protocol v1 is unchanged.

Configure `RESOURCE_ALLOCATION_SECRET_KEY` with at least 32 private random characters
and `RESOURCE_ALLOCATION_TIMEZONE=Europe/Istanbul`. Provision trusted identities
with `python scripts/manage_accounts.py --user-id <existing-user-id> --username <username>`;
add `--administrator` only for technical dashboard management. Passwords are prompted,
not passed on the command line. See [account/calendar setup](docs/database-operations.md#accounts-and-appointment-calendars).
Students land at `/student/` after sign-in; professors use `/appointments/` and
administrators retain the technical dashboard. The weekly
administration grid and dated participant calendar are deliberately separate.
For HTTPS set `RESOURCE_ALLOCATION_SECURE_COOKIE=1`; debug defaults off.

## Web Dashboard Overview

### Unified University Calendar

Open **Calendar** after signing in. `/calendar/` combines appointments, room
activities, explicitly dated academic schedules and equipment pickup/return
reminders. Choose month, week or day; use Previous, Next, Today and category/status
filters. Details link back to the original service. Pending/cancelled activities,
optional invitations and staff responsibilities are distinguished from personal
commitments. Equipment deadlines never reserve a person's time.

Private events are scoped server-side to their participants or designated staff.
The **Published academic schedule** audience includes only administrator-published
academic metadata, not enrollment lists. Existing records are private by default;
administrators use **Academic Publication** and **Calendar Setup** to publish and
explicitly date academic activities. Undated legacy records produce a warning,
not guessed calendar dates. The existing **My Schedule** page still manages blocks.
See the [calendar architecture](docs/architecture/unified-calendar-design.md).

For a new empty development database, `python scripts/seed_demo_database.py --seed 41 --run-allocation` creates reproducible fictional university data and runs the real engine. Use `--size large` for a 1,200-request sanity dataset. Seeding never overwrites/resets existing data. See the [ER diagrams and full schema inventory](docs/architecture/database-design.md) and [demo/recovery guide](docs/database-operations.md).

The current dashboard supports:

- strategy selection on the Dashboard page
- `Run Allocation`
- `Add Request` for `OneTime`, `Recurring`, `Exam`, and `CommitteeMeeting`
- `Submit and Run` for quickly adding a request and viewing its backend result
- committee participant selection with participant roles
- searchable Requests page
- request detail pages at `/request/<requestId>`
- Allocation Summary cards for approved, rejected, and pending requests
- display of committee participants, rejection reasons, and least-change suggestions
- Schedules page for user busy slots and space allocations
- Raw Data page for database-backed technical tables (legacy CSV-style tab names retained)

Flask does not check participant availability and does not compute suggestions. Those behaviors belong to the C++ backend.

## Recurring Student Reservations

Room and equipment forms support bounded weekly reservations with multiple
weekdays, explicit dates and a full occurrence preview. One faculty/custodian
decision follows the student's all-required or partial-approval consent. Selected
feasible dates reserve resources; pending/unavailable/rejected dates remain visible.
One explicitly configured semester must contain the full series. Administration
configures optional quotas and permitted priority levels; responsible staff overrides
require an immutable reasoned audit. Existing eligible queues retain priority/FCFS.
Rooms stay consistent across dates; equipment has separate physical handovers
and verified returns. Cancel a future date or remaining future dates while
retaining past history. Equipment deadlines are reminders, never assumed returns.
Upgrade to Alembic `0049b` and rebuild the verified backend before using the new
forms. See [recurrence design](docs/architecture/recurring-reservations-design.md)
and [operations](docs/database-operations.md#recurring-room-and-equipment-reservations).
The [Iteration 49 report](docs/iteration-reports/Iteration_49.pdf) summarizes
the architecture, database additions, verified tests and remaining limits.

## Demo Workflow

1. Compile the backend.
2. Run the Flask dashboard.
3. Select an allocation strategy.
4. Add or review requests.
5. Use `Save Request Only` for batch entry, or `Submit and Run` for a focused one-request demo.
6. Open `Allocation Summary` or the request detail page.
7. Use `Schedules` to inspect user busy slots and room allocations after allocation has run.

## Notes

This repository is an iterative academic prototype with transactional persistence,
authenticated appointment workflows and role/ownership authorization. Production
deployment hardening is not complete; do not expose the development server publicly.

Future work can build on the current structure with richer API integration and
deployment hardening. Existing weekly allocation and dated appointments are
implemented as separate, compatible workflows.
