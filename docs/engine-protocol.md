# Allocation Engine Protocol, Version 1

## Equipment borrowing operation (Iteration 44)

`allocation_system --equipment-json` accepts a separate version-1 operation named
`equipment`. Existing room allocation, appointments, student rooms and standalone
CSV invocations are unchanged. No SQL/files or presentation-only borrower/asset
labels cross this operation. stdout is exactly one JSON document; diagnostics use
stderr; exit 0 means a validated result (possibly infeasible), exit 2 invalid input.
The gateway still verifies source/binary build hashes and enforces its timeout.

Input: `protocolVersion:1`, `operation:"equipment"`, nonempty `runId`, positive
`facultyId`, boolean `custodianActive`, `borrowerFacultyIds` (known organizational
ancestry), `proposed:{start,end}` (UTC epoch seconds, minute-aligned, half-open,
at most 365 elapsed days). `items` has 1-50 distinct `{typeId,quantity,specifications}`
rows; quantities are 1-1000 and specifications are exact text-valued objects of
at most 50 keys. `types` has at most 1000 objects with `id`, `facultyId`,
`categoryId`, `maxLoanDays` (1-365), `enabled`, `specifications`, `eligibleFacultyIds`.
`units` has at most 10000 `{id,typeId,condition,held,reservations}` objects;
reservations contain `{start,end}`, at most 1000 per unit. IDs are positive 32-bit
integers; dates are 1970-2100. Unknown/malformed references fail explicitly.
`held` means physically handed out and unreturned, independent of the due date.

Output echoes version/operation/run ID and adds `engineVersion:"equipment-1"`,
`status`, boolean `feasible`, `errors`, `items`, and `alternativePeriods`. Each item
has `typeId`, `availableQuantity`, `unitIds`, `reasonCode` (`AVAILABLE`,
`NO_CUSTODIAN`, `INELIGIBLE`, `INSUFFICIENT_QUANTITY`), `alternativeTypeIds`.
If any item fails, every `unitIds` array is empty. Otherwise each contains exactly
the requested quantity in stable ascending inventory-ID order. Compatible
alternative types and at most three later feasible intervals require explicit
application selection, never automatic substitution. See the
[equipment design](architecture/equipment-borrowing-design.md) for ranking rules.
The student presentation removes unit IDs before rendering unapproved candidates.

```json
{"protocolVersion":1,"operation":"equipment","runId":"example","facultyId":1,
 "custodianActive":true,"borrowerFacultyIds":[1],
 "proposed":{"start":1894003200,"end":1894089600},
 "items":[{"typeId":1,"quantity":1,"specifications":{}}],
 "types":[{"id":1,"facultyId":1,"categoryId":1,"maxLoanDays":7,"enabled":true,
           "specifications":{"architecture":"arm"},"eligibleFacultyIds":[]}],
 "units":[{"id":1,"typeId":1,"condition":"usable","held":false,"reservations":[]}]}
```

```json
{"protocolVersion":1,"operation":"equipment","engineVersion":"equipment-1",
 "runId":"example","status":"success","feasible":true,"errors":[],
 "items":[{"typeId":1,"availableQuantity":1,"unitIds":[1],"reasonCode":"AVAILABLE",
           "alternativeTypeIds":[]}],"alternativePeriods":[]}
```

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
`BackendResultAdapter` is file-free. CSV reading is confined to explicit import
utilities and standalone CLI compatibility, never a PostgreSQL fallback.

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

## Appointment operation v1 (Iteration 42)

`allocation_system --appointments-json` is a separate operation; existing
`--json` room-allocation payloads and behavior are unchanged. `EngineGateway`
uses the same authoritative executable and source/binary manifest checks for both.
One UTF-8 JSON document enters stdin, one result leaves stdout; diagnostics use
stderr. Exit 0 means a valid evaluation (including an unavailable proposal);
invalid protocol/input exits 2. Nonzero exit, timeout or invalid output is never
accepted as a successful application operation.

The application resolves bounded weekly patterns, explicit academic-period
bindings and timezone-aware commitments into UTC epoch-second intervals. The
engine never reads SQL, operating-system timezone, CSV or global config in this
operation. Intervals are half-open. C++ evaluates integer UTC seconds, 1970-2100;
the application's calendar projection emits minute-aligned instants.
The university zone is explicitly configured, default Europe/Istanbul.

| Input | Meaning |
|---|---|
| protocolVersion / operation / runId | 1 / appointment / correlation identifier |
| action | recommend or validate |
| organizerId / professorIds / invitedIds | Distinct university identities; required professors nonempty; up to 100 professors and 100 invitees |
| durationMinutes | Positive duration, at most one day |
| horizon | start/end UTC epoch seconds; bounded search of at most 32 days |
| published | userId/start/end professor publication windows |
| busy | userId/start/end blocks and known confirmed commitments |
| unresolvedIds | Participants whose legacy calendar applicability is unknown; up to all 201 participants |
| preferredStart | Optional UTC preferred instant for ranking |
| proposed | Required start/end for validate; manual proposals need not match the recommendation grid |
| limit | Optional recommendation count 1-100; default 20 |

```json
{
  "protocolVersion": 1, "operation": "appointment", "runId": "example",
  "action": "recommend", "organizerId": 1, "professorIds": [2],
  "invitedIds": [], "unresolvedIds": [], "durationMinutes": 30,
  "horizon": {"start": 1800000000, "end": 1800086400},
  "published": [{"userId": 2, "start": 1800000000, "end": 1800010800}],
  "busy": [], "limit": 1
}
```

```json
{
  "protocolVersion": 1, "operation": "appointment", "engineVersion": "appointments-1",
  "runId": "example", "status": "success", "feasible": true,
  "reasonCode": "AVAILABLE", "errors": [],
  "recommendations": [{"start": 1800000000, "end": 1800001800,
    "availableInvitees": [], "unavailableInvitees": [], "unresolvedInvitees": [],
    "preferenceDistanceSeconds": 0,
    "reason": "Mandatory participants are available within published professor hours; ranked by known-free invitees, preferred-time distance, then time."}]
}
```

Feasibility requires coverage by every professor's publication, no organizer or
required-professor conflict, resolved mandatory calendars and matching duration.
Unknown optional calendars never block, but are not counted free. Recommendations
use a 15-minute grid anchored to published windows, rank known-free invitees first,
then preferred-time distance, then chronology. Manual proposals use the same
feasibility rule. Stable reason codes are AVAILABLE, NO_FEASIBLE_TIME,
UNRESOLVED_CALENDAR, OUTSIDE_PUBLISHED_AVAILABILITY, REQUIRED_PARTICIPANT_BUSY,
ORGANIZER_BUSY and INVALID_INTERVAL. Invalid protocol returns status error with
structured INVALID_INPUT errors. Python verifies correlation, version, operation,
status, duration, horizon and the disjoint complete invitee partition.

Feasibility is not a reservation. Flask rechecks before unanimous revision-specific
confirmation and atomically records mandatory commitments in PostgreSQL. Pending
requests reserve nothing; a stale calendar snapshot cannot commit confirmation.

## Student room operation v1 (Iteration 43)

`allocation_system --rooms-json` evaluates one dated, exclusive student activity.
The original `--json` and `--appointments-json` contracts are unchanged. The same
verified executable, UTF-8 stdin/stdout, bounded timeout and structured-error rules
apply. No files, global strategy config or database are read by this operation.
Exit 0 includes a valid but infeasible evaluation; invalid input exits 2 with
`status: error`, `reasonCode: INVALID_INPUT`, structured errors and stderr diagnostics.

| Input | Meaning |
|---|---|
| protocolVersion / operation / runId | 1 / studentRoom / nonempty correlation string, at most 100 bytes |
| action | recommend, validate (exact selectedRoomId), or attendance (optional professor calendar only) |
| strategy | System-configured best_fit (default) or greedy; not the academic/exam strategy selector |
| organizerId / organizerRole | Positive university ID; Student, or Instructor for attendance |
| category / attendeeCount | study, meeting, lecture, club or other; positive total attendance |
| requiredFeatures | Distinct projector, whiteboard and/or computers |
| preferredFacultyId / preferredBuilding | 0/empty means no preference, not an access grant |
| proposed / horizon | Minute-aligned half-open UTC epoch-second intervals, 1970-2100; duration at most one day, search at most 32 days |
| organizerResolved / organizerBusy | Explicit calendar-resolution flag and dated busy intervals |
| rooms | Up to 10,000 SpaceFactory-supported rooms with capacity/facilities, availability, faculty/approver IDs, enabled/category/access policy, calendar resolution and busy intervals |

Input is bounded to 16 MiB; each busy collection to 100,000 intervals and each
whitelist to 10,000 unique positive IDs. Unknown/duplicate types, categories,
facilities, identifiers, malformed intervals or non-boolean flags are rejected.
Disabled/unconfigured rooms use facultyId/approverId 0 and cannot be selected.

```json
{
  "protocolVersion": 1, "operation": "studentRoom", "runId": "room-example",
  "action": "recommend", "strategy": "best_fit",
  "organizerId": 1, "organizerRole": "Student", "category": "study",
  "attendeeCount": 5, "requiredFeatures": [],
  "preferredFacultyId": 0, "preferredBuilding": "",
  "organizerResolved": true, "organizerBusy": [],
  "proposed": {"start": 1894009200, "end": 1894012800},
  "horizon": {"start": 1894009200, "end": 1894617600},
  "rooms": [{
    "id": 301, "name": "Fictional Study Studio", "type": "Classroom",
    "capacity": 8, "building": "Main", "available": true,
    "features": {"projector": false, "whiteboard": true, "computers": false},
    "facultyId": 10, "approverId": 20, "enabled": true,
    "restricted": false, "allowedUserIds": [], "categories": ["study"],
    "calendarResolved": true, "busy": []
  }]
}
```

```json
{
  "protocolVersion": 1, "operation": "studentRoom", "engineVersion": "student-rooms-1",
  "runId": "room-example", "status": "success", "feasible": true,
  "reasonCode": "AVAILABLE", "errors": [], "explanations": [], "alternatives": [],
  "candidates": [{"roomId": 301, "facultyId": 10, "capacity": 8,
    "spareSeats": 3, "extraFacilities": 1, "preferencePenalty": 0,
    "start": 1894009200, "end": 1894012800,
    "reason": "Eligible single room; 3 spare seats, all required facilities present; 0 unmatched preferences. Owning faculty approval is required."}]
}
```

Best-fit sorts by unmatched faculty/building preferences, spare seats, unnecessary
facilities, then room ID. Greedy retains source ordering within preference ties.
Eligibility requires policy/access, ownership/approver, capacity/facilities, resolved
calendar and no room or organizer overlap. Up to 20 exact-time candidates are
returned. Only if none exists, recommend scans a deterministic 15-minute grid
anchored to the search start, returning up to five earliest feasible alternatives.
The web uses a seven-day search; alternatives need a fresh exact-time evaluation
before submission. Validation never silently substitutes another room.

Reasons include AVAILABLE, NO_ELIGIBLE_ROOM, ROOM_DISABLED, NO_APPROVER,
ACCESS_RESTRICTED, INSUFFICIENT_CAPACITY, MISSING_FACILITY, UNRESOLVED_CALENDAR,
ROOM_BUSY and ORGANIZER_BUSY. `explanations` summarizes rejected candidates and is
not an authorization grant. Python validates correlation, operation/version,
collections, room references, capacity arithmetic, duration/horizon and feasibility
consistency, then adds display names. Private purposes/participants are not sent
to the engine. Feasibility is not a reservation: faculty confirmation rechecks
the exact selection and commits under PostgreSQL revision/overlap protection.

## Dated recurring operations v1 (Iteration 49)

Semester bounds, student whole/partial approval consent, quotas and audited queue
priority are Flask/PostgreSQL workflow concerns. They do not change the engine
contract: aggregate `feasible` still means every requested interval is feasible.
In partial mode the application uses the structured per-occurrence C++ result and
reserves only authorized selected feasible dates. It does not reinterpret a false
aggregate as a whole-series approval or reduce equipment quantities.

The original allocation, appointment, room and equipment operations are unchanged.
`--room-series-json` uses `operation: studentRoomSeries`; `--equipment-series-json`
uses `operation: equipmentSeries`. Both retain protocolVersion 1, correlation,
verified executable/build manifest, UTF-8, stdin/stdout-only execution, diagnostics
on stderr, exit 0 for a valid decision (including infeasibility) and exit 2 for
invalid input. They do not access PostgreSQL, CSV or shared configuration.

Start with the corresponding single-period input. Add `occurrences`, a complete
ordered list of 1-366 `{start,end}` minute-aligned UTC intervals. The first interval
must equal `proposed`; all have equal elapsed duration and cannot overlap. Room
inputs also require `startMinutes` (0-1439 university-local minutes) and a horizon
covering the complete series. The bounded date range is at most two years; room
search padding is limited to 732 days. Equipment type maximum loan duration is
checked independently for each interval. Python expands explicit date bounds and
weekdays in the configured timezone; C++ evaluates the actual dated intervals,
not repeated undated weekday values.

Room output retains candidates, alternatives, explanations and reasonCode, with
engineVersion `student-rooms-series-1`. Candidates use **the same room on every
date**, intersecting complete ranked sets before the top-20 display limit.
`occurrences` contains start/end, feasible, reasonCode, candidates, alternatives
and explanations per date. `NO_CONSISTENT_ROOM` in explanations distinguishes an
empty common room set. Optional alternative proposals shift the entire pattern
by a reported `offsetMinutes` within two hours; no silent date or room change is
made. Flask filters out shifts inconsistent with the local weekly pattern across
timezone transitions. Selection is revalidated before saving and confirmation.

Equipment output uses engineVersion `equipment-series-1` and per-occurrence
`{start,end,feasible,items,alternativePeriods:[]}`. Each item has the existing type,
available quantity, selected unit IDs, reason and compatible alternatives. Top-level
`items` and `alternativePeriods` are empty to avoid an ambiguous single-period
assignment. Top-level feasible is true only when every period can fulfill every
requested quantity. Different dated periods may use different physical units;
currently held units remain unavailable regardless of their planned return date.

Example recurring extension to a room input:

```json
{"operation":"studentRoomSeries","startMinutes":600,
 "occurrences":[{"start":1893999600,"end":1894003200},
                {"start":1894604400,"end":1894608000}]}
```

This is an extension fragment, not a standalone input: supply all ordinary room
fields, matching proposed/horizon, protocolVersion and runId. The response is a
proposal only. Existing faculty/custodian services approve and persist all
remaining proposed occurrences in one PostgreSQL transaction or none. Gateway
validation checks correlation, types, exact occurrence count/order/dates, child
decisions and aggregate feasibility; malformed or partial stdout is an integration
error, never a partial reservation.
