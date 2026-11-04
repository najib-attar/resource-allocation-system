# Professor Services and Portal

Professor Services UC-PROF-01–09 and Portal PROF-UI-01–08 are implemented in `main`
through [PR #25](https://github.com/najib-attar/resource-allocation-system/pull/25),
building on the merged Student Portal [PR #24](https://github.com/najib-attar/resource-allocation-system/pull/24).
This is one application and shared Campus Space design system, not a separate server.

| Capability | Current implementation |
| --- | --- |
| UC-PROF-01 | Own weekly office hours, validity dates, exclusions and safe removal |
| UC-PROF-02 | Required-professor appointment review, own decisions, progress/history and authorized cancellation |
| UC-PROF-03 | Personal schedule/calendar blocks and authorized commitments |
| UC-PROF-04 | Optional invitations to student room activities; no faculty-review permission implied |
| UC-PROF-05 | Authorized calendar and existing appointment/room notifications |
| UC-PROF-06 | Self-owned Exam academic declarations using existing engine contracts |
| UC-PROF-07 | Self-owned OneTime and Recurring teaching declarations using weekly slots |
| UC-PROF-08 | CommitteeMeeting resource requests with required participants; separate from student appointments |
| UC-PROF-09 | Owner-only eligibility/allocation tracking, history and unpublished revisions |

Administrative eligibility, allocation outcomes and calendar publication are
separate. New inputs await explicit review; only eligible current revisions enter
the engine. Eligibility reserves nothing. Existing published reservations survive
legacy review/rejection until an authorized replacement; active published inputs
remain read-only. Faculty/course descriptions do not verify teaching affiliations.

## Contracts, architecture and evidence

- [Approved backend contracts and migration assumptions](../srs/professor-workflows.md)
- [Complete use-case/control-to-backend traceability](traceability.md)
- [Frontend architecture and implemented sequence](frontend-plan.md)
- [Screen and action coverage](screen-coverage.md)
- [Acceptance record, exact executions and limitations](acceptance-report.md)
- [Representative real-app screenshot manifest](screenshots.json)
- [Implementation file inventory](changed-files.json)
- [Database setup, 0051a eligibility and 0051b logout rollout](../database-operations.md)
- [Original UC-PROF specifications](../use-cases/)

The acceptance record preserves pre-publication/audit checkpoints. Merge status
comes from the PR; their recorded test totals are historical execution evidence.
Generated raw dumps were pruned during integration with immutable Git references
and cleanup manifests retained. Do not recreate bulk tracked evidence for routine runs.

## Deferred scope

Academic-request notifications, academic-request cancellation and versioned
replacements of published academic requests remain deferred. Existing appointment
notifications/cancellation work. Professors cannot initiate student appointments,
approve a peer's appointments, review their own eligibility, run allocation or
publish campus results. Owner-only tracking does not grant peer calendar access.

For local startup and developer tests use the [web guide](../../web/README.md).
For research boundaries and other services use the [documentation index](../README.md).
