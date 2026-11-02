# Institutional numerical policy foundation and internal governance (0050b)

The schema installs empty ledgers and a pure value contract. An explicitly invoked
internal service now supports authenticated governance; there are no public routes,
UI, authority-assignment commands or optimizer consumers. Installing the schema or
importing the service grants nobody authority and activates no policy. Personal
preferences, published availability and existing bookings are unchanged. The
existing production appointment scheduler remains the default.

## Values and mathematical compatibility

`web/cost_policy_values.py` provides immutable `CostCoefficients` and
`InstitutionalCostPolicy` values. `parse_institutional_policy(document,
university_timezone=..., expected_digest=...)` validates values, not an actor.
The trusted caller must supply the configured university timezone; an
arbitrary caller-supplied timezone is not university configuration.

Every field is required; unknown fields and numerical defaults are rejected:

| Field | Version 1 contract |
|---|---|
| policy_contract_version / objective_version | Exact integer 1 |
| origin / policy_id | `institutional_policy` / `university` |
| revision | Positive signed-64 integer |
| engine_operation | `cdmcs_schedule_v1` |
| objective_model | `V15_restricted_one_blocking_move` |
| rate_model | `weekday_window_tiers_v1` |
| timezone | Valid IANA name, exactly matching explicitly supplied university configuration |
| effective | `from` / `until`: aware ISO timestamps with valid offset components, half-open UTC interval, 1970 through 2099; microseconds at most, no rounding |
| cost_unit / calibration_ref | Nonblank bounded UTF-8 declarations, not inferred units or an optimality claim |
| provenance | Exactly `type: institutional_policy` and bounded `source_ref` |
| coefficients | All nine exact integer values listed below |

Minute rates are 0-100000000, ordered `preferred_rate <= outside_window_rate <=
outside_day_rate`. `gap_weight` is 0-100000; `nearby_limit` is 0-10080 minutes.
`exception_fee`, `move_fixed_cost`, `move_participant_cost`, `delay_per_day` are
0-10000000. Explicit zero is valid, not missing. Booleans, floats, infinities,
unknown versions, duplicate JSON keys and overflow are rejected. Input bytes use
the existing 4 MiB/depth-bounded JSON reader. Text declarations are at most 256
UTF-8 bytes and contain no ASCII control characters.

Only the pure coefficient validator is shared with D1. Its synthetic envelope and
provenance guards remain separate and unchanged. Institutional documents cannot
be parsed as D1 synthetic policies. No institutional-to-synthetic exporter exists.

The original objective stays `(total cost, maximum positive net personal burden,
start, moved ID, replacement start)`. One minute-rate tier applies, not additive
weekday/hour penalties. Adjacent gap cost is absolute deviation from the person's
desired gap, only within the cutoff and when both event starts share a local date.
It is not a mandatory break. Net calendar changes may be negative. Fixed move and
global day-delay charges are outside individual fairness. See the authoritative
[D1 mapping](../../research/cdmcs/i3d/d1/README.md#exact-mathematical-mapping).

The prefix total remains bounded by 10^12. The existing full-engine conservative
signed-cost bound is 43720003072000000 < INT64_MAX; D1's domain is stricter.
Accepted coefficients do not guarantee that any particular calendar is feasible
or fits prefix, context, time or memory budgets. Neither engine changed. D2's
global delay reference, original candidates and complete neighbor context remain
mandatory; a cost policy never changes hard availability or permissions.

## Canonical integrity

The digest is SHA-256 of UTF-8 JSON for this fixed scalar-array order, with
`, ` item separators and non-ASCII characters emitted directly:

```text
[contract_version, provenance_type, policy_id, revision, objective_version,
 engine_operation, objective_model, rate_model, timezone,
 effective_from_UTC_epoch_microseconds, effective_until_UTC_epoch_microseconds,
 cost_unit, calibration_ref, provenance_type, provenance_ref,
 preferred_rate, outside_window_rate, outside_day_rate, gap_weight, nearby_limit,
 exception_fee, move_fixed_cost, move_participant_cost, delay_per_day]
```

This is a versioned wire-independent canonicalization, not canonical JSON for
arbitrary documents. Python uses exact timedelta arithmetic; PostgreSQL uses
exact numeric epoch extraction, `jsonb_build_array`, `convert_to` and built-in
SHA-256, with no new extension. A BEFORE INSERT trigger rejects incorrect digests.
Equivalent timestamp offsets and object-key order give the same digest. Actor and
server-time metadata are recorded separately, not assertions authenticated by a
content hash. A digest is not approval, a signature or evidence of calibration.
Text is hashed exactly as supplied: there is no implicit Unicode normalization,
case folding or trimming. Composed and decomposed spellings therefore differ.
The SQL text guard uses the same explicit ASCII control set as the pure contract,
not a locale-dependent character class. A privileged database owner can bypass
guards or replace both content and digest; the hash is not tamper-proof custody.

## Four distinct records

| Table | Responsibility |
|---|---|
| scheduling_cost_policy_revision | Immutable numerical proposal content/digest, versions, dates, timezone, calibration reference and explicit proposer/grant association |
| scheduling_cost_policy_event | Immutable decisions and activation/deactivation associations, actor/grant reference, head version, reason and server timestamp; no coefficient copies |
| scheduling_cost_policy_head | Optional singleton version and active activation-event pointer; no row is seeded, and null/missing never selects an older policy |
| scheduling_cost_policy_authority_revision | Immutable named propose/approve/audit grants and revocations, responsible actor and institutional authorization reference |

The revision already records proposal identity/time; a duplicate submission event
is unnecessary. Collapsing content and events duplicates coefficients or loses
immutable decisions. Reusing allocation state would couple unrelated locks and
untyped JSON. An authority ledger is needed because no current role establishes
institutional cost-policy authority. No generic permission framework is added.

FKs reference retained university identities with RESTRICT, not replaceable login
rows. Typed numerical constraints, version/model identifiers, finite effective
intervals, string budgets, explicit provenance and positive revisions are enforced
in PostgreSQL. Server triggers stamp creation/update times. Referenced grants must
be grant records, approval actors differ from proposers, activation references an
approval for the same revision, and deactivation references its activation.

One head permits at most one current active pointer. Updates must increment its
version exactly once; deletion/truncation cannot reset it. The three histories
reject update/delete/truncate. Integrity functions use `pg_catalog`, their owned
schema, then explicit `pg_temp` last; temporary or caller search-path tables cannot
replace their authoritative relation checks. Current and historical grant identity
is NOT proof of a currently authorized human action; these constraints are
structural, not the B2 authorization service.

## Migration, rollback and erasure

0050b follows 0050a and creates four empty tables and their integrity guards. It
does not seed coefficients, policies, heads or grants. Downgrade acquires all four
ACCESS EXCLUSIVE locks in child-to-parent order before checking any table. Any
populated table blocks downgrade, including an initialized head. An empty rollback
preserves existing personal preferences, users and bookings. PostgreSQL dump/restore
tests also include populated synthetic policy content and its exact digest.

Normal application SQL cannot erase history. This is not an irreversible erasure
prohibition: an appropriately authorized database owner can perform a separately
reviewed transactional procedure. No erasure mechanism, retention period or
authority bootstrap is supplied here. Non-owner application credentials and
private database/application logging remain operational prerequisites. The
inherited account-lifecycle security limitation must be fixed before rollout;
technical security findings are maintained in restricted review materials.
Application credentials must not own tables, have superuser privileges, alter
triggers/functions or create objects in trusted schemas. Migration/erasure
ownership must be separated from normal application access. Authorized erasure
requires an approved retention decision covering dependent history, audit and
backups, not merely a digest change or an application DELETE permission.

## D3-C-B2 internal service

`CostPolicyService(database, university_timezone=...)` in
`web/cost_policy_service.py` reuses the pure parser, existing `AccountService`
identity checks and owned `Database` transactions. It does not import either engine
or read private preferences/calendars. No new schema, permission framework, grant
assignment operation or automatic activation is introduced.

| Operation | Explicit current capability | Inputs beyond trusted context |
|---|---|---|
| propose | propose | expected_head_version, complete institutional document with next revision |
| approve / reject | approve | expected_head_version, revision, digest, mandatory reason |
| activate / deactivate | approve | expected_head_version, revision, digest, mandatory reason |
| current | audit | none |
| history | audit | limit (1-100, default 20), optional exclusive before_revision cursor |

Every application role has the same deny-by-default behavior. A write capability
does not implicitly grant `audit`; intended capability combinations require
institutional authorization. There is no caller-supplied actor ID. The trusted
server principal, signed-session identity/generation and middleware database URL
must agree with fresh same-session account/user records. Disabled, inactive, stale,
forged, cross-database/schema and dirty-session contexts are rejected. The service
pins the configured schema ahead of temporary objects before authoritative SQL.

The authority selector chooses the highest revision whose `effective_from` has
begun, then requires `Granted` and `from <= now < until`. It never falls back after
a selected revocation/expiry. Future revisions do not take effect early. A
nonblank bounded institutional authorization reference is required, but is not a
signature or an authority bootstrap. Restricted database custody and an approved
assignment process are prerequisites for real grants; only disposable fixtures
create grants in verification.

The per-policy state machine is strictly:

```text
Proposed -> Approved -> Activated -> Deactivated
         -> Rejected
```

The proposer cannot approve their own revision. Approval does not change the
active pointer. Activation checks the exact immutable revision/digest and its
half-open effective interval, and requires an empty active pointer. Replacement
therefore requires an explicit deactivation, including when the prior policy has
expired. Rejected/deactivated revisions are terminal; a further policy requires a
new proposal and approval. Dates, coefficients and provenance cannot be edited.

Every successful write increments the global head exactly once. The proposal
itself records its proposer/grant/time; decisions add immutable events, pinned by
FK to the complete revision and its verified digest. The event, head and pointer
commit together. Decision receipts contain head version, revision, digest, status
and optional event ID. The schema does not store a proposal's historical head
version; history reports the read snapshot's head version separately rather than
inventing that information.

`current()` returns a policy only for the exact current, effective, supported and
integrity-checked activation. Missing, deactivated, expired, not-effective,
unsupported or unknown state returns no policy, never older or zero-cost values.
Contradictory active pointers/event chains fail closed. The global activation
stream must alternate activation/deactivation with matching predecessor IDs, even
across revisions and after all activations have closed. A SQL window checks this
metadata without loading the entire ledger into Python; its database work grows
with activation history, independently of the bounded page size.
`history()` returns newest
revisions with immutable policy content, status, proposer/grant/time and bounded
decision tuples `(id, type, actor, authority_revision, head_version, timestamp,
reason, predecessor)`. At most 101 revisions and four events per returned revision
are read; a legal chain has at most three events. A corrupt page raises rather than
returning a partial successful history. These internal values are not a research
export or user-visible API. Their representations withhold contents. Calibration
and provenance references are internal declarations, not fetched evidence. Audit
readers may inspect those references and decision actors/reasons, not other users'
personal preferences or calendars. Any future public explanation of approved
coefficients requires a separately approved sanitized representation, not these
complete internal views. There is no such public route or serializer here.
`audit` is an explicit read capability, not a new access-log or retention service:
these read-only operations do not append governance decision events. Operational
access logging and its retention still require approved private logging controls.

### Transactions and concurrent authority changes

Writers require the existing READ COMMITTED transaction and use consistent order.
The service explicitly checks the actual isolation before any head initialization;
a changed server/engine default of REPEATABLE READ or SERIALIZABLE fails closed.
It also rejects actual DBAPI autocommit and verifies read-write mode. A logical
SQLAlchemy transaction and a READ COMMITTED report alone do not prove atomicity:
an autocommit connection can commit initialization before a later denial.
Merely waiting for the authority lock under an older transaction snapshot is not
enough to observe a newly committed revocation. This guard does not change global
database configuration or the supported coherent read-only snapshot behavior.

1. Initialize an absent head with `INSERT ... ON CONFLICT DO NOTHING`, then lock
   the singleton `FOR UPDATE`. Initialization and all writes roll back on denial.
2. Lock the authority table in `SHARE` mode, then lock the actor's login account
   for update and university user for share. The table lock also blocks raw
   authority inserts that do not take the head lock. No authority is modified.
3. Revalidate identity and the current capability using the database clock. Check
   the expected head, numerical bounds, full policy digest and lifecycle. Flush
   the event before updating the active pointer, without an intermediate head
   update that would break B1's exact-increment guard.
4. Flush all changes; recheck authority revision/validity and any newly activated
   policy's interval before commit. Failure discards the entire transaction.

If revocation insertion holds its lock first, a decision waits and observes the
committed revocation. If a decision holds `SHARE` first, it linearizes before
revocation; subsequent calls are denied. The lock deliberately covers all
authority inserts, not just the actor's capability. This small administrative
workload favors conservative integrity over concurrent grant throughput.
Future authority-management operations must follow head-first ordering; arbitrary
opposite-order SQL can deadlock. PostgreSQL detects/rolls back the victim, and the
service returns a sanitized storage failure, with no automatic replay. Existing
configurable lock timeout bounds waits (default five seconds). Clients refresh
versions and explicitly retry; stale decisions are never silently reapplied.

Readers require actual non-autocommit REPEATABLE READ, READ ONLY transactions,
with no autoflush and fresh identity checks. The early database clock query returns
`transaction_timestamp()` and `clock_timestamp()`, enclosing the transaction's
snapshot acquisition. The same Granted authority revision must be valid at both
endpoints. This ensures the identity and grant have a coherent authorized snapshot
instant, instead of combining an earlier valid session with a later-starting grant.
`statement_timestamp()` is not a sufficient lower bound because protocol
preparation can acquire a snapshot before Execute resets that timestamp.
If authority changes or begins/expires across the interval, the read fails closed;
the caller may start a fresh transaction, not fall back to older rights. A backward
clock interval is rejected. Policy effectivity uses the upper endpoint.

A concurrent revocation/deactivation does not retroactively rewrite an already
authorized read. Dirty ORM state is rejected and PostgreSQL also rejects injected
Core writes. SQL/lock failures are replaced by generic errors without raw SQL,
parameters or exception chaining; no new payload logging is added. Caller-supplied
Connection-bound sessions are not supported as owned service transactions and are
denied rather than trusted based on matching user IDs.

Institutional values must remain outside synthetic export/execution paths. Real
calendar access, cost compilation from persisted records, relocation consent,
additional availability, broader scheduling permissions and activation require
separate approval. There are no production coefficient values or claims of
calibrated inconvenience, social fairness or operational readiness.

## B1 implementation file inventory

The core files, schema documentation and compatibility assertions are:

```text
.github/workflows/backend-postgresql-regression.yml
.github/workflows/cdmcs-research-verification.yml
README.md
docs/architecture/database-design.md
docs/architecture/database-er-high-level.mmd
docs/architecture/database-er-high-level.svg
docs/architecture/database-er-physical.mmd
docs/architecture/database-er-physical.svg
docs/architecture/database-schema-catalog.md
docs/architecture/institutional-cost-policy-design.md
docs/database-operations.md
migrations/versions/0050b_institutional_cost_policy_foundation.py
research/cdmcs/i3d/d1/contract.py
scripts/generate_database_diagrams.py
tests/test_application_entrypoints.py
tests/test_cost_policy_persistence.py
tests/test_cost_policy_values.py
tests/test_database_diagrams.py
tests/test_equipment.py
tests/test_postgres_completion.py
tests/test_postgres_recovery.py
tests/test_recurring_persistence.py
tests/test_resource_feedback.py
tests/test_scheduling_preferences.py
tests/test_university_calendar.py
tests/test_waiting_lists.py
web/cost_policy_values.py
web/persistence/models.py
```

## B1 executed local verification

Windows, Python 3.12.14, PostgreSQL 17.11 and GCC 14.3.0, using only owned synthetic
database schemas and fictional records:

| Gate | Actual result |
|---|---|
| New policy values / PostgreSQL foundation | 10 + 21 passed; zero skips |
| Full application Python/PostgreSQL | 584 run in 2379.095 seconds: 583 passed, one expected POSIX permission skip on Windows; no database skips |
| Existing personal preference persistence | 40 passed separately; all 51 shared/persistence methods also included in the full application run |
| Application C++ | 192 passed; clean-slot and normal-dataset CSV CLI smoke cases passed |
| I3a / I3b / identity / I3c | 37 / 47 / 8 / 47 passed, zero skips |
| D1 / D2 | 84 / 56 passed, including native score/equivalence tests; zero skips |
| Standalone CDMCS | 618 differential cases, ten invalid inputs and one unresolved case; 25 safety methods passed |
| Additional focused checks | Matching-digest invalid numerical SQL, populated policy dump/restore, FK-index coverage and Alembic drift passed |

The new tests cover canonical digests across Unicode, equivalent offsets and
microseconds, maximum revision values, missing/invalid values, schema-pinned
integrity functions, immutable history, head reset prevention, atomic rollback,
competing head updates and both downgrade/append race directions. Restore checks
retain the policy digest and leave the current head absent.

Verification caught and corrected six missing leading FK indexes using the
existing unchanged quality test. The interrupted initial application run is not
counted as a successful full run; the table records the complete fresh rerun.
Excess timestamp precision is rejected rather than silently truncated. An early
fixture expectation was corrected to the existing calendar revision default 0.

Standalone and research-native checks used the preserved, SHA-256 verified Release
executable `7aa7724c4f53e5e4fb49aaf4cddd2252a4d561a241b2286d8b74e3ce93b60532`;
neither engine source changed. Application C++ was freshly compiled. No new
standalone build, ASan/UBSan or hosted CI coverage is implied by these Windows
executions. At this initial foundation checkpoint, Linux CI, independent review
and operational prerequisites remained outstanding. Tests establish compatibility
and integrity, not calibrated weights, social fairness or production readiness.

## B1 independent integrity and CI verification

The follow-up review reproduced and corrected three defects before publication:
malformed UTC offsets were normalized instead of rejected; SQL's control-character
classification rejected some text accepted by the pure contract; implicit
temporary-schema lookup could defeat structural trigger checks. Regressions now
require strict offset components, matching Python/SQL text domains and explicit
trusted schema resolution. Coefficient bounds, D1 compilation and both C++ engines
remain unchanged. No new tables or governance commands were necessary.

Independent canonical vectors exercise every variable digest field, exact Unicode
spelling, offsets, microseconds and maximum revisions. PostgreSQL tests witness
initialization and decision races, revocation ordering, rollback of flushed audit,
immutable histories, all four held downgrade locks and concurrent history writes.
The late-upgrade failure witness runs after all functions/triggers are installed:
rollback removes their DDL and retains revision 0050a; re-upgrade and drift checks
then succeed. Existing real backup/restore and FK-index tests also pass.

Final local verification used Windows, Python 3.12.14, PostgreSQL 17.11 and GCC
14.3.0. Every database test used owned, disposable schemas and fictional records.

| Gate | Actual result |
|---|---|
| Explicit institutional policy CI gate | 13 pure + 31 PostgreSQL tests passed; zero skips |
| Full application Python/PostgreSQL | 598 run in 2627.235 seconds: 597 passed; one expected Windows skip for the Linux executable-permission test; no PostgreSQL skips |
| Existing private preference CI gate | 51 passed; zero skips |
| Application C++ | Fresh compile: 192 passed; both CSV CLI smoke cases passed |
| I3a / I3b / identity / I3c | 37 / 47 / 8 / 47 passed; zero skips |
| D1 / D2 | 84 / 56 passed; zero skips |
| Standalone CDMCS Release | 618 differential cases, 7202 arrangements, 2504 moves; ten invalid inputs rejected, one unresolved case; 25 safety methods passed |
| Additional focused witnesses | Real populated policy dump/restore and FK-index coverage: two passed; strengthened late-DDL rollback: one passed |
| CI/documentation | Both workflows passed actionlint; eight embedded Python blocks parsed; five entry-point/gate tests passed; schema documentation matches all 58 application tables |

The full run was restarted after the confirmed integrity correction. Earlier red
witnesses and the interrupted pre-fix run are not counted as passing full runs.
The strengthened late-DDL test was also rerun in the final complete 44-test gate.
Native research checks used the same SHA-256 verified Release artifact recorded
above; application C++ was freshly compiled. No new standalone build or local
ASan/UBSan coverage is claimed, and Python persistence is not sanitizer-instrumented.

The hosted policy gate explicitly requires both complete test groups and zero
skips; its own regression rejects missing PostgreSQL, incomplete discovery and
skipped integration tests. The full Linux gate requires at least 598 tests and
only its known platform-specific skip. Policy paths also trigger existing research
Release, sanitizer and offline jobs. Hosted execution remains pending publication;
these workflows contain no deployment or operational migration steps.

At that B1 checkpoint the inactive foundation was ready for publication review,
not operational activation, with current-authority/lifecycle validation deferred.
Approved retention/erasure, restricted database ownership, private logging and the
inherited account-lifecycle security correction remain prerequisites for rollout.

## Internal governance verification (B2)

The service and `tests/test_cost_policy_governance.py` add no schema or engine
changes. Local verification used Windows, Python 3.12.14, PostgreSQL 17.11 and
GCC 14.3.0, with fictional identities, explicit fixture coefficients and authority
records confined to disposable test schemas in a separate temporary cluster.

| Gate | Actual result |
|---|---|
| Internal governance | 43 passed in 117.298 seconds; zero skips |
| Full application Python/PostgreSQL | 641 run in 2698.256 seconds: 640 passed, one expected POSIX executable-permission skip on Windows; no PostgreSQL skips |
| Existing foundation and personal preferences | All 44 policy and 51 preference methods executed successfully within that complete application run |
| Application C++ | Fresh compile: 192 passed; clean-slot and normal-dataset CSV smoke cases passed |
| I3a / I3b / identity / I3c | 37 / 47 / 8 / 47 passed; zero skips |
| D1 / D2 | 84 / 56 passed, including native score/equivalence checks; zero skips |
| Standalone CDMCS Release | 618 differential cases, 7202 arrangements, 2504 moves; ten invalid inputs rejected and one expected unresolved case; 25 safety tests passed |
| Schema compatibility | All 58 application tables match generated schema documentation; Alembic head remains 0050b; migration, drift, dump/restore, rollback and concurrency checks passed in the full suite |

The explicit governance command was `python -B -m unittest discover -s tests -p
test_cost_policy_governance.py -v`; the full command used `-p 'test_*.py'` instead.
Both used an isolated `TEST_DATABASE_URL`. Research groups used their existing
unittest discovery commands and hash-verified native executables; the application
C++ check used `tests/run_tests.ps1`. The standalone Release artifact has the same
SHA-256 recorded in the B1 verification above. No new standalone compilation,
local ASan/UBSan or hosted B2 CI execution is implied. Python governance is not
sanitizer-instrumented. Explicit hosted governance discovery/zero-skip gating and
Linux verification remain follow-up review work before publication.

The tests cover every legal/illegal transition, separate approval and activation,
self-approval denial, all five roles without implicit grants, stale identity,
session/database/schema binding, denied dirty sessions, bounded private history,
digest/pointer corruption, expiry, numerical revision exhaustion and no calendar,
preference, booking, notification or optimizer side effects. PostgreSQL witnesses
cover competing initial proposals, duplicate approvals, approval versus rejection,
activation versus deactivation, both raw-revocation lock orders, a coherent read
across concurrent deactivation, lock timeouts, an actual deadlock, commit failure
and late failure after a flushed audit event. Only one concurrent decision wins;
failure leaves neither a partial head nor an orphan decision.

An independent configuration witness found that a changed writer isolation of
REPEATABLE READ could authorize an old authority snapshot after waiting for a
revocation. The focused correction rejects non-READ-COMMITTED writers before head
initialization. A regression covers both REPEATABLE READ and SERIALIZABLE; normal
read-only REPEATABLE READ views remain supported. The earlier full run was stopped
after this finding and is not counted as passing: the table records the complete
fresh post-correction run. Initial commit-failure fixture scoping errors were also
corrected and rerun, not treated as successful verification.

This is ready for independent security/CI review, not operational use. Institution-
approved assignment, revocation and capability combinations still have no
management implementation. Activation uses B1's existing `approve` capability as
a separate operation; no additional authority is inferred from a role. Real grants,
calibrated coefficients, non-owner database privileges (including the required
authority lock), retention/erasure and private logging require separate approval
and deployment verification. Privileged database corruption requires a reviewed
recovery procedure, not silent history repair or fallback. The inherited
account-lifecycle correction remains mandatory before rollout. Public routes,
authority bootstrap, persisted-preference compilation, real-calendar execution,
CDMCS activation and booking changes remain absent.

## Independent governance review (B2.5)

Review preserved B2's three commits and found three concrete gaps. Each was
reproduced on disposable PostgreSQL before its correction:

| Finding | Correction and evidence |
|---|---|
| An AUTOCOMMIT-bound session reported READ COMMITTED but persisted an initialized head after denial; reads could also run without the promised mode | Inspect actual psycopg autocommit and server isolation/read-only state before initialization or policy reads. Regressions reject autocommit, wrong read mode and unsupported Connection-bound contexts |
| RR identity and a later grant-validity clock could describe no jointly authorized instant | Bound snapshot acquisition by transaction start/current clock and require the same valid grant at both endpoints. Real database witnesses cover revocation before a future grant, already-authorized reads finishing after revocation and the actual stable snapshot/lower clock bound |
| B1 structural references allowed an out-of-service overlapping activation across revisions to look like valid current/history | Validate the entire activation/deactivation stream with SQL LAG, not just the last revision. The witness also closes both overlapping activations and requires historical corruption to remain rejected |

The normal service state machine and explicit replacement protocol are unchanged.
No B1 schema correction was necessary: it can represent all required transitions;
structural FKs alone are not governance authorization. B2.5 neither weakens its
constraints nor treats digests as privileged-database tamper protection. Both
engines, nine coefficients/bounds, canonicalization, D1 synthetic provenance,
negative net costs, fairness and D2 global delay reference remain unchanged.

Real two-connection tests additionally cover approval and activation in both
revocation lock orders. A revocation that holds its insertion lock first prevents
the later decision; a decision holding SHARE first commits before revocation and
later attempts are denied. Writers all require READ COMMITTED/read-write mode;
no automatic retries or second lock order were introduced. Existing tests still
cover initial head/proposal races, duplicate decisions, stale versions, timeout,
deadlock, flushed-event failure and atomic commit failure.

The backend workflow now explicitly requires discovery of at least 56 governance
tests, execution of every discovered case and zero skips. Missing PostgreSQL,
incomplete discovery, partial execution and failed tests cannot pass. The full
Linux application floor is 656 with only its existing known platform skip.
Governance source/test changes trigger the existing push and PR research jobs,
including Release, sanitizers and offline comparisons. All evidence remains
synthetic; no new governance-data upload or deployment step is added.

Final local verification used the same Windows/Python 3.12.14/PostgreSQL 17.11/
GCC 14.3.0 environment and a new isolated cluster containing only fictional data.

| Gate | Actual result |
|---|---|
| Original B2 baseline | 43 passed in 118.784 seconds; zero skips |
| Actual embedded governance CI gate, executed locally | 56 passed in 284.486 seconds; zero skips |
| Full application Python/PostgreSQL | 656 run in 3256.696 seconds: 655 passed; one expected Windows POSIX-permission skip, no PostgreSQL skips |
| Existing policy / personal preferences | All 44 / 51 methods passed in the complete application run |
| Application C++ | Fresh compile: 192 passed; both CSV smoke cases passed |
| I3a / I3b / identity / I3c | 37 / 47 / 8 / 47 passed; zero skips |
| D1 / D2 | 84 / 56 passed; zero skips |
| Standalone CDMCS Release | Preserved hash-verified artifact: 618 differential cases, 7202 arrangements, 2504 moves, ten invalid inputs rejected and one expected unresolved case; 25 safety methods passed |
| CI / additional witnesses | Seven entry-point/gate tests passed; both workflows passed actionlint 1.7.12; nine embedded Python blocks parsed; strengthened clock lower-bound assertion separately rerun and passed |
| Persistence compatibility | 58 tables match generated schema documentation; head 0050b; full migration, drift, rollback, recovery, backup/restore and concurrency tests passed |

The strengthened lower-bound assertion was executed separately after the full
run had imported its tests; application code was unchanged. Initial red witnesses
are not counted as passing runs. Hosted Linux/PostgreSQL, Release and ASan/UBSan
verification remains pending authorized publication. WSL/Linux is not installed
locally; no fresh local standalone sanitizer build or Python sanitizer coverage
is claimed. Native checks used the same preserved SHA-256 Release artifact noted
above, while application C++ was freshly compiled.

The inactive service is ready to publish for review, not operational rollout.
Authority assignment/revocation governance, calibrated coefficients, restricted
database roles, retention/authorized erasure, private logging and the inherited
account-lifecycle correction remain mandatory prerequisites. No public routes,
management UI, operational grants, production values, operational policy activation,
real-calendar optimization or booking changes were introduced.
