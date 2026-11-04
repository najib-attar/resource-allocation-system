# Professor workflows — repository audit and implementation boundary

> Historical pre-implementation audit, retained as handoff evidence. UC-PROF-06–09
> and the approved eligibility policy are now implemented and merged. Use the
> [approved contracts](professor-workflows.md) and
> [current Professor Services guide](../professor-services/README.md) for present behavior.

**Audit basis:** `najib-attar/resource-allocation-system`, GitHub `main`, inspected 3 November 2026. The UI-01–UI-10 student redesign is local and has **not** been inspected: remote `design/student-portal` and its recent commits were unavailable. Any deviations in the local worktree must be reconciled by Codex before implementation.

## Roles and authority

- The authenticated professor role is named **`Instructor`** in the database and route guards. Do not add a parallel `Professor` role.
- An ordinary Instructor may manage their own published appointment hours, review only the student appointments in which they are a **required professor**, cancel their eligible appointments, manage their own dated blocks, access their relevant private calendar and notifications, and accept/decline explicit optional invitations to student-organized room activities.
- Ordinary Instructor does **not** approve student room reservations. `web/room_calendar.py:valid_approvers` requires an active **Staff** or **Administrator**, or an administrator account; an Instructor may act in a staff capacity only if separately given administrator authority.
- Ordinary Instructor does **not** currently submit university-wide academic resource requests through `/add-request`, run `/run-allocation`, select a campus-wide algorithm, or publish academic calendar records. Those routes are administration restricted by `web/security.py`.
- Equipment borrowing is currently student-only; equipment custodians are authorized Staff/Administrator accounts. Do not add general professor borrowing or lending privileges implicitly.
- The admin can explicitly attribute an academic publication to an Instructor (`web/university_calendar.py`), but that is **not** a verified teaching assignment or permission to edit the academic request.

## Use-case mapping

| ID | Professor use case | Current code authority | Delivery state |
|---|---|---|---|
| UC-PROF-01 | Publish appointment hours and remove own patterns | `web/appointment_routes.py:availability`, `web/appointment_service.py` | Existing |
| UC-PROF-02 | Approve/decline student appointment, optional cancellation | `web/appointment_routes.py:decision/cancel`; `web/appointment_service.py` | Existing |
| UC-PROF-03 | Personal calendar blocks and own schedule | `/appointments/calendar`; `web/personal_schedule_service.py` | Existing |
| UC-PROF-04 | Accept/decline optional invitation to student room booking | `/rooms/<id>/invitation`; `web/room_request_service.py` | Existing |
| UC-PROF-05 | Relevant university calendar and notifications | `/calendar/`, `/notifications`; permission-scoped projections | Existing |
| UC-PROF-06 | Submit own Exam resource request; track outcome | Existing admin-only `/add-request` accepts `Exam`; C++ multi-room/shared-room strategies exist | **Proposed new Instructor capability** |
| UC-PROF-07 | Submit own OneTime/Recurring teaching room request | Admin-only `/add-request` supports `OneTime` and `Recurring`; C++ strategies exist | **Proposed new Instructor capability** |
| UC-PROF-08 | Submit own `CommitteeMeeting` resource request | Admin-only `/add-request` supports committee participants and specific resource; C++ checks participants | **Proposed new Instructor capability** |
| UC-PROF-09 | Read only self-owned academic requests, allocation outcome and explicit published instructor attribution | Admin request/result views exist; calendar projection exists | **Proposed role-scoped query/UI** |

## Critical domain decisions and safeguards

1. **Professor academic intake is a new permission boundary.** Add dedicated Instructor-scoped backend routes and service checks rather than exposing administrator `/add-request` or `run-allocation` UI to professors. Identity must come from the authenticated session, not a `userId` form field.
2. **Professor requests are not confirmations.** Existing engine result states (`Pending`, `Approved`, `Rejected`) must be shown accurately. Running/publishing a campus-wide allocation remains administration-only. Do not invent an approval state machine unless the application actually implements it and stakeholders approve the policy.
3. **Respect existing engine contracts.** `web/app.py:validate_request_form` and `request_record` require a `spaceId` for current `OneTime`, `Recurring`, `Exam`, and `CommitteeMeeting` forms; exams additionally require course code/name/type and room-split flag; committee meetings require at least one required participant. Do not erase a required field simply to match a mockup. If a preferred-room-only abstraction is desired, specify the adapter and test it separately.
4. **Calendar publication is independent.** The admin chooses visibility and optional Instructor attribution; unresolved academic period bindings must not be guessed. An attribution alone is not proof of course ownership.
5. **Privacy.** All new list and detail APIs must filter to authenticated own requests; block IDOR and cross-faculty access. Existing professor appointments remain participant-scoped, private student details remain private.
6. **Cancellation/revision rules for academic requests are not established by the professor use cases.** Do not create Cancel/Edit buttons that imply unsupported transactions; present them as future decisions unless separately designed and implemented.
7. **No professor room approval by default.** Room faculty reviewer is staff/admin, student organizer remains student; an invited professor has only an optional attendance response.
8. **Professor-initiated person-to-person meetings** are not yet a supported scheduling service; UC-PROF-08 `CommitteeMeeting` is an academic resource allocation request, not a clone of UC-STU-01.
9. **Do not duplicate student-portal UI components.** Reuse the shared shell, forms, status styles, calendar and notification visual language; role-sensitive navigation may differ.
10. **Keep tests.** Include existing Python/PostgreSQL, C++, browser and security regressions plus new tests for professor workflows, across multiple roles and concurrent allocation operations.

## Source paths on `main`

- [`web/security.py`](https://github.com/najib-attar/resource-allocation-system/blob/main/web/security.py)
- [`web/app.py`](https://github.com/najib-attar/resource-allocation-system/blob/main/web/app.py)
- [`web/appointment_routes.py`](https://github.com/najib-attar/resource-allocation-system/blob/main/web/appointment_routes.py)
- [`web/appointment_service.py`](https://github.com/najib-attar/resource-allocation-system/blob/main/web/appointment_service.py)
- [`web/room_request_service.py`](https://github.com/najib-attar/resource-allocation-system/blob/main/web/room_request_service.py)
- [`web/room_calendar.py`](https://github.com/najib-attar/resource-allocation-system/blob/main/web/room_calendar.py)
- [`web/university_calendar.py`](https://github.com/najib-attar/resource-allocation-system/blob/main/web/university_calendar.py)
- [`web/notification_service.py`](https://github.com/najib-attar/resource-allocation-system/blob/main/web/notification_service.py)
- [`web/equipment_service.py`](https://github.com/najib-attar/resource-allocation-system/blob/main/web/equipment_service.py)
- [`web/README.md`](https://github.com/najib-attar/resource-allocation-system/blob/main/web/README.md)
- [`docs/use-cases`](https://github.com/najib-attar/resource-allocation-system/tree/main/docs/use-cases)

## Recommended milestones

**PR-0 Student stability** — Publish Student UI-10 as a Draft PR, run hosted CI, review screenshots + feature traceability, reconcile with current `main`. Merge only after acceptance. If Professor work must start earlier, use a separate worktree with an explicit branch base; never mix unreviewed student changes with professor-only changes accidentally.

**PROF-B0 Contract audit** — Codex reads the *actual local checkout*, existing student acceptance report and all relevant services, verifies these nine use cases against HEAD, identifies proposed-versus-existing differences, and creates an implementation/permission matrix. No code rewrite yet.

**PROF-B1 Existing professor regression** — Add/strengthen tests and page links for UC-PROF-01..05; no duplicate services or role privileges.

**PROF-B2 Professor academic intake** — Implement role-scoped creation and validation for UC-PROF-06 (Exam), UC-PROF-07 (OneTime/Recurring), UC-PROF-08 (CommitteeMeeting) in small tested commits. Administrative publication stays privileged. Resolve contract gaps explicitly before touching C++ or database schema.

**PROF-B3 Professor academic read model** — UC-PROF-09 ownership-filtered list/detail and appropriate calendar links. Avoid inventing teaching assignments.

**PROF-UI** — After the backend is verified, design the professor portal in the shared Campus Space vocabulary, then implement and browser-test each page group; reuse common components rather than copy-pasting student templates.

**PROF-UAT** — Role-by-role and browser integration acceptance, hosted CI, Draft PR review. Only then declare Professor Services v1 complete.
