# PostgreSQL Runtime and Legacy Cleanup

## Scope and Evidence

Iteration 41 maintenance preserves PostgreSQL tables/migrations, allocation rules,
all five strategies, JSON protocol v1, routes and templates. No new persistence
technology or domain behavior is introduced. References, imports, route calls and
test consumers were checked before removal; Python AST inspection supplements
these checks but is not a proof that every possible public API is obsolete.

```text
Flask -> Repository -> coherent PostgreSQL snapshot
      -> EngineGateway -> C++ --json -> transactional PostgreSQL publication
      -> DatabaseResultAdapter -> in-memory projections -> BackendResultAdapter -> templates

Explicit offline import: CsvInputs -> validated DTOs -> empty PostgreSQL database
Standalone compatibility: C++ no-argument CLI -> CSV loaders/writers
```

## Removed or Isolated

| Component | Previous callers | Cleanup |
|---|---|---|
| Adapter CSV/text readers and offline `pin` | Retired file adapters, parity fixtures; PG subclass overrode readers | Removed; runtime uses logical `get_table`/`count_records` views. |
| Lifecycle-history suggestion parser | Offline parity and fallback presentation | Removed from runtime; legacy CLI comparison parser retained only in `tests/csv_cli_fixtures.py`. |
| Gateway CSV snapshot/boolean conversion | Explicit importer and parity tests | Moved into importer; gateway only validates/invokes JSON. |
| Form/CSV integer and slot parsers | Flask forms and importer | Shared `input_validation.py`, named `parse_time_slots`; form encoding is not persistence. |
| Request validation in importer | Database saves, demo/import tools | Shared `persistence/validation.py`; normal request saving no longer imports CSV machinery. |
| Duplicate scalar projection | Input and result adapters | One `table_view` projection helper; template columns/formatting unchanged. |
| CSV header constants in Flask | Test fixture writers only | Removed; offline fixtures use explicit presentation column definitions. |
| Duplicate request-type labels | Flask and presentation | One presentation definition reused by Flask. |
| `legacy_shared_file_state.py`, `legacy_result_adapter.py` | Retired test-only lock/journal/result publication | Deleted, not relocated into another framework. |
| `legacy_csv_fixtures.py` | CLI smoke plus retired recovery tests | Replaced with focused `csv_cli_fixtures.py`; workspace/lock dependencies removed. |
| Unused imports | No expression/decorator consumers | Removed from adapters and relevant test modules. |

Raw Data selectors such as `file=requests.csv` and `file=config.txt` intentionally
remain for existing bookmarks and labels. They map to memory/SQL projections only;
invalid names still select the safe default. Existing template column keys and
weekly form time syntax are retained to avoid an unnecessary frontend rewrite.

## Test Inventory

| Category | Retained test files/responsibility |
|---|---|
| Current Flask functionality | `test_save_only_confirmation.py`, `test_backend_executable.py` web smoke, `test_postgres_web.py`, `test_postgres_text_contract.py`. |
| PG persistence/concurrency | `test_postgres_foundation.py`, `test_postgres_import.py`, `test_postgres_workflow.py`, `test_postgres_concurrency.py`, `test_postgres_quality.py`, `test_postgres_completion.py`. |
| PG demo/recovery/schema | `test_postgres_demo.py`, `test_postgres_recovery.py`, `test_database_diagrams.py`, Alembic drift/upgrade tests. |
| JSON execution | `test_engine_gateway.py`, `test_json_engine.cpp`, authoritative executable validation tests. |
| CSV import compatibility | `test_postgres_import.py` validates IDs, ordering, foreign keys, dry-run/refusal, malformed input and strategy defaults. |
| Standalone CSV compatibility | `test_csv_contract.py` (three Python-writer/C++ quoting regressions), `test_csv_cli.py`, `csv_cli_fixtures.py`, C++ CSV reader/loader/session/integration tests. |
| Runtime independence | `test_persistence_boundaries.py`, `test_postgres_runtime_independence.py`, runtime IO guard used by other web tests. |
| C++ allocation/domain | All existing unit/rule/strategy/factory/service/availability/committee/suggestion/session/integration/runtime tests preserved unchanged. |

`test_shared_file_concurrency.py` is renamed `test_postgres_concurrency.py`; its
15 database regressions remain. The PostgreSQL Unicode submit test moves out of
`test_csv_contract.py` into `test_postgres_text_contract.py`. Standalone CLI smoke
moves into `test_csv_cli.py`. All meaningful coverage is retained.

Four tests are deliberately removed: old OS-file-lock release, file-save journal
crash recovery, orphan CSV generation workspace, and local JSON-file publication.
Their mechanisms are no longer shipped or supported; PostgreSQL lock release on
worker termination, transactional saves/rollback, stale-run rejection, failed-run
preservation and pinned views cover the current implementation instead.

The new guard intercepts both Python file opens and CSV readers/writers. Tests
exercise all views, Save Only, Submit and Run, configuration, structured results,
restart in a new process with an empty working directory and a real refused
PostgreSQL connection. No fallback result files can be accessed during these checks.

## Intentionally Retained

- C++ CSV loaders, writers, `CsvReader`, console helpers and both session export
  overloads are reachable through standalone CLI or supported unit/integration APIs.
- `scripts/import_csv.py`, `CsvInputs` and fictional demo initialization remain
  explicit, validated, non-destructive setup tools, never runtime fallbacks.
- Original `data/` inputs and `tests/fixtures/` are import/parity/CLI data; generated
  local output files are not deleted, overwritten by tests or committed.
- Older iteration reports and diagrams describe historical designs and remain intact.
- Public C++ role/organization model classes are documented domain APIs, although
  JSON allocation uses role/unit labels rather than instantiating that hierarchy.
  No production call site alone is insufficient evidence to delete these public
  models in a persistence cleanup; any API retirement needs a separate domain review.
- Flask routes/forms and weekly schedule formatting remain together. Large route
  decomposition or renaming every template column is outside this cleanup.

The CI workflow filename is now `backend-postgresql-regression.yml`; its PostgreSQL
service and test commands are unchanged. Exact executed results and platform skips
are recorded in [Iteration 41 progress](../iteration-reports/Iteration_41_progress.md).
