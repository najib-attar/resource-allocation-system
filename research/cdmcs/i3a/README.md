# I3a: offline calendar snapshot and shadow comparison

This independent Python research tool invokes the two existing C++ executables.
It has no database access, web routes, booking actions, or production selection
flag. Everything it accepts must be explicitly synthetic. Roles are descriptive
metadata, never scheduling dispatch or authorization. Neither engine is modified.

## Source audit and equivalence boundary

| Actual behavior | Required mapping / exclusion |
|---|---|
| Production `AppointmentSchedulingService::validate` checks organizer busy time, but requires published hours for every `professorIds` member | Organizer uses busy-only availability; every other required person must explicitly require published availability. This is a constraint policy, not a role test. |
| Production `recommend` merges touching/overlapping published windows and anchors a 15-minute grid to the first professor's merged window, even before the horizon | Preserve the explicit grid-anchor participant and original window starts. Normalize unions before either serialization. |
| Production allows overlapping busy records; I1 requires a conflict-free baseline | Union busy intervals per person for this fixed-calendar experiment, preserving original commitments in the snapshot/evidence. No relocation or identity-dependent score claim follows from this projection. |
| Production optional invitees affect ranking, never feasibility | Do not put optional people into CDMCS required profiles/calendars. Unknown optional calendars remain unknown in production ranking. |
| Production uses epoch seconds, I1 uses elapsed UTC minutes | Reject precision loss; use an explicit UTC anchor, never wall-clock subtraction across DST. |
| I1 requires caller-prepared prefixes and local-day ordinals | Derive these only from explicit synthetic rate bands and the declared IANA zone. Reject decreasing civil-date mappings. |
| Production has no shared-resource appointment constraint | Resource-constrained comparisons are unsupported, not silently stripped or emulated as people. |
| I1 has relocation and exception permissions | Disable both: fixed baseline commitments, empty replacements/exceptions. Proposals never become bookings. |
| Both recommendation operations cap output at 100 | Reconstruct complete feasible sets by validating every common candidate separately in each engine. |
| Objectives differ | Compare rankings separately, without interpreting rank differences as feasibility defects. |

Source anchors: `src/services/AppointmentSchedulingService.cpp:18,30,59`,
`src/integration/AppointmentJsonProtocol.cpp:41`, `web/calendar_service.py:141`,
`web/engine_gateway.py:107`, and `research/cdmcs/i1/docs/JSON_CONTRACT.md`.
Existing appointment/professor/invitation/commitment database models and revision
approval rules remain solely in the application. The offline tool imports only
the existing read-only executable/hash validator, not calendar/database services
or the Flask gateway. It retains raw process failures instead of losing evidence.

## Milestones

1. Frozen snapshot contract, validation, timezone and compatibility tests.
2. Shared interval normalization, exact grid generation and separate serializers.
3. Complete feasible-set comparison, strict output validation, ranking, bounded
   subprocess measurements, and reproducible evidence export.
4. Synthetic boundary/exhaustive matrix, research/application regressions and
   measured report. No live-calendar comparison or integration is authorized.

## Snapshot v1

The JSON root declares `snapshot_version: 1`, `synthetic: true`, `snapshot_id`,
`timezone`, `utc_anchor`, `horizon`, `duration_minutes`, `organizer`, `participants`,
`commitments`, `required_resources`, `candidates`, and `provenance`.
Optional `preferred_start` and `unsupported_information` are explicit.
See `fixtures.py` for reproducible complete examples.

- Participants have opaque IDs, `required`, `published_required`, `calendar_state`
  (`known`, `missing`, `unresolved`, `unsupported`), `published` intervals, optional
  `role_label`, and synthetic `preference` settings. The organizer must be required.
  A known empty publication list means no offered hours, not missing information.
- Commitments identify people/resources and an interval. They must be protected;
  the tool never relocates them. Pending/cancelled records must not be invented as
  protected commitments. Fixtures explicitly specify the calendar facts used.
- Intervals are half-open `[start,end)`. ISO timestamps must be exact minutes.
  UTC instants (`Z`/`+00:00`) are unambiguous across DST. Local wall strings use
  the explicitly declared zone; folds and gaps are rejected. Nonzero offset wall
  strings must agree with that zone and must also be unambiguous.
- The UTC anchor is no later than the horizon. The anchor-to-end range is bounded
  to 32 days. Meetings are 1-1440 minutes; candidates must fit in the horizon.
- `candidates.mode` is `production_grid` (step exactly 15 minutes) or `explicit`
  (independent manual validator tests). `anchor_participant` is an explicitly
  publication-constrained required person and maps to the first production
  professor. This preserves engine grid semantics without assuming a human role.
- Preference defaults are explicitly **synthetic neutral**: rate/break/gap/delay
  weights zero. Optional nonoverlapping `rate_bands` override `base_rate`;
  `preferred_break`, `gap_weight`, `nearby_limit` prepare I1's documented costs.
  These are not university policies or learned personal preferences.
- Missing/unresolved mandatory data, unsupported information, unrepresentable
  resource constraints, and I1 profile/window budgets yield unsupported comparison,
  never an inferred free calendar. Invalid shapes/numerics yield input errors.

The contract becomes frozen dataclasses containing tuples, not mutable nested
dictionaries. Serializers produce fresh dictionaries; they cannot mutate inputs.
Input size, collection counts, identifiers and numerical values are bounded.
This is test tooling, not a public endpoint or a new application protocol.

## Comparison and measurements

Each candidate interval is sent to production `--appointments-json` with
`action: validate`, and to I1 with exactly one candidate, no replacements and no
exceptions. Feasible/infeasible sets are comparable only when every call succeeds.
Unresolved and engine/input errors are never counted as infeasibility. All raw
requests/stdout/stderr/exit statuses are retained, including discrepancies.

Ranking uses separate actual batch recommendation calls only on the production
grid. Explicit off-grid cases have feasibility evidence, not a fabricated
production recommendation ranking. Top-100 lists and total candidate/feasible
counts are labeled separately. CDMCS cost/fairness apply to the normalized fixed
calendar, not an approval process or calibrated utility.

Process creation, communicate, encoding, decoding and complete invocation times
are recorded separately using `perf_counter_ns`. Process creation is not the
entire OS startup overhead; communicate includes startup, parsing, scheduling and
serialization. Neither engine exposes pure computation timing. Matched per-
candidate experiments use the same C++ binaries, grids and repetitions, alternate
engine order, and include warmups. No process-free speedup claim is justified.

## Reproducibility and operation

Commands, runtime/source/executable hashes, pinned timezone-data version, input
hashes, raw outputs and normalization are exported only to a **new directory
outside the checkout**. Existing directories are never overwritten. No network,
database, Flask request, background worker or operational file is used by the tool.
Production executable resolution retains source/binary manifest checks. I1 must
be supplied explicitly and checked against an explicit expected SHA-256.

Normalization, request-dictionary construction and preflight executable hashing
are outside the per-invocation timing. JSON encoding/decoding are included and
reported separately. Different payload sizes and preference computations remain
real protocol differences, not controlled-away algorithm timing. A process-free
computation benchmark would require separately reviewed instrumentation.

Build I1 using its existing README. Use the existing authoritative production
binary or `scripts/build_backend.py --output <external-path>`; never select an
arbitrary filename fallback. Example from the repository root, using Python with
the pinned I1 test dependencies installed:

```text
python -B -m research.cdmcs.i3a --matrix --cdmcs <explicit-binary> --cdmcs-sha256 <sha256> --output <new-external-directory> --repetitions 3 --warmups 1
```

Set `CDMCS_I3A_BINARY` and `CDMCS_I3A_SHA256` explicitly for native tests, then:

```text
python -B -m unittest discover -s research/cdmcs/i3a/tests -v
```

Set `PYTHONDONTWRITEBYTECODE=1` and `PYTHONTZPATH` to an empty string to use the
pinned IANA `tzdata` dependency rather than the machine's timezone database.
No additional package is required. Native comparisons explicitly skip without
both executable settings; unit tests still run. `--input <synthetic.json>` runs
one snapshot instead of `--matrix`. Optional `--production` selects an explicitly
configured manifest-validated artifact, never a filename search/fallback.

Exit codes are 0 for equal, 1 for a discrepancy, 2 for input/engine failure and
3 for an unsupported single comparison. The built-in matrix includes declared
unsupported/invalid cases and succeeds only when their expected classifications
match; it never suppresses actual engine errors on valid cases.

Final verified counts, measurement conditions and remaining gaps are in
`RESULTS.md`. No current result claims a production integration or a speedup.
