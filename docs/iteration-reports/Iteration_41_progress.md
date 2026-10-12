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
| Final regression and report | Pending | Full C++/Python/PostgreSQL tests, integrity and security review required. |

## Decisions

- Use normalized records with immutable engine decision payloads for provenance.
- Use short state-row locks and optimistic revision checks, not a lock held during
  C++ computation. Stale results fail explicitly and never replace published data.
- Preserve weekly slots; defer date semantics to the separately approved calendar
  work. Do not invent organizational parents from CSV names.
- Retain legacy CSV CLI and explicit import/export; no operational CSV fallback.

## Remaining work

Design commit: `2136153`; foundation commit: `245dfbc`; importer commit: `64f81da`; workflow commit: `68ec3e8`. Baseline: 140 C++ passed, two isolated CLI smoke scenarios
passed; Python 74 total, 73 passed, one POSIX-only skip on Windows. Foundation:
`python -m unittest discover -s tests -p test_postgres_foundation.py -v`, real
PostgreSQL 17.11: seven passed. Import:
`python -m unittest discover -s tests -p test_postgres_import.py -v`: ten passed.
Remaining implementation milestones are above.

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
