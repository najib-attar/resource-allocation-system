# Campus Space / Student Portal — Concept 04 implementation handoff

## Status
Approved **visual direction**, not final pixel-perfect UI. This reference is a standalone static HTML interaction demo, **not** production source code or a real backend. All example activity, counts, names, dates and status records are fictional. Don't copy them into the application as real data.

## UX structure
- Main navigation: **Home, My Activity, Calendar, Inbox**. Do not duplicate individual services in the main navigation.
- Home service discovery: **Appointments, Rooms & spaces, Equipment borrowing, Waiting lists, Feedback & issues**. No decorative numbering.
- Home secondary content: recent authorized activity and a small calendar preview; calendar must not dominate the page.
- Appointments is one hub encompassing creation, existing appointments, required-professor approval status, invitations, rescheduling/cancellation. Students may learn feasible meeting times through existing authorized scheduling endpoints. Do not show a professor's private calendar. A standalone published-office-hours browser is proposed, not implemented.
- Calendar and Inbox are not separate resource-request services; they are cross-service views.
- Desktop layout is left navigation + service area + activity/planning. Mobile uses accessible bottom navigation and stacked services/activity.

## The codebase is authoritative
Existing implementation uses Flask/Jinja, scoped JS/CSS, CSRF, PostgreSQL and C++ scheduling engines. Preserve existing routes, permissions, request lifecycle and output exactly. Do not switch to React, replace templates wholesale, or introduce a second calendar engine. Inspect current `web/templates/student_home.html`, `web/templates/base.html`, `web/templates/components/_navigation.html`, account controls, `web/static` files and backend read models. Existing `/appointments/`, `/rooms/`, `/equipment/`, `/waiting-lists/`, `/feedback/`, `/calendar/`, notifications must stay usable.

## First PR: Student shell + Home only
1. Inspect current frontend and identify what the prototype assumes but the actual backend can/cannot provide.
2. Implement scoped styling (avoid global CSS overrides) and minimal Jinja template changes for Student Home; preserve the existing shared shell for professor/staff/admin users.
3. Replace all fictional activity/status/counts with existing real, scoped read-model data; show honest empty/unavailable states. If unified cross-service My Activity requires an aggregate backend, **do not invent it in the first PR**: link users to existing authenticated service list pages and document Phase 2.
4. Link all five service tiles to their existing authorized destination pages. No fake modal or inoperative search. Hide/remove search unless a real search endpoint exists.
5. Keep real appointment confirmation and room-reservation semantics: pending != booked. Optional invitations != confirmed organizer booking. Equipment reminders != occupied calendar time. Unresolved calendar applicability must remain visible as a warning.
6. Preserve authentication, logout/CSRF, notifications, URL endpoints, status/history details, controls and accessibility.
7. Test responsive 1440, 768, 390, 320 widths; keyboard navigation and focus, empty states, no horizontal overflow, cross-role isolation, backend regression tests.
8. Keep PR small; report any missing fields and proposed future PRs before broadening scope. No deployment or merge without approval.

## Suggested later PRs, *after* first PR approval
- My Activity / aggregated requests view if explicitly approved with backend privacy checks, or keep existing separate lists if unnecessary.
- Appointment hub/list/detail/form styling; published office hours browser only as separate privacy-reviewed user case.
- Room request and equipment catalog/list/detail styling.
- Waiting lists and feedback styling.
- Calendar / Inbox consistency, with role-specific regression.

## Included visual reference
`student_portal_concept_v4.html` (standalone, static interaction demonstration)
`student_portal_concept_v4_desktop.png`
`student_portal_concept_v4_mobile.png`

Review the actual HTML, not just screenshots; use it as visual guidance rather than copying the demo's data, state machine or client-side mock logic.
