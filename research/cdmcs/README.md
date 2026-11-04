# CDMCS research guide

CDMCS is isolated experimental scheduling research. It is **not activated as the
application scheduler** and is not one of the administrative allocation strategies.
The live application continues to use the existing C++ allocation and appointment
contracts, PostgreSQL reservations and approval rules.

| Stage | Implemented research boundary | Guide |
| --- | --- | --- |
| I1 / I2 review | Standalone C++17 finite-model optimizer and independent correctness tests | [Engine, build and model](i1/README.md) |
| I3a | Explicitly synthetic offline snapshots and paired feasible-set comparison | [Snapshot and comparison guide](i3a/README.md) |
| I3b | Authorized, read-only internal calendar projection; no engine execution | [Privacy and authorization boundary](i3b/README.md) |
| I3c | Disabled-by-default, explicitly invoked synthetic shadow runner | [Admission, transport and resource limits](i3c/README.md) |
| I3d D1 | Synthetic preference contracts and deterministic cost compilation | [Compiler and mathematical mapping](i3d/d1/README.md) |
| I3d D2 | Synthetic fixed-calendar batching with preserved delay semantics | [Partition proof and measurements](i3d/d2/README.md) |

I3b projection is not permission to run real calendars through an optimizer.
Synthetic fixtures and cost coefficients are not university preferences, consent
or calibrated policy. Proposals never create reservations or replace mandatory
approval and fresh conflict checks. Real-data execution, distributed admission,
retention and activation require separate review.

## Reading historical results

Stage READMEs retain dated local verification, source revisions, measurements and
the CI status at that checkpoint. References such as migration `0049b`, 53 tables,
“pending publication” and future stage recommendations describe those historical
checkpoints; the application is now at `0051b`, and D2 is implemented within its
documented synthetic boundary. Later integration is recorded in
[Student PR #24](https://github.com/najib-attar/resource-allocation-system/pull/24)
and [Professor PR #25](https://github.com/najib-attar/resource-allocation-system/pull/25).

Current verification is configured in the
[isolated research workflow](../../.github/workflows/cdmcs-research-verification.yml)
and [application/PostgreSQL workflow](../../.github/workflows/backend-postgresql-regression.yml).
They are correctness gates, not evidence of deployment, optimizer activation or
algorithmic speedup. Measurements remain valid only for their stated inputs,
builds, machines and timing boundaries; no new performance claim is made here.

Follow each stage's prerequisites and reproduction commands. Research-only
Boost/CMake dependencies are separate from normal application startup. Preserve
original reference hashes and useful regression tests. Use disposable synthetic
databases for integration tests and keep raw private calendar payloads out of Git.

See the [application documentation index](../../docs/README.md) for active
workflows, operations and the inactive preference/cost-policy persistence foundations.
