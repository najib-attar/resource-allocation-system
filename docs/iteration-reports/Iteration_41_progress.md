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
| SQLAlchemy/psycopg/Alembic foundation | Pending | Real PostgreSQL migration and rollback tests required. |
| Validated CSV import/dry-run | Pending | Ordering, IDs, metadata and reference tests required. |
| Request persistence and configuration | Pending | Concurrent creation and atomic save tests required. |
| Engine snapshots and transactional results | Pending | Five-strategy parity, stale/failed publication tests required. |
| Web cutover | Pending | Existing routes must work without operational CSV/result files. |
| Final regression and report | Pending | Full C++/Python/PostgreSQL tests, integrity and security review required. |

## Decisions

- Use normalized records with immutable engine decision payloads for provenance.
- Use short state-row locks and optimistic revision checks, not a lock held during
  C++ computation. Stale results fail explicitly and never replace published data.
- Preserve weekly slots; defer date semantics to the separately approved calendar
  work. Do not invent organizational parents from CSV names.
- Retain legacy CSV CLI and explicit import/export; no operational CSV fallback.

## Remaining work

All implementation and fresh-database verification remain outstanding. Update
this document with actual commands/results and milestone commit references.
