# D2: research-only fixed-calendar batching

This stage is synthetic-only and explicitly invoked. It does not select a live
scheduler, read a database, create bookings or persist preferences. Both C++ engines,
their protocols and the historical Python references remain unchanged.

## Contract audit and supported domain

The existing I3c runner executes two subprocesses per candidate and retains only
aggregate feasibility. Its CDMCS codec sets delay to zero and uses merged busy
blocks. It is an independent **feasibility** baseline, not a D1 score serializer.
The production appointment `validate` operation checks exactly one proposed
interval, including off-grid starts; its capped recommendation operation is not a
complete feasible-set API.

The unchanged I1 `solve` loop visits exactly the submitted starts. With protected
fixed events, no resources, no replacement starts and no extra-availability
windows, each start yields zero or one arrangement. A successful request containing
at most 100 distinct starts and `limit=100` can therefore return every feasible
submitted start. This statement is false when relocation is permitted. Protocol
validation must additionally reject truncation, duplicate/foreign starts, missing
counts, movement/permission output or an unresolved-calendar status.

Each D2 input is bound to an existing immutable I3c synthetic fixture and compiled
once by D1 from explicit owner preferences, explicit synthetic numerical policy
and complete unclipped calendar context. No profile defaults are invented. Missing
or unresolved calendars (including optional calendars in this first strict domain),
database-origin projections, resources, overlapping baseline meetings and
unsupported timezone/cost data are rejected before execution. Optional invitees
remain nonmandatory; an unavailable **known** optional calendar does not block.

## Delay and partition proof

For the full universe U, submitted subset S and unchanged local date array d:

```text
C_S(t) = sum(personal net burden at t) + w * (d(t) - d(min S))
C_S(t) - C_U(t) = -w * (d(min S) - d(min U))
```

Personal burden/fairness are independent of alternative candidate starts. Plain
chunks are equivalent only for zero delay or a preserved minimum local date. For
positive delay, a later-date chunk includes the original earliest candidate as an
ordinary reference alternative, consuming one of the configured <=100 slots.
No foreign time is introduced; the union remains exactly U. Reference rows are
checked for consistent feasibility/cost/fairness but counted only at their unique
target occurrence. Every original candidate is a target exactly once. A blocked
reference still works: the C++ reader fixes its origin before feasibility checks.
Batch size one cannot express a later-date positive-delay target plus reference;
the entire plan is explicitly unsupported before launching, never silently rebased.

The D1 delay guard is called for each submitted subset. Only `candidate_starts`
and the output limit change; UTC anchor, horizon, prefix arrays, true original
events, published windows, duration and all weights stay unchanged. No score
correction, floating-point arithmetic or optimizer modification is performed.

Complete responses map each target to either its returned integer score/burden or
infeasible. Combining target scores by `(total, fairness, original start)` retains
the exact existing objective because movement fields are null. Production still
receives one original single-time validation per target, not per repeated reference.

## Implementation milestones

1. Audit/partition proof, immutable D1 preparation and pure adversarial tests.
2. Reuse the I3c bounded execution kernel, implement the opt-in runner and verify
   native singleton/full-calendar equivalence, privacy and failure cleanup.
3. Matched optimized-build measurements, complete regressions, final source review
   and evidence. All commits remain local until publication is authorized.

No persistent worker, new matching algorithm, production API or new framework is
required. Original I3c singleton execution remains available and unchanged by default.
