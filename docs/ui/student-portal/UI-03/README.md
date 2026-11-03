# UI-03 Appointments

The approved service heading, restrained cards, blue controls, status pills and
stacking fields now cover list, new request, detail, optional invitation and
unavailable states. Shared components are opt-in for student service templates;
Home and other roles do not load `student-services.css`.

Every original appointment action, route, form field, CSRF token, revision and
permission condition is retained. Detail shows actual required-professor progress
for the current revision. Optional attendance remains distinct from organizer
reservations. The original published-availability picker and same-date manual
proposal code remain authoritative; private professor calendars are not exposed.

`tests.json` records the final automated execution. `browser-results.json` records
empty/populated/403/409 route captures at 1440, 768, 390 and 320px. Keyboard checks
include unobscured focus and native date input focus. `workflow-results.json`
records real multi-professor submission, optional invitation, recommendation
invalidation, offline failure, manual proposal, reschedule/reset, cancellation,
invitation decline and mandatory-availability rejection. No API responses are
mocked. Workflow screenshots show synthetic records in an owned PostgreSQL schema.

Changes: appointment templates and shared service base/components/stylesheet;
`base.html` only enables the opt-in heading and stylesheet. Browser scripts and
coverage documentation accompany this phase. No service or engine code changes.
