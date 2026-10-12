# Allocation Engine Protocol, Version 1

## Boundary and Invocation

Application persistence is PostgreSQL. **Execution is JSON**, independent of
database drivers and offline CSV import/CLI files:

```text
Flask -> ordered PostgreSQL snapshot -> EngineGateway -> executable --json
        JSON stdin -> ResourceAllocationSession -> existing rules/strategies
        JSON stdout -> transactional PostgreSQL publication -> DatabaseResultAdapter -> views
```

Build using `python scripts/build_backend.py`. The authoritative artifact and
adjacent build manifest are unchanged. Python verifies both binary and source
SHA-256 hashes before invoking `[absolute_executable, "--json"]`, without a shell.
Windows and Linux use the same stdin/stdout contract, UTF-8 encoding, and timeout.
The C++ JSON mode never opens CSV/config files or invokes CSV writers.

Send exactly one JSON object on stdin and close stdin. stdout contains exactly
one JSON result followed by a newline. Human-readable engine diagnostics go to
stderr. Clients must check the exit code **and** the response envelope before
accepting a result. `engineVersion` identifies the protocol-capable engine;
the gateway log/persisted `build` metadata identifies the exact verified binary.

## Input

Required top-level fields:

| Field | Meaning |
|---|---|
| `protocolVersion` | Integer `1` |
| `runId` | Nonempty client correlation string, returned unchanged |
| `strategy` | One of the five exact strategy keys below; no JSON-mode fallback |
| `users` | User objects with positive integer `id`, `name`, `role` |
| `spaces` | Space objects with `id`, `name`, `type`, positive `capacity`, boolean `available`, `features` |
| `busySlots` | Objects with existing `userId`, `slot`, optional `reason` |
| `requests` | Request objects; an empty batch is valid |

User roles: `Student`, `TeachingAssistant`, `Staff`, `Instructor`, `Administrator`.
Optional profile fields: `email`, `status` (default `active`), `primaryUnit`,
`assignedRoles` (string array), `studentNo`, `program`, `yearLevel` (nonnegative
integer), `title`, `officeRoom`, `assistantType`, `jobTitle`, `adminLevel`.
Priority and permissions are **derived by existing C++ user subclasses**, not sent by UI.

Space types: `Classroom`, `Laboratory`, `MeetingRoom`. `features` contains three
required booleans: `projector`, `whiteboard`, `computers`. `building` is optional.

Every request has positive integer `id`, existing `requesterId`, existing `spaceId`,
positive integer `participantCount`, `type`, and nonempty `slots` array.
Each slot is `{day, startMinutes, endMinutes}`: day 1-7, minutes since midnight,
`0 <= startMinutes < endMinutes <= 1440`. No textual time parsing crosses the
execution boundary. Working-hour and user-permission rules remain engine decisions.

Optional strings: `title`, `purpose`, `requiredFeature`, `requiredBuilding`.
Missing/empty title and purpose retain domain defaults. Empty feature/building
means no preference. Legacy CSV inputs' `None` sentinel is translated to an empty
optional value by the snapshot adapter, not transmitted as a protocol convention.

| Type | Additional requirements |
|---|---|
| `OneTime` | Exactly one slot |
| `Recurring` | One or more explicit occurrence slots |
| `Exam` | Exactly one slot; `exam` object with boolean `canSplitAcrossRooms`, optional `courseCode`, `courseName`, `examType` |
| `CommitteeMeeting` | Exactly one slot; `participants` array of `{userId, role?}`; role defaults to `Participant` |

Participant IDs must reference existing users and cannot repeat within a request.
An empty committee participant list is structurally valid but rejected by the
existing participant rule. Meeting topic and duration are derived from existing
request metadata and its slot, not duplicated in the protocol.

Strategies: `greedy`, `priority`, `multi_room_exam_greedy`,
`multi_room_exam_best_fit`, `shared_room_exam_best_fit`.

Invalid shapes, numeric types (including booleans/fractions), ranges, references,
duplicate entity IDs, unknown roles/space/request types or strategy keys reject
the **whole execution**, before allocation. They are protocol errors, not silently
skipped CSV rows. Unknown additional fields are ignored for forward-compatible
metadata; they do not affect allocation. Limits: 16 MiB document, 10,000 items per
validated array, signed 32-bit entity/count fields. These are transport limits,
not a guarantee of bounded strategy computational cost.

## Output

Required envelope: `protocolVersion`, `engineVersion`, `runId`, `strategy`,
`status` (`success` or `error`), `requestResults`, `allocations`, `suggestions`, `errors`.
All four collections are arrays even when empty. A successful batch may contain
rejected requests; `success` describes successful engine execution, not universal approval.

- Each `requestResults` item includes `requestId`, `requestType`, `title`, `purpose`,
  `requesterId`, `requesterName`, `requesterRole`, `priority`, `status`, `reasonCode`,
  `rejectionReason`, `history` (string array), `participantCount`, `requestedSpaceId`,
  requested `slots`, requirements, `participants`, `exam`, `assignedParticipants`,
  `allocationCount`, `allocationIds`, `allocatedSpaceIds`.
- Decisions use `Approved` / `Rejected`. Version 1 reason codes are deliberately
  coarse: `APPROVED` / `REQUEST_REJECTED`; detailed explanation is in `rejectionReason`.
  Clients must not infer suggestions or decisions from history text.
- Each allocation includes `allocationId`, `requestId`, `spaceId`, `spaceName`,
  `spaceType`, `building`, `spaceCapacity`, structured `slot`, `assignedParticipants`,
  and `requiredParticipantIds`. Multi-room exams create multiple rows. Recurring
  assigned participant totals are summed across occurrences, not distinct people.
- Each suggestion group has `requestId` and `items`. Every item includes `spaceId`,
  structured `slot`, `score`, `timeDistanceMinutes`, `dayDistance`, `conflictCount`,
  `reason`. An empty group means scanning found no alternative. No group means
  suggestion scanning was not applicable. Ranking/limit remains the existing top three.
- Each error has stable `code` and human-readable `message`. Common codes:
  `INVALID_INPUT`, `UNSUPPORTED_VERSION`, `UNKNOWN_STRATEGY`, `MALFORMED_JSON`,
  `INPUT_TOO_LARGE`, `ENGINE_FAILURE`.

Exit codes: **0** successful execution; **2** invalid input/protocol/usage;
**3** internal engine/output failure. Invalid JSON cannot supply a correlation ID,
so the error envelope may have an empty `runId`. The gateway never publishes any
nonzero-exit result, malformed stdout, incomplete collection, or mismatched version/run.

## Example

```json
{
  "protocolVersion": 1, "runId": "demo-1", "strategy": "greedy",
  "users": [{"id": 1, "name": "Ada", "role": "Instructor"}],
  "spaces": [{"id": 101, "name": "B201", "type": "Classroom", "capacity": 40,
    "available": true, "building": "Main",
    "features": {"projector": true, "whiteboard": true, "computers": false}}],
  "busySlots": [],
  "requests": [{"id": 1, "type": "OneTime", "requesterId": 1, "spaceId": 101,
    "participantCount": 10, "title": "Lecture", "purpose": "Teaching",
    "slots": [{"day": 1, "startMinutes": 600, "endMinutes": 660}]}]
}
```

Abbreviated successful response (additional documented fields omitted here):

```json
{
  "protocolVersion": 1, "engineVersion": "allocation-engine-json-1",
  "runId": "demo-1", "strategy": "greedy", "status": "success",
  "requestResults": [{"requestId": 1, "requestType": "OneTime", "status": "Approved",
    "reasonCode": "APPROVED", "rejectionReason": "", "allocationCount": 1,
    "assignedParticipants": 10}],
  "allocations": [{"allocationId": 1, "requestId": 1, "spaceId": 101,
    "spaceName": "B201", "spaceType": "Classroom", "building": "Main",
    "spaceCapacity": 40, "assignedParticipants": 10, "requiredParticipantIds": [],
    "slot": {"day": 1, "startMinutes": 600, "endMinutes": 660}}],
  "suggestions": [], "errors": []
}
```

## Flask Persistence, Publication and Compatibility

PostgreSQL identities and short state-row transactions protect request IDs,
request/participant saves, strategy preferences, snapshot capture and publication.
No global config is mutated while the engine runs: the captured strategy travels
inside JSON. Save Only never executes the engine. Submit and Run first saves; on
engine failure/timeout the new request remains pending and previous results remain active.

The C++ process executes outside a database transaction. Publication verifies the
captured input revision, then commits decisions, allocations, suggestions, history,
run status and the active-run reference together. An older run cannot replace a
newer completed run. Failed/stale runs keep the previous successful run active.
Readers pin one repeatable-read database view per response. No local result JSON,
runtime CSV outputs or execution workspaces are involved in normal web operations.

`engine_result_projection.py` provides **in-memory** compatibility tables to the
existing dashboard, schedules and Raw Data templates. These tables are views of
JSON, not files written by C++. Structured suggestions are formatted directly.
`DatabaseResultAdapter` reuses presentation formatting without file reads or history
parsing for suggestions. Before the first database run, views show pending requests.
Legacy `BackendResultAdapter` file support remains for offline compatibility/tests,
not as a fallback when PostgreSQL is unavailable.

Running the executable **without arguments** keeps the CSV CLI: reads `data/*.csv`
and `config.txt`, prints console outcomes and exports the original four CSVs.
Its config fallback, CSV schemas and quoted UTF-8 CSV contract remain unchanged.
CSV import/export remains legitimate through explicit import utilities and the CLI;
the quoted-field defect was already fixed in `CsvReader`, not removed by this iteration.

Allocation behavior matches legacy mode on representative fixtures. The JSON history
is a structured array of domain events and does not append the CSV writer's `exported`
marker, since no CSV export occurs. Transport-invalid input fails the whole JSON run,
whereas legacy CSV loading retains its per-row warning/`InvalidRequest` behavior.

JSON eliminates shared engine input/config/output races and mixed output generations.
Operational CSV coordination has been replaced by database transactions. Offline
CSV utilities retain their existing checks; CLI edits do not update PostgreSQL.
See [database design](architecture/database-design.md) and
[operations](database-operations.md) for migration, concurrency and failure details.

## Verification

Install `requirements.txt`, configure an isolated `TEST_DATABASE_URL`, build first,
then run `powershell -ExecutionPolicy Bypass -File tests\run_tests.ps1`
and `python -m unittest discover -s tests -p 'test_*.py' -v`.
Tests include JSON parsing/serialization, malformed protocol, gateway failure modes,
all four request types, shared/multi-room exams, structured suggestions, real Flask
flows and legacy-vs-JSON comparison of two fixtures across all five strategies.
The existing Linux CI discovers these tests; Windows execution does not verify
Linux locks/permissions. No result is a proof of correctness for all possible inputs.
