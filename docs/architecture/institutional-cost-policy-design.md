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
| effective | `from` / `until`: aware ISO timestamps, half-open UTC interval, 1970 through 2099; microseconds at most, no rounding |
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
reject update/delete/truncate. Integrity functions pin their own schema search
path. Current and historical grant identity is NOT proof of a currently authorized
human action; these constraints are structural, not the B2 authorization service.

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

## D3-C-B2 boundary

B2 must establish approved named authorities and authentication/database binding,
recheck current grants and account status in the decision transaction, serialize
authority revocation/publication, reject stale expected-head versions, enforce full
lifecycle transitions and validity, and atomically publish pointer plus audit.
Approval must remain distinct from activation. Missing, expired, deactivated,
unsupported and corrupt policies must block optimization without older/zero-cost
fallback. This foundation implements none of those management operations.

Institutional values must remain outside synthetic export/execution paths. Real
calendar access, cost compilation from persisted records, relocation consent,
additional availability, broader scheduling permissions and activation require
separate approval. There are no production coefficient values or claims of
calibrated inconvenience, social fairness or operational readiness.

## Implementation file inventory

The core files, schema documentation and compatibility assertions are:

```text
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
executions. Linux CI, independent security review and operational prerequisites
remain outstanding. Tests establish compatibility and integrity, not calibrated
weights, social fairness or production readiness.
