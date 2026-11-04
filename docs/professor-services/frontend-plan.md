# Professor Portal — frontend implementation and architecture

Reviewed base: `5a7f0b0`, dedicated `codex/professor-services-v1` worktree. Student baseline `747c925` and Draft PR #24 remain unchanged. The fresh 29-test backend preflight passed: eligibility, intake, legacy preservation, existing professor ownership and identity/session workflows. The user request governs over the archived design/handoff instructions.

## Shared design and information architecture

The implementation promotes the existing Campus Space shell/service CSS and Jinja service parent to workspace-neutral components, retaining Student role classes and rendering. No duplicate design system, framework, global reset or business-rule implementation was added. Existing other-role styles/permissions remain opt-in and unchanged.

Primary professor navigation: Home, My academic requests (real owner route), Calendar, Inbox. Service entry points appear on Home: Appointments, Office hours, Academic requests, Personal schedule and optional room invitations. Preserve authorized legacy campus-service/history destinations through Home, not duplicate primary navigation. Account controls keep schedule, notifications and logout.

Home uses a read-only, Instructor-scoped database snapshot, existing academic read contracts and personal schedule projection. It shows actual upcoming required confirmed appointments, requests awaiting this professor, bounded office-hour patterns, academic review/outcomes, dated own commitments and recipient notifications. No teaching affiliation or dates are inferred from declarations. Lists link to complete existing services.

## Implemented sequence

| Phase | Pages and presentation | Verification and safety boundary |
|---|---|---|
| PROF-UI-01 | Shared Campus shell, Professor Home, four primary destinations, service discovery and real authorized summaries | Read-only/empty/populated/privacy/disabled identity, no engine on reads, Student and other-role shells; actual Flask screenshots at five widths |
| PROF-UI-02 | Appointment hub, pending decisions, details/progress/invitations/history and authorized approval/decline/cancel | Original parameters/revisions/CSRF, per-professor decisions, Student reschedule invalidation, conflicts; no professor appointment creation |
| PROF-UI-03 | Office-hour form/list, inclusive validity/exclusions, personal timetable/blocks | Original hour/block services and timezone, invalid intervals and cross-user denials, confirmed commitments protected |
| PROF-UI-04 | Four academic intake forms and unpublished revision presentation | Explicit resource/weekly slots, declarations and required committee participants; same idempotency/validation; no allocation control or invented date/strategy |
| PROF-UI-05 | Owner request list/filter/pagination/detail, separate eligibility/allocation/calendar steps, actual resources/reasons/history | Published requests read-only, revision resets approval, current/rejected/pending outcomes and owner-ID tampering |
| PROF-UI-06 | Existing calendar, personal schedule and Inbox component alignment | Month/week/day, filters/date navigation/privacy, supported read actions; academic notifications explicitly unavailable |
| PROF-UI-07 | Independent control/source audit, safe cleanup, complete integration/cross-role/browser regressions | Actual persisted POST outcomes, 1440/1024/768/390/320, keyboard/focus/overflow, full Python/PostgreSQL and C++ tests; no operational data |

PROF-UI-01–07 have focused verified commits; the acceptance report lists their SHAs. PROF-UI-07 supplies the final independent integration/full regression evidence. Each page group was exercised in the real Flask application with disposable PostgreSQL data at all five widths. The [screen/control coverage](screen-coverage.md) extends the existing [backend traceability](traceability.md); the acceptance report records actual execution, not planned passes.

## Existing limitations preserved

Academic slots are weekly weekday/minute requirements. Calendar dates require explicit administrative applicability. Shared/multi-room exam behavior is the existing engine strategy plus the supported split declaration; professors cannot select or run campus allocation strategies. No academic cancellation contract, versioned published replacement, academic notification producer or private teaching-attribution entitlement is added. Existing optional room invitations grant no faculty-review/custody authority.

## Integration evidence maintenance

Student PR #24 is merged; Professor Services now inherits main at `1969335`. For fresh browser execution, set `PROFESSOR_REVIEW_OUTPUT` to an owned directory under ignored `build/` before running the existing browser helpers. Keep compact verified summaries and deliberately selected representative captures; raw control/state dumps and extra screenshots are ignored. The acceptance report and artifact-cleanup.csv identify retained and historical evidence. Academic notifications, cancellation and versioned published replacements remain deferred.
