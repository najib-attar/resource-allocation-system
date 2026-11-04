# Documentation index

The Student Portal and Professor Services are implemented in `main`. Student
[PR #24](https://github.com/najib-attar/resource-allocation-system/pull/24) and
Professor [PR #25](https://github.com/najib-attar/resource-allocation-system/pull/25)
record their integration. The application migration head is **0051b**.

## Start here

| Reader / task | Guide |
| --- | --- |
| Project overview and quick start | [Repository README](../README.md) |
| Run a persistent fictional demo; try student/professor sign-in | [Demo walkthrough](demo-walkthrough.md) |
| Develop the Flask application | [Web developer guide](../web/README.md) |
| Set up, migrate, back up or recover PostgreSQL | [Database operations](database-operations.md) |
| Understand persistence and schema | [Database design](architecture/database-design.md), [generated schema catalog](architecture/database-schema-catalog.md) |
| Understand the Flask/C++ boundary | [Engine JSON protocol](engine-protocol.md) |

## Implemented application workflows

| Area | Requirements / architecture | Coverage and verification |
| --- | --- | --- |
| Student Portal | [Portal guide](ui/student-portal/README.md), [frontend architecture](architecture/frontend-design.md) | [Feature matrix](ui/student-portal/coverage.md), [screen coverage](ui/student-portal/screen-coverage.md), [UI-10 control traceability](ui/student-portal/UI-10/traceability.md) |
| Professor Services and Portal | [Professor guide](professor-services/README.md), [approved contracts](srs/professor-workflows.md), [shared UI architecture](professor-services/frontend-plan.md) | [Backend/control traceability](professor-services/traceability.md), [screen coverage](professor-services/screen-coverage.md) |
| Student–professor appointments | [Requirements](srs/UC-STU-01-requirements.md), [design](architecture/appointments-design.md) | [Student acceptance record](ui/student-portal/acceptance-report.md), [Professor acceptance record](professor-services/acceptance-report.md) |
| Student room requests | [Requirements](srs/UC-STU-02-requirements.md), [design](architecture/student-room-design.md) | Student portal feature/control matrices above |
| Equipment borrowing | [User guide](equipment-borrowing-guide.md), [requirements](srs/UC-STU-03-requirements.md), [design](architecture/equipment-borrowing-design.md) | Student portal feature/control matrices above |
| Waiting lists | [Requirements](srs/UC-STU-05-requirements.md), [design](architecture/waiting-lists-design.md) | [Acceptance cases](testing/waiting-list-test-cases.md) |
| Feedback and issues | [Requirements](srs/UC-STU-06-requirements.md), [design](architecture/resource-feedback-design.md) | Student portal feature/control matrices above |
| Calendar and personal schedule | [Requirements](srs/unified-calendar-requirements.md), [calendar design](architecture/unified-calendar-design.md) | Portal acceptance and screen/control matrices above |
| Recurring room/equipment reservations | [Design and lifecycle](architecture/recurring-reservations-design.md) | [Operations and configuration](database-operations.md#recurring-room-and-equipment-reservations) |

Representative screenshots come from the actual Flask application with synthetic
PostgreSQL records: [Student gallery](ui/student-portal/screenshots.md),
[Professor screenshot manifest](professor-services/screenshots.json).
Acceptance records identify the exact revisions, commands and results that ran;
historical counts are not claims of a fresh test execution on every later commit.

## Research and inactive foundations

- [CDMCS research guide](../research/cdmcs/README.md): isolated experiments, explicit
  synthetic execution and authorized read-only projection; no live scheduler activation.
- [Private preference foundation](architecture/personal-preferences-design.md):
  private persistence, not a public settings screen or optimizer input activation.
- [Institutional cost-policy foundation](architecture/institutional-cost-policy-design.md):
  internal values/governance boundary, without calibrated defaults or public management UI.

These foundations do not grant new scheduling, delegation or booking permissions.

## Historical and proposed material

- [Campus Space reference pack](design/campus-space/README.md) and its
  [static prototype](design/campus-space/index.html) retain approved visual references.
  Fictional data, prototype controls and original implementation instructions are
  not production behavior. Use the portal matrices for actual coverage.
- [Original professor handoff](../Codex-Professor-Handoff.md),
  [pre-implementation backend audit](srs/professor-backend-audit.md) and
  [use-case PDFs](use-cases/) preserve the input specifications. Later approved
  [professor contracts](srs/professor-workflows.md) resolve policy decisions.
- [Iteration reports](iteration-reports/), [analysis](analysis/) and
  [design reports](design/) preserve development history. Their version-specific
  schema counts, branch states and test results apply to their recorded checkpoints.

Deferred application functionality includes academic-request notifications,
academic cancellation, versioned replacement of published academic requests,
a standalone student office-hours browser and a unified cross-service activity API.
Appointment notifications/cancellation and existing service-specific activity pages
are implemented. Production deployment and real-data CDMCS activation require
separate work; no prototype or research document implies their availability.
