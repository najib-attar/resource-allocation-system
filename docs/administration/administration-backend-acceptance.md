# Administration backend acceptance — ADM-B5

**BACKEND VERIFIED for the approved, non-sensitive v1 scope.**
Reviewed baseline `aae966b`; administration code checkpoint `5f6af41`.
The commit introducing this report records backend acceptance before frontend work.

## Executed verification

All application modules were discovered with the existing unittest loader and
executed in four isolated subprocesses using the existing professor regression
runner, with its output redirected into ignored build storage. PostgreSQL 17 on
the new administration-only loopback cluster; uniquely owned schemas; rebuilt
GCC 14.3 C++17 backend. No operational database, original account or demo migrated.

| Execution | Run | Passed | Failures | Errors | Skips | Seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ADM-B1 academic/security | 77 | 77 | 0 | 0 | 0 | 500.218 |
| ADM-B2 operational | 187 | 187 | 0 | 0 | 0 | 1950.22 |
| ADM-B3 complete module | 11 | 11 | 0 | 0 | 0 | 136.12 |
| Subsequent history pagination | 2 | 2 | 0 | 0 | 0 | 25.36 |
| Subsequent date/ID boundaries | 2 | 2 | 0 | 0 | 0 | 19.97 |
| Full discovery, initial execution (57 modules) | 752 | 750 | 0 | 1 | 1 | 1610.98 |
| Complete corrected administration module on final backend code | 11 | 11 | 0 | 0 | 0 | 77.61 |
| Application C++ tests | 192 | 192 | 0 | 0 | 0 | — |
| Backend runtime smokes | 2 | 2 | 0 | 0 | 0 | — |

The initial full-run error was a synthetic feedback fixture attempting to report
before its later reservation began. The fixture clock was corrected; production
eligibility was preserved. The entire affected module was rerun, not just the
failed assertion. All other 56 modules passed. Thus all **752 distinct discovered
cases** have verified final outcomes: **751 passed, one expected platform skip**.
This is a reconciliation of the listed executions, not a claim that the initial
full command exited successfully. A fresh full run remains a final frontend gate.
The skip is `test_linux_execute_permission_is_checked`: POSIX permission checking
runs on Linux. No PostgreSQL, authorization or migration test was skipped.

Commands: `python -B -m unittest discover -s tests -p "test_*.py" -v` is the
canonical full discovery; grouped executions use
`python -B tests/professor/run_tests.py --child <label> <modules>`.
Parallel run evidence is under `build/administration/ADM-B5/` and
`build/professor-tests/ADM-B5/`; corrected module under
`build/professor-tests/administration/ADM-B5-correction/`.
C++ command: `powershell -ExecutionPolicy Bypass -File tests/run_tests.ps1`.

## Acceptance findings

- UC-04–10/12 existing authoritative services retained. New UC-01/11 read models
  are bounded and use read-only repeatable-read transactions, with current
  administrative capability and service-specific scope helpers.
- Current Eligible revisions alone reach guarded allocation snapshots and the
  real engine. Stale, tampered, rejected and unreviewed inputs are refused.
  Revision proofs, locks and atomic publication preserve active results on errors.
- Reviewing legacy eligibility does not change existing reservations; outstanding
  reviews block replacement. Active publication inputs remain read-only.
- Five-role, owner/foreign-user, current faculty/custodian, CSRF, retry/concurrency,
  private feedback/Inbox and durable logout regressions passed. Dashboard reads
  do not expose private appointment content or invoke the C++ engine.
- Resource decisions persist as the real source records. Room confirmation,
  equipment reservation, actual custody, verified returns and waiting-list
  preapproval remain separate; no new automatic reservation is introduced.
- No schema, migration, C++ source/protocol, strategy or research implementation
  changed. Existing 0051a/0051b fresh/legacy/rollback/recovery tests passed.
  Existing rollout still requires backup/review and matching worker restarts;
  this release adds no migration requirement beyond the verified current head.

## Scope and limitations

See [traceability](traceability.md), [B1](iterations/ADM-B1.md),
[B2](iterations/ADM-B2.md), [B3](iterations/ADM-B3.md) and
[sensitive deferrals](iterations/ADM-B4.md). Browser account administration,
unrestricted resource changes, PII exports, academic notifications, cancellation
and published version replacements remain deferred. Faculty approver replacement
may require organizer revision of an existing request; no override is added.

Files in this gate: this acceptance report and documentation links. No database
effects or screenshots for this backend-only gate. Conclusion: proceed to
Campus Space frontend implementation and real-browser acceptance.
