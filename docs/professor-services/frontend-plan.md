# Professor frontend sequence — plan only

Prerequisite: review the backend acceptance report, merge/review dependent Student Draft PR #24, and resolve the eligibility gate before enabling academic intake. Reuse the Campus Space system in `base.html`, `components/student_ui.html`, existing icons, status badges, panels, form patterns, `student-portal.css` and page-specific scripts. Keep shared design corrections small; do not copy student services into a professor dashboard.

| Group | Scope and actual backend contract | Acceptance boundary |
|---|---|---|
| PUI-01 | Instructor Home and navigation: Home, Appointments, Schedule, Calendar, Inbox; Academic Requests once its read page exists | Active Instructor only; real destinations; no administrator/custodian buttons; reuse shared shell and responsive panels |
| PUI-02 | Existing `/appointments/`, detail/decision/cancellation, `/appointments/availability` hours/exclusions | Current revision, all required approvals, rejection, mandatory availability, conflict feedback, history; hours are publication to appointment matching, not a private-calendar browser |
| PUI-03 | `/appointments/calendar` personal timetable and blocks | Own blocks only; confirmed commitments cannot be overridden; distinct optional room/student invitations; no peer calendar disclosure |
| PUI-04 | Read-only My Academic Requests using the new owner list/detail API | Paginated type/status filters, loading/empty/400/403/503, active allocations and reasons/history, unresolved binding warning, no fake dates or submit button |
| PUI-05 | Exam, OneTime/Recurring teaching and CommitteeMeeting intake | **Blocked** until separately approved review schema/admin actions/snapshot gate/legacy policy are implemented and tested; then session-owned Pending submission, declarations, explicit space, real constraints and revision invalidation |
| PUI-06 | Existing university calendar, scoped academic details and Inbox | Month/week/day/filter/navigation; public attribution remains metadata; no private attribution entitlement; existing notification sources only; no academic notifications until approved |
| PUI-07 | Cross-role integration and acceptance | Real PostgreSQL persistence; allowed/rejected POSTs; all five roles; 1440/768/390/320; keyboard/focus, overflow, console/network, actual screenshots |

Each group needs a focused local commit and real Flask evidence. Do not implement a new framework, unified invented activity endpoint, registration/recovery, student borrowing/request services, private professor calendar browsing or administrator allocation UI. Reuse existing appointment, room-invitation, personal schedule and calendar services. Academic CommitteeMeeting remains separate from appointment approvals.

The new API is a service/read-model boundary, not a replacement for Jinja: future pages may call `ProfessorService` server-side and reuse its validated query contract. Keep a single implementation of owner scoping and outcome semantics. Only add JavaScript when interaction requires it.
