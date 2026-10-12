# Iteration 41 - PostgreSQL migration progress

## Scope

Replace operational CSV/config/result-file persistence for existing functionality
with PostgreSQL. Preserve C++ allocation behavior and JSON protocol v1. Do not
implement authentication, dated calendars or UC-STU-01 in this iteration.

## Baseline and Git

- Documentation PR #1 reviewed, both CI runs successful, merged as `b0aa19b`.
- Documentation follow-up commit: `dafefb9`.
- Implementation branch: `iteration/41-postgresql-migration`; local commits only.
- Existing untracked virtual environment and four generated CSV outputs protected.

## Milestones

| Milestone | State | Verification |
|---|---|---|
| Database design and ER diagram | Complete | Inspected current models, CSV data, JSON protocol, Flask persistence and adapters. |
| SQLAlchemy/psycopg/Alembic foundation | Complete | Fresh PostgreSQL 17.11 migration; seven foundation/configuration/constraint/rollback tests passed. |
| Validated CSV import/dry-run | Complete | Ten real-PostgreSQL tests passed: exact DTO round-trip, preserved order/IDs, dry-run, invalid input, rollback and refusal to overwrite. |
| Request persistence and configuration | Complete | Thread/process saves preserve distinct IDs and participant associations; lock timeout and worker termination tested. |
| Engine snapshots and transactional results | Complete | Twelve real-PostgreSQL workflow tests passed, including all five strategies, exact JSON round-trip, rollback, stale runs and coherent readers. |
| Web cutover | Complete | Database-backed dashboard, Save Only, Submit and Run, details, schedules, raw projections and strategy changes verified; file readers disabled in a regression test. |
| Final regression and report | Complete | 140 C++ passed; 112 Python passed, zero failed, one POSIX-only skip. Fresh database CLI migration/import and twelve Flask route checks passed; final documentation reviewed. |

## Decisions

- Use normalized records with immutable engine decision payloads for provenance.
- Use short state-row locks and optimistic revision checks, not a lock held during
  C++ computation. Stale results fail explicitly and never replace published data.
- Preserve weekly slots; defer date semantics to the separately approved calendar
  work. Do not invent organizational parents from CSV names.
- Retain legacy CSV CLI and explicit import/export; no operational CSV fallback.

## Verification record

Design commit: `2136153`; foundation commit: `245dfbc`; importer commit: `64f81da`; workflow commit: `68ec3e8`. Baseline: 140 C++ passed, two isolated CLI smoke scenarios
passed; Python 74 total, 73 passed, one POSIX-only skip on Windows. Foundation:
`python -m unittest discover -s tests -p test_postgres_foundation.py -v`, real
PostgreSQL 17.11: seven passed. Import:
`python -m unittest discover -s tests -p test_postgres_import.py -v`: ten passed.
These were milestone checks; the final complete-suite results are recorded below.

Workflow: `python -m unittest discover -s tests -p test_postgres_workflow.py -v`:
twelve passed on Windows against PostgreSQL 17.11. No existing application data
was imported into or overwritten in a production database; verification uses
new, randomly named test schemas only.

Web cutover verification: full Python suite with real PostgreSQL: 111 total,
110 passed, zero failed, one POSIX-only permission skip on Windows. Ported the
existing storage-facing regressions instead of leaving a CSV web test mode.
Offline CSV CLI/parser/recovery tests remain. All five strategies produce exact
equivalent results through original CSV snapshots and database snapshots, including
structured suggestions and normalized result round-trips.

Web cutover commit: `76350be`. Final review added safe malformed-URL handling and
a real-engine regression for form-created recurring occurrences. Foundation now
has eight passing tests; Save Only/confirmation has ten passing tests. Final full
Python run: 113 total, 112 passed, zero failed, one POSIX-only skip on Windows.
The freshly compiled C++ runner remains 140 passed, zero failed; both isolated
CLI smoke scenarios passed. Dependency checks and Python compilation passed.

A newly created disposable database was migrated to head, imported through the
actual CLI, checked with `alembic check` (no schema drift), and exercised with the
real engine plus twelve Flask GET smoke routes. No production/existing database
was overwritten. All four protected generated CSV SHA-256 values are unchanged.

## Local implementation commits

| Commit | Milestone |
|---|---|
| `2136153` | Database design, ER diagram and migration plan. |
| `245dfbc` | PostgreSQL models, migrations and integration test foundation. |
| `64f81da` | Safe CSV import with preserved IDs/order and dry-run. |
| `68ec3e8` | Transactional allocation runs and publication. |
| `76350be` | Existing web workflows cut over to PostgreSQL. |
| `cb95f5c` | Connection validation and recurring form persistence regression. |

Final living documentation and this verification record are committed separately.
No implementation commit has been pushed or merged; publication requires approval.

## Remaining limitations

The updated Linux CI job is configured but not remotely executed on this
unpublished branch. Local verification used Windows and real PostgreSQL 17.11.
Authentication, dated appointment scheduling and UC-STU-01 remain outside scope.
HTTP retry idempotency and automatic abandoned-run/retention cleanup are not added.
Original generated results stay offline and must be regenerated for PostgreSQL.
See [operations](../database-operations.md) for setup, failure semantics and backups.

## Database foundation review follow-up

The initial cutover is complete; the requested comprehensive foundation review
is in progress. No new feature iteration or additional tables are introduced.

- Reproduced missing ordinal constraints, duplicate decision ordering, missing
  reverse-FK lookup indexes and acceptance of inconsistent allocation projections.
- Added additive revision `0041b`: validates existing order/score data, adds six
  lookup indexes and two ordering uniqueness constraints. An invalid existing
  database fails the transactional upgrade instead of being silently repaired.
- Publication/read-back now verify allocation totals and resource metadata against
  the captured snapshot; no C++ scheduling rules are duplicated.
- Seven new quality regressions passed; the complete PostgreSQL group passed
  45 tests on real PostgreSQL 17.11. All five strategies retain exact round-trip.
- Next: complete schema inventory/ER sources, demo seeding, runtime CSV cleanup,
  isolated backup/restore verification and full final regression.

Demo seeding uses deterministic fictional inputs (default seed 41): 106 users,
20 resources, 120 requests, 12 busy slots and six supported faculty/department
units. Large mode scales inputs tenfold. Four demo tests passed, including all five
real strategies and refusal to overwrite. No reset option or pre-approved fake
allocations exist. Shared initialization is one validated empty-target transaction;
CSV import still uses the same safeguards. Malformed metadata receives explicit
validation errors rather than incidental Python attribute errors.
