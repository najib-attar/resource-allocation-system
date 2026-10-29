# I3b: authorized read-only calendar projection

This experimental Python module reads existing application calendars into I3a's
immutable `Snapshot` DTO. It registers no routes, selects no scheduler, launches
no engine, and creates no bookings, approvals, permissions or background work.
The existing appointment scheduler remains the default.

## Architecture and reuse

```text
Authenticated Flask request (signed session, g.principal, pinned database URL)
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
  snapshot. It rejects pending ORM changes and refreshes cached identity objects
  inside that transaction, without flushing, committing or rolling it back.
- [security.py](../../../web/security.py) pins the successful authentication
  database's immutable URL in server-side request state. Projection checks both
  its database and actual session binding against it, including configured schema
  options. This metadata is never serialized or logged; it may contain credentials.
  No route, role grant, password-verification rule or CSRF behavior changes.
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
Identical user/role/session fields in a different database or configured schema
do not establish authentication there. Separate connection pools for the same
configured authority remain supported. Database/session construction and request
middleware are trusted server code, not client-supplied authorization tokens.

These restrictions deliberately stop unsupported paths rather than inventing new
roles or permissions. There is no new public endpoint for obtaining these objects.
`for_selection` accepts an explicit bounded search horizon; it does not itself
apply the existing `/appointments/times` route's current-time lower bound. A
future shadow caller must preserve that route's exact authorized selections and
horizon. This is not a new grant to expose arbitrary historical or future private
free/busy calendars.

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
Missing and unrelated appointment IDs receive the same private denial. Wrapped
database-busy errors and SQLAlchemy failures have static messages with suppressed
causal tracebacks. Diagnostic systems must still not capture raw snapshot data,
request-local credentials, exception contexts or frame locals.

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
No remote CI ran: this branch has not been published. At that checkpoint, I3b
tests were not in CI. The following I3b.5 review adds that coverage because
application discovery does not recurse into research tests.

An initial added equipment fixture attempted a future handover without freezing
its clock. The existing production rule correctly rejected it. The fixture now
uses the established explicit fictional pickup-time convention; no equipment
rule was changed. Final reruns above passed.

### I3b.5 security and CI review

The review reproduced and corrected four internal-boundary weaknesses; none was
connected to a live projection route:

| Finding | Correction and regression |
|---|---|
| Caller-owned identity sessions could autoflush pending edits or reuse stale account/user/role objects | Deny pending ORM work; disable autoflush; refresh persisted identity in the supplied transaction. Eight application tests verify ownership, revocation, inactivation, role freshness and repeatable-read behavior. |
| Matching principal fields did not bind projection to the authentication database | Middleware pins the authority; the projection verifies database and session URLs before calendar retrieval. Tests cover matching identities in another schema, same-authority connection pools and a misbound session. |
| Unknown and unrelated appointment IDs had distinguishable error classes | One static permission denial for inaccessible records; no new visibility grant. |
| A wrapped database-lock exception could retain SQL parameters in its printed cause | Sanitize wrapped busy and SQLAlchemy errors; regression verifies sensitive synthetic parameters are absent from default formatted tracebacks. |

The PostgreSQL workflow now contains a separate disposable-container projection
job. It requires both research and identity test groups, zero skips, bounded
execution, 3 GiB/2 CPU application and 1 GiB/2 CPU database limits, and no calendar
artifact upload. Existing application/PostgreSQL regressions remain enabled.
I3b and authentication/calendar changes also trigger the existing I3a offline,
standalone Release and ASan/UBSan jobs. These jobs have no deployment steps.
Workflow linting or Windows runs do not establish hosted Linux/sanitizer success;
remote CI requires separately authorized publication.

Fresh local verification for I3b.5 used the same Windows/Python/GCC/PostgreSQL
versions listed above, new disposable databases and synthetic records only:

| Check | Actual I3b.5 result |
|---|---|
| Projection contract and PostgreSQL tests | 47 passed, zero failed/skipped: nine pure and 38 PostgreSQL tests |
| Identity-session regressions | Eight passed; combined CI-equivalent projection/identity gate: 55 passed, zero skipped |
| I3a with both native engines | 37 passed, zero skipped; 41 complete equality cases, 469 candidates and 391 feasible per engine, five unsupported cases and four invalid inputs |
| Standalone CDMCS C++17 | Fresh `-O0` and Release builds; both CTest suites passed in each configuration, with the original differential, safety and independent horizon coverage |
| Complete application C++ | 192 passed, zero failed; both standalone CSV CLI smokes passed |
| Complete application Python/PostgreSQL | 501 run: 500 passed, zero failed, one expected POSIX execute-permission skip on Windows |
| External production executable/manifest | Fresh build outside the checkout; all four engine-using projection regressions passed with the configured override |
| Schema and migrations | All 53 tables match documentation; fresh disposable-database upgrade to 0049b and no Alembic drift |
| CI static verification | Both workflows pass actionlint; 15 Bash blocks, two embedded Python programs and changed Python sources pass syntax checks |

No original projection test was retired. Only the connection-failure fixture
changed: it now injects an outage on the authenticated database, since a foreign
database is deliberately denied before calendar reads.

Remaining boundaries: only existing student selections and tightly scoped
appointment review are authorized; optional invitees never become mandatory.
Opaque busy intervals remain private data, not anonymized public evidence.
Repeatable-read authorization is point-in-time: a later revocation is observed by
the next read, not retroactively by an already established snapshot. No new
preferences, delegation permissions, resource semantics or migrations are added.
DTO limits (32 days, 101 required/100 optional participants, 10,000 busy rows,
100,000 publication rows and 1,024 windows per person) apply after calendar
retrieval. The existing read-only database context does not impose a SQL statement
deadline. CI budgets are not live request admission control; future live shadow
execution must review query/execution budgets before exposure.

## Next-stage boundary

I3c should first establish a reviewed shadow-execution permission/data-retention
boundary and explicitly supplied research cost preferences. Keep fixed calendars,
no relocation or additional availability, no shared-resource equivalence, no
booking mutations, and sanitized results. New professor-organizer, administrative
delegation or committee initiation needs separate product authorization and, where
necessary, schema changes; this projection does not manufacture those capabilities.
