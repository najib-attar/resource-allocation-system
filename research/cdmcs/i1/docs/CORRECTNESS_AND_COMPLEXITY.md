# I1 correctness sketch, supported model and complexity

## Exactness theorem (restricted domain)

Given a conflict-free original calendar, finite explicit candidate new meeting starts `T`, finite replacement starts `R`, truthful published/exception windows, and at most one *blocking* flexible-meeting relocation, the algorithm returns the lexicographic minimum of the exact V15 cost function among all structurally feasible and requestable candidate arrangements.

**Reason:** For every candidate start `t`, retrieve the set of **distinct** original meetings conflicting with the new meeting. If it is empty, the one admissible no-move arrangement is considered. If it contains one meeting that is flexible, examine all permitted replacement starts for that meeting, rejecting replacement conflicts with the unchanged schedule and the newly inserted meeting. If it contains two or more distinct meetings, or a fixed blocker, no allowed one-move arrangement exists. Every accepted arrangement is assigned its exact incremental preference delta and fixed supplemental costs. Selecting the minimum lexicographic key is therefore exact within the restricted solution universe.

This does **not** claim that all users will approve conditional proposals or that a globally best continuous-time university schedule is found.

## Incremental preference scoring

For each affected participant, adding/removing a meeting changes the meeting's own rate-prefix term plus at most two adjacent gap terms (and the previously adjacent gap). Deleting an original event, inserting the new event, and inserting the relocated event uses a fixed number of predecessor/successor lookups in the original indexed calendars; the new event is passed as an overlay when relevant. This is exact only for the stated **locally decomposable** V15 preference function.

The independent test oracle instead enumerates each permissible new/replacement pair using all-pairs conflict checks and recomputes every affected participant's complete schedule cost. It does not reuse I1's indexes or incremental scoring.

## Complexity (with explicit finite input)

Let `H` be the number of precomputed minutes, `P` the number of supplied participant profiles, `N` the number of baseline person/resource calendar entries, `K=|T|` the number of candidate starts, `J` the number of distinct movable blockers encountered, `R=|R|` the number of replacement starts, `q` the maximum number of keys inspected for new/replacement events, and `u` the maximum affected participants. Under the conflict-free baseline invariant:

- Read/validate prefix/date data: `O(PH)`; build sorted per-key calendars: `O(N log N)`.
- One conflict search: `O(q log N + z)` where `z` counts reported distinct overlaps (the program may inspect a small number of adjacent baseline entries for each key).
- Cache one blocking meeting's permissible replacements once: `O(R q log N)` per distinct blocking meeting (plus its permission checks).
- Evaluate at most `D ≤ K R` joint proposals, each in `O((q+u) log N)` plus bounded output top-K maintenance (`limit ≤100`).
- Conservative total: `O(PH + N log N + K q log N + J R q log N + D(q+u) log N + D*limit*log(limit))` (ignoring constants and raw JSON serialization).

The original estimate above omits linear availability-window scanning and
key/participant membership comparisons. For the actual implementation let `W`
be maximum windows per profile, `p` maximum affected people, `L` output limit,
and `B` serialized input size. A more conservative expression is:

`O(B + PH + N log N + (K + JR)(q log N + z + pW)
  + D(q^2 + p^2 + p log N + L log L))`.

Here `z` counts overlap visits across keys, including the same meeting encountered
on several keys; identities are deduplicated afterward. String lengths are bounded
implementation constants, not free operations in an unrestricted model. Cached
replacement meetings copy memberships, so memory includes `O(JR(q+p))`, not just
`O(JR)`, in addition to the parsed input, profiles and indexes. I2 explicitly caps
copied cache members and logical search work. No time/space advantage is inferred
from the existence of caching alone.

All quantities are explicit or bounded in the input; enumerating each minute of a compact huge horizon is **pseudo-polynomial** in the horizon's bit length. There is no exponential subset enumeration because only one conflicting original meeting may move. No worst-case performance superiority over the production C++ engine follows.

The caller-provided profile and local-day series are authoritative inputs. Failure to compute them correctly upstream can invalidate calendar or preference semantics even when the C++ core is internally exact.

The theorem applies only when evaluation completes within implementation budgets.
An `INVALID_INPUT` resource-limit response is not an infeasibility certificate.
The supplied V15 reference has an empty-participant relocation horizon bug;
the differential harness explicitly enforces the documented bounded horizon.
See [review](REVIEW.md) for the preserved witness and scope of comparison.
