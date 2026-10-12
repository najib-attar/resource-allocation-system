# Resource Allocation System (Iterative Prototype)

This repository contains an iterative C++ prototype for a university resource allocation system, with a Flask web dashboard for demonstration.

The project focuses on gradually developing a flexible allocation system for resources such as classrooms, laboratories, meeting rooms, exams, and committee meetings. The implementation follows an iterative software design approach, where each iteration introduces one or more new concepts into the prototype.

Iteration 41 adds PostgreSQL application persistence while preserving the [versioned Flask-C++ JSON execution boundary](docs/engine-protocol.md), C++ allocation engine and existing dashboard workflows. See the [database design](docs/architecture/database-design.md) and [setup/migration guide](docs/database-operations.md).

## Current Prototype Features

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
- `docs/iteration-reports/` : Iteration reports, including Iterations 33-40
- `docs/design/class-diagrams/` : class diagram exports, including Iterations 33-40
- `docs/testing/` : backend testing and verification reports
- `docs/development/` : analysis, implementation, testing, documentation, frontend, and Git workflow guidelines
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

### Development Documentation

- [Repository Instructions](AGENTS.md): entry point for the development guides.
- [Analysis and Delivery Workflow](docs/development/WORKFLOW.md)
- [Git, Iterations, and Review](docs/development/GIT_ITERATIONS.md)
- [Existing Engine Protocol](docs/engine-protocol.md): compatibility contract for Flask-C++ execution.
- [Database Design](docs/architecture/database-design.md): entities, ER diagram, constraints and transactional workflow.
- [Database Operations](docs/database-operations.md): setup, safe import, testing and failure behavior.
- [Student-Professor Appointment Use Case](docs/use-cases/UC-STU-01-student-professor-appointment.pdf): requirements for a future feature, not current implementation.

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
Running 140 test(s)
Result: 140 passed, 0 failed
```

The test runner compiles and runs the backend smoke executable, then compiles and runs the unit and integration tests.

After installing `requirements.txt`, building the authoritative backend, and configuring an isolated `TEST_DATABASE_URL`, run `python -m unittest discover -s tests -p 'test_*.py' -v` for database integrity/concurrency, migrations, gateway, JSON/legacy parity and Flask smoke checks. The verified Windows foundation-review run executed 134 tests: 133 passed, zero failed, one POSIX-permission test skipped. Configure matching PostgreSQL backup tools as described in the [database guide](docs/database-operations.md) to run recovery tests. Without the URL/tools, relevant tests explicitly skip; such a run is not full verification. Linux CI provides a real PostgreSQL service but has not yet run for this unpublished branch. See the [iteration verification record](docs/iteration-reports/Iteration_41_progress.md) for commands and platform limitations.

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

## Web Dashboard Overview

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

## Demo Workflow

1. Compile the backend.
2. Run the Flask dashboard.
3. Select an allocation strategy.
4. Add or review requests.
5. Use `Save Request Only` for batch entry, or `Submit and Run` for a focused one-request demo.
6. Open `Allocation Summary` or the request detail page.
7. Use `Schedules` to inspect user busy slots and room allocations after allocation has run.

## Notes

This repository is an iterative academic prototype with real transactional persistence. Authentication, authorization of web actors and production deployment hardening are not implemented; do not expose the development server publicly.

Future work can build on the current structure with authentication, dated calendars and the separately approved appointment use case, richer API integration, and deployment hardening. Those features are not implemented by the database migration.
