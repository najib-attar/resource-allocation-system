# Resource Allocation System (Iterative Prototype)

This repository contains an iterative C++ prototype for a university resource allocation system, with a Flask web dashboard for demonstration.

The project focuses on gradually developing a flexible allocation system for resources such as classrooms, laboratories, meeting rooms, exams, and committee meetings. The implementation follows an iterative software design approach, where each iteration introduces one or more new concepts into the prototype.

The latest implemented iteration is Iteration 40, with SpaceFactory and BackendResultAdapter refinements.

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
- strategy selection through `AllocationStrategyFactory` and `data/config.txt`
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
- `src/` : C++ prototype implementation
  - `src/models/` : domain models, requests, factories, users, spaces, allocations, time slots, participants, busy slots, and suggestions
  - `src/rules/` : rule engine, rule facade, and individual request rules
  - `src/services/` : backend workflow session, allocation service, user availability service, and meeting time suggestion service
  - `src/strategies/` : allocation strategy interface, greedy strategy, priority strategy, and multi-room exam strategies
  - `src/data/` : CSV loading, export, and structured summary writer components
  - `src/utils/` : console output helpers
- `web/` : Flask dashboard for adding requests, running the backend, viewing summaries, viewing schedules, and inspecting raw CSV data
- `data/` : CSV input/output files and configuration
- `tests/` : lightweight backend unit, integration, regression, and smoke tests
- `external/` : third-party single-header libraries, if present locally

### Design Documentation

- [Design Patterns and Principles Report](docs/design/design-patterns-and-principles/Design_Patterns_and_Principles_Report.pdf)
- [LaTeX Source](docs/design/design-patterns-and-principles/Design_Patterns_and_Principles_Report.tex)

## Data Files

The prototype currently uses CSV files in the `data/` folder:

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

The selected allocation strategy is configured in `data/config.txt`. The current demo configuration is:

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

After building the authoritative backend, also run `python -m unittest discover -s tests -p 'test_*.py' -v` for gateway, JSON/legacy parity, CSV persistence/concurrency and Flask smoke checks. The Windows run has 70 passed, 0 failed, and one POSIX-permission skip; Linux CI is configured to exercise the platform-specific path.

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

Install Flask:

```bash
pip install flask
```

Run from the project root:

```bash
python web/app.py
```

Open:

```text
http://127.0.0.1:5000
```

The web dashboard does not implement allocation logic. CSV remains temporary application persistence/import/export, but Flask executes the C++ engine through a versioned JSON stdin/stdout contract using `EngineGateway`. Structured results and meeting suggestions are atomically published as one JSON document and adapted for existing views; execution does not read shared config or write runtime CSV outputs. The C++ backend remains responsible for rules, strategies, participant availability, meeting suggestions, and allocation. See the [engine protocol](docs/engine-protocol.md) for schema, errors, compatibility, and verification.

## Web Dashboard Overview

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
- Raw Data page for direct CSV inspection

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

This repository is an iterative academic prototype. The current implementation focuses on architecture, extensibility, rule-driven evaluation, and demonstration workflows rather than production-level persistence.

Future work can build on the current structure with alternative-room meeting suggestions, future-only suggestion modes, participant-conflict-aware ranking, global optimization, database or API integration, and richer calendar integration.
