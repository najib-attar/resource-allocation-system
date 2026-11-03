# Student Portal acceptance report

**READY FOR STUDENT PORTAL ACCEPTANCE REVIEW** — 3 November 2026, Europe/Istanbul. Student Services v1 is ready for final user acceptance testing.

Worktree: `resource-allocation-frontend`; branch: `design/student-portal`. Starting HEAD `e01eba6` was clean. Existing UI-01 commits and historical work were preserved. The approved pack was supplied as an extracted folder and copied to `docs/design/campus-space/`; its fictional examples and proposed features were treated as reference data, not backend instructions.

## Completion and local phase commits

| Phase | Group | Status | Executed Python tests | Local commit |
|---|---|---|---|---|
| UI-01 | Home and navigation | Complete | 32 passed | `548d69c26a4aa1758a14c2302e51db333d5e4241` |
| UI-02 | Minimal Login | Complete | 31 passed | `42f3a926e7627f51af5e89d3c7c80e30c06a03e8` |
| UI-03 | Appointments | Complete | 49 passed | `caf972b94b8f3d653cf3fef7466eb70f2c9ef0fd` |
| UI-04 | Rooms | Complete | 68 passed | `581e9b08ec4753d0be32cbe9f50a60eca2e240e8` |
| UI-05 | Equipment | Complete | 52 passed | `e7c5aad4df1cdce12da3b6593a8b597d466d5fef` |
| UI-06 | Waiting Lists | Complete | 49 passed | `84d649ba19c0037b0c9b7106e197934b080091e6` |
| UI-07 | Feedback and Issues | Complete | 31 passed | `cad6b8d8411d1993d8f13de27d3bdd076300e6ff` |
| UI-08 | Calendar, My Schedule and Inbox | Complete | 50 passed | `2d745fadf9f16dde5dfc40137e042e36de654be8` |
| UI-09 | Final integration | Complete | 613 passed, 1 expected skip | `d060c7a350dc9bdd4b045b399043693d12bb2042` |

Phase counts overlap; they are not a unique-test total. [Full commit metadata](commits.json) records each phase SHA. The final acceptance-packet commit follows the UI-09 code commit; its SHA is the branch HEAD. No push, pull request, merge or deployment was performed.

## Backend feature coverage

- [All 24 approved screen references](screen-coverage.md), including existing Home activity and real state components.
- [Action-level feature matrix](coverage.md): capabilities, authorized actions, actual routes/services, frontend components and verifying tests.
- [All 68 Flask routes](UI-09/routes.md), including 47 service rules and their role boundaries.
- [Form and protected-source audit](UI-09/contracts.json): no original named form control removed; protected services, authentication, persistence, migrations, C++ and CDMCS paths unchanged.

All existing student capabilities identified in the route/service/template/test audit remain accessible. Staff-only approval, physical handover, inspection and resolution stay staff-only. Mandatory availability, approval invalidation, recurring consent, actual partial returns, waiting-list preapproval, report eligibility and private calendar scope remain enforced by their existing services. `web/app.py` changes only student error presentation, retaining status codes, method headers, CSRF rejection and Retry-After.

## Executed tests and real-app verification

Full regression: **614 run, 613 passed, 1 expected platform skip, 0 failures/errors**, across 47 modules. Discovery and execution counts match. No database tests skipped. Elapsed: **1,551.08 seconds**. The sole skip is `test_linux_execute_permission_is_checked`: "POSIX permission check runs on Linux." This run used Windows.

- [Exact full results and module counts](UI-09/tests.json); [every executed test name/result](UI-09/tests.txt).
- Real PostgreSQL workflows, concurrency, migrations in owned test schemas, backup/restore (4), role/session/privacy/CSRF and all student service lifecycles ran.
- C++: **192 passed, 0 failed**; both clean-slot and normal-dataset runtime smokes passed. [Full output](UI-09/cpp-tests.txt).
- Final Edge/Chromium browser audit: **182 views, 1611 keyboard steps, 0 JavaScript errors**. [Exact results](UI-09/browser-results.json).
- Live request-boundary observations verified actual loading messages, busy state, cleared selections and disabled submit/refresh controls before unchanged real requests completed; no response mocks or delays. [Loading evidence](UI-09/loading-results.json).
- Phase browser flows exercised submission, recommendations, stale/offline states, rescheduling/reset, invitations, revisions, cancellation/occurrences, partial returns/extensions, queue withdrawal and real assignment, private reporting/clarification/resolution, filters, personal blocks and persisted notification actions.

The isolated review servers were stopped. Eight uniquely owned review schemas from this task were removed after ownership and exact test-database checks; unrelated schemas and operational databases were preserved. [Cleanup evidence](UI-09/cleanup.json). An unreadable pre-existing build artifact was preserved separately while unchanged C++ sources were rebuilt. An initial waiting-list launcher referenced a nonexistent class; the corrected complete 49-test rerun passed and is the reported result.

## Accessibility and responsiveness

Student views passed at **1440, 768, 390 and 320px**, with no horizontal page overflow. Complete main-content keyboard traversal, visible/unobscured focus, form labels, one main heading, skip navigation and four primary destinations passed. Professor (9), staff (11) and administrator (7) views were checked at desktop and 390px, including original shells and mobile drawer/Escape/focus.

Tablet/mobile calendars use the existing authorized entries in an agenda; desktop keeps hourly views. Asset tables preserve every column in labeled keyboard-scrollable regions. Compact calendar notes keep optional invitations and equipment reminders distinct from personal commitments. Status meanings are expressed in text. Input/secondary-control boundaries measure 3.34:1 against white and focus outlines 5.19:1; sampled text/status pairs are recorded in [contrast evidence](UI-09/contrast.json).

## Screenshots

**272 real application captures**, with synthetic accounts/records in owned PostgreSQL schemas; no prototype screenshots are counted.

- [Complete screenshot gallery](screenshots.md); [dimensions and SHA-256 inventory](screenshots.json).
- Current [Home desktop](UI-09/final-home-1440.png), [Home 320px](UI-09/final-home-320.png), [Login](UI-09/final-login-390.png), [My Schedule](UI-09/final-schedule-390.png).
- [Appointment approval progress](UI-03/appointment-detail-390.png), [room candidates](UI-04/ranked-room-candidates-workflow.png), [partial-return/extension](UI-05/partial-return-and-extension-workflow.png), [real waiting assignment](UI-06/waiting-assigned-390.png).
- [Staff response to private feedback](UI-07/feedback-staff-response-workflow.png), [mobile calendar](UI-08/calendar-week-390.png), [read/unread Inbox](UI-08/inbox-read-and-unread-workflow.png), [actual service failure](UI-09/service-unavailable-390.png).

The fixture calendar week is 7–13 January 2030; displayed current dates/audit timestamps use the running clock. Historical physical handover/return fixtures use seeding clocks only, never a mocked application clock while the server runs.

## Missing or deferred functionality

No identified existing student backend capability is intentionally omitted. The following remain outside the authorized backend scope:

- A unified cross-service My Activity endpoint. The existing Home anchor summarizes supplied appointment/room data; complete equipment, queue and feedback activity remains in the real service hubs and histories.
- A standalone student office-hours browser. The actual appointment form still computes feasible times from published hours; private professor calendars are not exposed.
- Registration, password recovery, email/availability alerts, public cost-preference settings and CDMCS activation.
- A standalone state-gallery route. Actual empty/loading/success/error/forbidden/offline states are implemented in the real pages.

## Files changed

[Complete inventory of 528 changed files](changed-files.csv), including imported reference assets, all screenshots and exact test reports. Application presentation files are listed below; no database model, schema, C++ engine or business-service file changed.

| File |
|---|
| [web/README.md](../../../web/README.md) |
| [web/app.py](../../../web/app.py) |
| [web/static/equipment.js](../../../web/static/equipment.js) |
| [web/static/feedback.js](../../../web/static/feedback.js) |
| [web/static/login.css](../../../web/static/login.css) |
| [web/static/login.js](../../../web/static/login.js) |
| [web/static/rooms.js](../../../web/static/rooms.js) |
| [web/static/student-services.css](../../../web/static/student-services.css) |
| [web/templates/_personal_timetable.html](../../../web/templates/_personal_timetable.html) |
| [web/templates/appointment_calendar.html](../../../web/templates/appointment_calendar.html) |
| [web/templates/appointment_detail.html](../../../web/templates/appointment_detail.html) |
| [web/templates/appointment_error.html](../../../web/templates/appointment_error.html) |
| [web/templates/appointment_new.html](../../../web/templates/appointment_new.html) |
| [web/templates/appointments.html](../../../web/templates/appointments.html) |
| [web/templates/base.html](../../../web/templates/base.html) |
| [web/templates/calendar_academic_detail.html](../../../web/templates/calendar_academic_detail.html) |
| [web/templates/calendar_error.html](../../../web/templates/calendar_error.html) |
| [web/templates/components/_calendar_event.html](../../../web/templates/components/_calendar_event.html) |
| [web/templates/components/_notification_items.html](../../../web/templates/components/_notification_items.html) |
| [web/templates/components/student_services.html](../../../web/templates/components/student_services.html) |
| [web/templates/equipment_catalog.html](../../../web/templates/equipment_catalog.html) |
| [web/templates/equipment_detail.html](../../../web/templates/equipment_detail.html) |
| [web/templates/equipment_error.html](../../../web/templates/equipment_error.html) |
| [web/templates/equipment_requests.html](../../../web/templates/equipment_requests.html) |
| [web/templates/feedback_detail.html](../../../web/templates/feedback_detail.html) |
| [web/templates/feedback_list.html](../../../web/templates/feedback_list.html) |
| [web/templates/feedback_new.html](../../../web/templates/feedback_new.html) |
| [web/templates/login.html](../../../web/templates/login.html) |
| [web/templates/notifications.html](../../../web/templates/notifications.html) |
| [web/templates/room_availability.html](../../../web/templates/room_availability.html) |
| [web/templates/room_request_detail.html](../../../web/templates/room_request_detail.html) |
| [web/templates/room_request_new.html](../../../web/templates/room_request_new.html) |
| [web/templates/room_requests.html](../../../web/templates/room_requests.html) |
| [web/templates/student_error.html](../../../web/templates/student_error.html) |
| [web/templates/student_service_base.html](../../../web/templates/student_service_base.html) |
| [web/templates/university_calendar.html](../../../web/templates/university_calendar.html) |
| [web/templates/waiting_detail.html](../../../web/templates/waiting_detail.html) |
| [web/templates/waiting_lists.html](../../../web/templates/waiting_lists.html) |
| [web/templates/waiting_policy.html](../../../web/templates/waiting_policy.html) |

Review/test tools and UI contracts are in `tests/test_student_portal_ui.py` and `tests/ui/`; their complete paths are in the file inventory. Shared student components replace repeated styling, page scripts retain existing backend contracts, and no frontend framework or application dependency was added.

## Remaining acceptance work and risks

No blocking security, functionality or integration failure was found in the executed checks. Final review on the university’s target physical devices and assistive technologies remains a user acceptance task; these checks are not an accessibility certification. Deployment configuration and operational rollout remain separate and unauthorized by this task.

Student Services v1: **ready for final user acceptance testing**.

**READY FOR STUDENT PORTAL ACCEPTANCE REVIEW**
