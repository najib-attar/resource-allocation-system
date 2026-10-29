# I3b: authorized read-only calendar projection

This experimental Python module reads existing application calendars into I3a's
immutable `Snapshot` DTO. It registers no routes, selects no scheduler, launches
no engine, and creates no bookings, approvals, permissions or background work.
The existing appointment scheduler remains the default.

## Architecture and reuse

```text
Authenticated Flask request (existing signed session and g.principal)
  -> CalendarProjectionService
  -> owned PostgreSQL REPEATABLE READ / READ ONLY transaction
  -> AccountService.identity(..., session=owned_session)
  -> existing participant/context authorization and calendar_snapshot
  -> project_facts: opaque, immutable, minimized facts
  -> CalendarProjection (server-internal only; engine execution disabled)
```

- [service.py](service.py) owns the read boundary and context authorization.
- [projection.py](projection.py) maps already-authorized calendar facts without
  querying the database or deciding feasibility.
- [AccountService](../../../web/account_service.py) accepts an optional existing
  session so identity/revocation checks and calendar reads share one database
  snapshot. Existing callers retain the same authentication behavior.
- [AppointmentService](../../../web/appointment_service.py) supplies the existing
  `_participants` and `_visible` policies. These deliberate private-method
  dependencies are covered by integration tests; changes to them require review.
- [calendar_snapshot](../../../web/calendar_service.py) remains the authoritative
  calendar projection. There is no second availability or conflict-checking engine.
- [I3a](../i3a/README.md) supplies immutable interval/participant/commitment types
  and existing grid semantics. Both C++ engines, EngineGateway, database schema,
  migrations and application routes remain unchanged.

## Verified authorization boundary

| Context | Current support / permission |
|---|---|
| Student searches for a new appointment | Own organizer identity only, selected active professors in a valid faculty, optional active students. Reuses the existing student route and participant rules. |
| Organizer reviews an existing appointment | Existing own Pending Approval or Confirmed record; only its exact interval is projected. |
| Required professor reviews an existing appointment | Must actually belong to a Pending Approval record's required professors; only its exact interval. An administrative grant does not bypass membership. Confirmed-record detail access does not establish a further evaluation grant. |
| Invited student | Existing appointment details remain visible, including approval progress. Invitation-only access does **not** authorize raw calendar projection. |
| Professor organizes a new appointment | Unsupported: current appointment routes and database aggregate constraints require a student organizer. |
| Administrator or committee initiates/on behalf of another person | Unsupported: no corresponding dated-appointment permission is established. Legacy administrative/committee access does not create that grant. |
| Unrelated user, anonymous or revoked session | Denied before calendar retrieval. |

The API takes no caller-supplied principal or organizer ID. Identity comes from
the authenticated request, is checked against the signed session, and is resolved
again from PostgreSQL in the same read transaction. Forged principal attributes,
revoked sessions and disabled identities fail closed. The generic DTO itself has
no student/professor dispatch; application policy stays outside optimization.

These restrictions deliberately stop unsupported paths rather than inventing new
roles or permissions. There is no new public endpoint for obtaining these objects.

## Authoritative calendar facts

| Source | Meaning retained from production |
|---|---|
| `professor_availability` | Weekly hours expanded only inside explicit validity dates, using each pattern's timezone and excluded dates. Overlapping/touching windows retain their original boundaries for I3a normalization. No published hours means no offered time, not an inferred open calendar. |
| `calendar_block` | Dated personal blocks, including partial-day exceptions. Reasons are discarded. |
| `appointment_commitment` | Confirmed mandatory-person commitments. Pending/declined/cancelled appointments have no materialized reservations. Existing deferred aggregate constraints enforce this. |
| `room_organizer_commitment` | Actual dated room organizer obligations, including confirmed recurring occurrences. Existing cancellation releases these records. |
| `busy_slot`, active-run `allocation`, `request_participant` | Existing scoped legacy projection: requester and explicitly recorded participants only. No enrollment is inferred from seat counts. |
| `academic_period`, `legacy_calendar_binding` | Explicit date/week validity and excluded dates. Unbound mandatory applicability is unresolved, not free. |
| `application_state` | Calendar revision and active allocation run read in the same transaction. |
| `appointment_professor`, `appointment_invitation` | Existing required/optional context membership. Optional busy/unresolved or declined students never become mandatory scheduling constraints. |
| Equipment loans/deadlines | Not participant-busy intervals and not exclusive appointment resources. The equipment workflow remains separate. |

Review of an authorized existing appointment excludes only that appointment's own
commitments, as the current approval/rescheduling evaluation already does. No
arbitrary appointment exclusion or broad search range is accepted for this path.
Declined/cancelled record visibility does not create an active scheduling context.

The existing approval evaluation passes all recorded optional invitation IDs,
including declined invitations, to its calendar input. This projection preserves
that behavior rather than inventing a different ranking policy. Room invitees,
group registrations and anonymous attendee counts do not implicitly create new
participant-busy records; only the existing commitment sources above apply.

The existing 0042b aggregate triggers already prohibit missing/inconsistent
confirmed appointment commitments. This module neither duplicates those checks
nor attempts data repair. Invalid timezone, interval or participant configuration
fails with a sanitized error. It relies on the reviewed migrations being applied;
it cannot attest an externally damaged database with disabled integrity triggers.

## Snapshot and privacy

Snapshots retain the university IANA timezone (default `Europe/Istanbul`), exact
minute-aligned UTC epoch seconds, half-open intervals, a UTC anchor, duration and bounded
horizon. Searches retain the production 15-minute, first-professor-window anchor;
explicit manual proposals retain their exact singleton start, including off-grid
times. Cross-midnight intervals are not split into unrelated weekly records.
New local request instants and published local times pass the existing gap/fold
validator, even if a caller constructed an ambiguous/nonexistent aware local
datetime. Pass an explicit UTC instant across a fold. Stored PostgreSQL timestamptz
values already identify absolute instants and are converted directly, not reparsed
as ambiguous wall times.

Each projection creates fresh opaque participant aliases and busy-record labels.
There are no names, emails, login IDs, database appointment IDs, purposes, reasons,
participant lists of unrelated meetings, resource serial numbers or credentials.
Only necessary per-person protected busy intervals are retained. Group identity,
relocation permission and private event metadata are not represented.

`CalendarProjection.summary()` exposes only version/revision and disabled-execution
metadata. `internal_snapshot()` intentionally exposes restricted server-internal
facts, **not** a response DTO. Never return it from a route, log it, or persist it
as research evidence. Sanitized `repr` methods hide calendar contents; Python
in-process access is not a security sandbox against malicious trusted code.

The DTO carries `origin="authorized_calendar"`. Prepared participant preferences
are `None`: the database has no CDMCS rate/gap/fairness preference model, and no
zero-cost university preferences are invented. Explicit production preferred-time
input can be retained separately. I3a normalization refuses engine serialization
of this origin, and the synthetic-only parser/CLI/export boundary remains closed.
Even synthetic PostgreSQL test records are **not** relabeled as I3a synthetic
fixtures merely because they were generated for tests.

Limits match the supported boundary: 32 days, duration 1-1440 minutes fitting the
horizon, 100 required professors and 100 optional invitees, 10,000 busy facts,
1,024 published intervals per person, exact minute precision and 1970-2100
instants. Exclusive resource requests, other operations and unknown fact fields
are rejected, not silently stripped. Existing database query loading is reused;
these DTO budgets are not a new database-wide record quota.

## Read-only and concurrency guarantees

Every invocation owns a fresh session through `Database.transaction(read_only=True)`:
PostgreSQL `REPEATABLE READ, READ ONLY`, with ORM autoflush disabled throughout
authorization and data retrieval. No row locks or caller-owned dirty sessions are
accepted. New/dirty/deleted ORM objects abort the read; PostgreSQL also rejects
injected DML. Exceptions roll back and do not reveal SQL parameters or payloads.

A concurrent writer may commit without blocking this read. The projection sees
one coherent old revision/calendar, and the next projection sees the new state.
It is a point-in-time view, not a reservation or guarantee that data remains
current after return. Future live execution/confirmation must reauthorize and
respect the existing revision/concurrency protections.

## Verification and reproduction

Use only a disposable PostgreSQL database and the pinned application dependencies.
The tests reuse the existing owned-schema fixtures and real authentication
middleware. They do not start a web server or touch an operational database.

```text
python -B -m unittest discover -s research/cdmcs/i3b/tests -v
```

Set `TEST_DATABASE_URL` to the isolated test database, `PYTHONDONTWRITEBYTECODE=1`
and `PYTHONTZPATH` to an empty string for pinned tzdata. Configure the existing
authoritative backend for the few **test-only** production-engine comparisons;
the projection itself has no engine dependency or execution method. Without
PostgreSQL, integration tests explicitly skip and must not be reported as verified.

Coverage includes participant/permission boundaries, states, exceptions, DST,
midnight, legacy bindings, room cancellation, equipment deadline exclusion,
independent production validation, concurrent changes, rollback and query failure.
Read-only tests fingerprint all 53 application tables and identity sequences,
inspect PostgreSQL transaction settings and captured SQL, and block subprocess
launches while projecting.

### Executed verification: 29 October 2026

Windows, Python 3.12.14, GCC 14.3.0, PostgreSQL 17.11, pinned tzdata 2026.5.
The disposable cluster was loopback-only; each integration test owned a random
schema. No existing application database or original CSV dataset was used.
Verified implementation commit: `c28679c6a9a66e172032d2b1c0e1ea005a66730c`,
based on merged I3a main `73a90699dc91ea863bf8415e26ba1bdf408c8d22`.

| Check | Actual result |
|---|---|
| I3b tests | 43 passed, zero failed/skipped: nine pure contract tests and 34 PostgreSQL-backed tests |
| Existing I3a tests with both executables | 37 passed, zero failed/skipped; original 41/5/4 matrix and 469/391 counts retained |
| Fresh standalone I1 CMake C++17 `-O0` build | Both CTest suites passed: 618 differential cases, one unresolved-calendar case, 10 invalid inputs, and 25 safety tests including 84 independent horizon subcases |
| Existing complete application C++ suite | 192 passed, zero failed |
| Isolated standalone CSV CLI smokes | Both clean-slot and normal-dataset cases passed |
| Full application Python suite with PostgreSQL | 493 run: 492 passed, zero failed, one expected POSIX execute-permission skip on Windows |
| Schema documentation and migration head | 53 application tables match; Alembic head remains 0049b |

The full Python suite also exercised migrations/drift, real backup/restore,
concurrent reservations, all five allocation strategies, JSON/CSV compatibility,
Flask workflows, appointments, equipment, recurrence, feedback and waiting lists.
No Linux, hosted Windows/MSVC or new sanitizer execution is claimed for I3b.
No remote CI ran: this branch has not been published. Add the new I3b tests to
isolated PostgreSQL CI before publication; existing application discovery does
not automatically recurse into the research test directory.

An initial added equipment fixture attempted a future handover without freezing
its clock. The existing production rule correctly rejected it. The fixture now
uses the established explicit fictional pickup-time convention; no equipment
rule was changed. Final reruns above passed.

## Next-stage boundary

I3c should first establish a reviewed shadow-execution permission/data-retention
boundary and explicitly supplied research cost preferences. Keep fixed calendars,
no relocation or additional availability, no shared-resource equivalence, no
booking mutations, and sanitized results. New professor-organizer, administrative
delegation or committee initiation needs separate product authorization and, where
necessary, schema changes; this projection does not manufacture those capabilities.
