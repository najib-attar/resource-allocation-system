# ADM-UI-06 — Independent integration and cross-role acceptance

Code checkpoints: `fdeaba6` (independent pipeline), `d6919cb` (retained browser
expectations), `ddcdb40` (shared unchanged legacy predicate), `04b1270` (retry
guidance/landing contract), `b6c9c78` (configuration-control persistence audit).
The final documentation commit introduces this report and representative images.

## Reviewed implementation

Reviewed the complete administration diff against `aae966b`, all twelve approved
contracts, current route/service/model/engine boundaries and shared-role templates.
The [control matrix](../integration-verification.md) connects each supported control
family to parameters, authority, source persistence, result and verification.
No alternate scheduling engine, schema, dependency or permission was introduced.

New verification uses actual Flask/Edge, owned PostgreSQL schemas and independent
committed reads before/after POSTs. Run snapshot request IDs are compared against
current eligible revisions. Existing valid tests remain; only administrator landing
and navigation assertions changed to match the intentionally new workspace.

## Exact executions

| Verification | Result |
| --- | --- |
| Fresh final full Python/PostgreSQL | 763 run: 762 passed, zero failures/errors, one expected Windows POSIX-permission skip; 1377.70s |
| Focused final concurrency/dashboard/failure modules | 48/48 passed, 173.41s; zero failures/errors/skips |
| Shared legacy predicate, migrations and dashboard | 25/25 passed, 221.29s; zero failures/errors/skips |
| Corrected retained prototype module | 8/8 passed, 44.83s; zero failures/errors/skips |
| C++ application suite | 192 passed, zero failed |
| Real engine runtime smokes | 2 passed: clean-slot and normal-dataset |
| Independent academic pipeline browser | 50 width/page observations, 730 keyboard steps; 18 POSTs, 12 verified non-login outcomes |
| Additional configuration browser | 15 observations, 330 keyboard steps; 15 POSTs, 14 verified non-login outcomes |
| Retained Professor independent browser | 200 observations, 2629 keyboard steps; 32 POSTs, 20 persisted outcomes |
| Retained Student lifecycle browser | 67 POSTs: 62 successful, 5 expected rejected; every operation independently verified |
| Legacy eligibility browser after extraction | 28 POSTs, 21 verified outcomes, one real-engine replacement |
| All-five-role logout browser | Five durable logout denials; zero rejected mutations persisted; account versions unchanged |
| Academic workspace final replay | 50 observations, 369 keyboard steps; 6 POSTs, 4 verified non-login outcomes |
| Calendar/waiting/issues final replay | 60 observations, 1173 keyboard steps; 16 POSTs, 11 verified non-login outcomes |
| Reports/Inbox final replay | 40 observations, 280 keyboard steps; 9 POSTs, 4 verified non-login outcomes |
| Generated schema catalog check | All 62 application tables match |

Browser observations use 1440/1024/768/390/320px. Final successful runs have zero
unexpected console/HTTP errors or document overflow. Expected invalid, unauthorized,
missing and stale responses are retained separately. Keyboard walks, labels,
headings, focus, primary navigation and relevant menus were checked. Owned browser
schemas were proved absent and Flask servers stopped after each run.

## Defects and corrections

- Earlier frontend checks found duplicate Student/Admin Home headings, expanded
  navigation covering mobile approval controls and intrinsic grid overflow on
  populated tablet results. The focused frontend commits corrected these and
  reran their complete affected browser phases.
- The independent audit found stale test assertions for the old administrator
  landing page/navigation. Assertions now require the new authorized destination;
  authority, CSRF and source-state assertions remain intact.
- Broad final discovery found the new safe 503 page had omitted the existing
  retry guidance. The message now explicitly says retry; the original status,
  Retry-After header and unchanged database assertions pass.
- Shared legacy review summaries and enforcement now use one query. Compiled
  enforcement SQL was confirmed byte-for-byte identical; a new real PostgreSQL
  test verifies the count before/after rejection while preserving active results.
  A temporary extraction syntax error was fixed before the successful focused run.
- Browser state capture now covers room configuration, equipment types/conditions,
  custodian replacement, recurring limits and justified priorities. Every successful
  mutation has a specific committed-state assertion; rejected operations are unchanged.

An earlier broad attempt aborted during the temporary import error. The next full
execution ran 763 cases: 760 passed, two failures, one expected Windows platform
skip, 1304.31s. Those two failures were the stale landing assertion and retry-copy
defect described above. These attempts are not represented as successful runs.
The fresh final result in the table is the acceptance gate.

## Effects, cleanup and limits

Only the dedicated test cluster and uniquely owned fixture schemas were used.
No operational migrations, original accounts/passwords, demonstrations or current
published application data were modified. No files or useful regression tests were
deleted. One unreachable legacy administrator navigation block, ineffective CSS
selector use and temporary harness debugging were removed; Staff/TA compatibility
styles and templates remain. Six representative PNGs total 622,056 bytes; raw
logs/state dumps remain ignored under `build/administration/`.

Sensitive extensions and previously deferred academic features remain deferred
as listed in [ADM-B4](ADM-B4.md). Final conclusion and hosted-check status are in
the [acceptance report](../acceptance-report.md). Publication is Draft PR only.
