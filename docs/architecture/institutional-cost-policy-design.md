# Institutional numerical policy foundation (0050b)

This is an empty, internal schema and pure value contract. There are no policy
proposal, approval, activation or authority-management commands, routes, UI or
optimizer consumers. Installing this schema grants nobody authority and activates
no policy. Personal preferences, published availability and existing bookings are
unchanged. The existing production appointment scheduler remains the default.

## Values and mathematical compatibility

`web/cost_policy_values.py` provides immutable `CostCoefficients` and
`InstitutionalCostPolicy` values. `parse_institutional_policy(document,
university_timezone=..., expected_digest=...)` validates values, not an actor.
The trusted future caller must supply the configured university timezone; an
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

## D3-C-B2 boundary

B2 must establish approved named authorities and authentication/database binding,
recheck current grants and account status in the decision transaction, serialize
authority revocation/publication, reject stale expected-head versions, enforce full
lifecycle transitions and validity, and atomically publish pointer plus audit.
Approval must remain distinct from activation. Missing, expired, deactivated,
unsupported and corrupt policies must block optimization without older/zero-cost
fallback. This foundation implements none of those management operations.

The schema supports the following future transaction protocol without another
ledger or initialization table. B2 must implement and test it, not rely on these
structural constraints as authorization:

1. In the existing READ COMMITTED writer transaction, explicitly initialize the
   absent singleton with `INSERT ... ON CONFLICT DO NOTHING`, then lock it with
   `SELECT ... FOR UPDATE`. Initialization leaves the active pointer null.
2. Use head-first locking for all proposal, decision, publication and authority
   changes, then a consistent identity-lock order. Recheck authenticated session,
   enabled account, latest grant and its validity in that same transaction.
   A revocation must take the same head lock to serialize with approval.
3. Reject a stale expected head version. Allocate bounded revision numbers and
   the next head version under the lock; write immutable content/history and the
   matching head update atomically. Unique keys remain a final duplicate guard.
4. Validate the complete lifecycle and configured timezone/effective interval.
   A historical Granted row alone does not mean authority is current. A historic
   Activated event alone does not mean it has not subsequently been deactivated.
   Raw SQL can satisfy those associations without implementing the B2 workflow.
5. Roll back the whole operation on error. Bound lock waits and handle retryable
   conflicts without replaying partial decisions. Direct SQL that ignores the
   common lock order may deadlock with migration; PostgreSQL rollback must win
   over availability, never discard committed history. REPEATABLE READ writers
   would additionally need whole-transaction serialization retries.

Schema-only concurrency witnesses cover competing initial heads, proposals and
decisions, revocation-before-decision ordering and rollback of a flushed event.
They demonstrate available primitives, not an implemented governance service or
new authority for any application role.

Institutional values must remain outside synthetic export/execution paths. Real
calendar access, cost compilation from persisted records, relocation consent,
additional availability, broader scheduling permissions and activation require
separate approval. There are no production coefficient values or claims of
calibrated inconvenience, social fairness or operational readiness.

## Implementation file inventory

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

## Executed local verification

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

## Independent integrity and CI verification

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

This is ready for publication review as an inactive foundation, not operational
activation. Current-authority/lifecycle validation remains B2 work. Approved
retention/erasure, restricted database ownership, private logging and the inherited
account-lifecycle security correction remain prerequisites for rollout.
