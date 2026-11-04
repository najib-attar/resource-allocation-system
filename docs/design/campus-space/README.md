# Campus Space — Student Portal Design Pack

**Version:** Design reference v1, 3 November 2026. **Scope:** Student-facing website and sign-in, *not professor/staff administration*. This is a static, interactive design prototype containing **24 individual screens**. No backend actions, accounts, CSRF, notifications or bookings are connected. All names, dates and statuses are invented for visual review.

## Where to put the files

Use the frontend Codex worktree, not the CDMCS worktree. Unzip this package into:

`C:\Users\najee\Desktop\resource-allocation-frontend\docs\design\campus-space\`

This is design documentation. **Do not** move `index.html` into `web/templates`, copy fake data into PostgreSQL, or make this the real Flask app. Keep the reference as a local folder first; check changes before committing design-only assets. Previous Concept 04 and Login v1 references are retained separately under `reference-previous/` for comparison.

Open `index.html` in Chrome or Edge. Use the page links and browser mobile emulation to review screens. The buttons are intentionally nonmutating; they display prototype notices rather than submitting university requests.

## Approved information architecture

Main nav: Home / My Activity / Calendar / Inbox. Services appear **once** on Student Home: Appointments, Rooms, Equipment, Waiting lists, Feedback. Each has its own dedicated hub and detailed screens. No numbered service cards. Calendar preview is secondary, not the entire home.

## Groups & feature coverage

| Group | Required pages & functionality | Key restrictions |
|---|---|---|
| Login | Username/password, CSRF, field and server errors, authentication & role redirect | No signup or invented password recovery |
| Student Home | Five services, authorized request summaries, appropriate meeting statuses, compact calendar preview | No fake production metrics; no duplicate service navigation |
| My Activity | Cross-service request summary and links to detailed records | **Proposed UI aggregation**, not an existing backend route; provide existing links until explicitly implemented |
| Appointments | List, book with one/multiple professors, faculty selection, optional student invitees, same-date feasible time selection, manual proposal, approval progress, participant-scoped details, invitation decline, organizer reschedule/cancel, history | No professor private schedule; all required professors approve same revision; pending is not booked; invitees do not block |
| Rooms | Requests list, request type, capacity, facilities, faculty/building preferences, actual student participants, optional professor invitations, ranked suitable rooms, recurrence/occurrence approval, room details, cancellation, busy/free room availability, eligible waiting-list entry | No presumption an unbound legacy calendar is free, no booking without review |
| Equipment | My loans, pickup/due times, catalog, quantities, exact specs, owned-faculty selection, recurring borrowing/approval mode, alternatives, custodian review, asset identifiers, physical handover/inspection, partial returns, condition, extensions, overdue, cancellations, eligible waiting-list | A due date is **not** a physical return; staff-only actions must not appear for student |
| Waiting lists | List/details, current policy consent, review/preapproval, contextual positions, withdrawal without penalty, recheck, confirmed assignment link, policy and timing limitations | Preapproval does not reserve; no invented minimum advance-notice default |
| Feedback | Private reports tied to eligible resource usage, category, urgency, details, filters, clarification, history, staff response | No report for unrelated resources; student cannot use staff-only resolution controls |
| Calendar | Unified month/week/day, filters, authorized events, status distinctions, own timetable, personal block creation/removal, ambiguity warnings | No disclosure of others' private details; equipment reminders not busy time |
| Inbox | Read status, notifications, authorized destinations, mark-all-read | No fabricated email or availability alerts |
| State gallery | Loading, empty, pending, unauthorized, stale recommendation, unresolved calendar, error, offline | Implement real errors/validation; no fake success |

## Implemented versus proposed

Most service-specific routes and forms already exist. `My Activity` as a cross-service backend endpoint and a standalone student-facing "Browse professor office hours" view are **not established**. The existing appointment form **does** compute feasible times using published professor hours. Personal cost preferences have no public settings UI or optimizer activation. Keep these explicitly future-only until authorized.

## Implementation order AFTER design approval

**UI-01:** Student Home + appropriate student-only navigation. **UI-02:** Minimal Login. **UI-03:** Appointments hub, new booking, detail, invitations. **UI-04:** Rooms hub, request, detail, busy/free and recurrence. **UI-05:** Equipment hub, catalog, detail and loan states. **UI-06:** Waiting lists and policy. **UI-07:** Feedback/reporting. **UI-08:** Calendar, personal schedule and Inbox. **UI-09:** Cross-service activity consolidation (only if backend contract approved), integration/accessibility review.

Each implementation task should be derived from `screen_inventory.csv` plus existing Flask route, Jinja template, service, authorization matrix and tests. One PR per bounded group; never implement all 24 screens in one PR. Sign-in & common components can be parallelized only when two worktrees don't edit shared files concurrently.

## Design-to-code acceptance checklist

- Dynamic data from authorized PostgreSQL read models. Never hardcode sample counts, identities or dates from the prototype.
- Preserve all existing POST/CSRF, version checks, interval checks, locking and business rules.
- Keep unsupported future features visibly distinct or omit them in production.
- Verify desktop 1440/1024, tablet 768, mobile 390/320 and keyboard navigation.
- Verify status wording and permission-specific available actions in every lifecycle.
- Preserve professor/staff/admin views, tests and accessibility expectations. Avoid global CSS changes and extra frameworks.
- Run Python/PostgreSQL, C++, relevant synthetic calendar and security regression checks. No production DB migrations for frontend redesign.
- Provide real browser screenshots and focused commits; review before push/PR/merge.

## Files

- `index.html` — complete static multi-screen design browser.
- `screen_inventory.csv` — each screen, backend route and implementation constraints.
- `README.md` — this document.
- `reference-previous/` — earlier approved homepage/login direction to compare.
- `previews/` — sample desktop and mobile screenshots from the standalone design browser.
