# Professor frontend sequence

The backend gate, minimal academic forms, tracking and administrator review are implemented. Full professor visual acceptance follows separately. Keep Student Draft PR #24's dependency explicit and inspect eventual main before preparing a professor PR. No professor push or PR is authorized.

Reuse base.html, existing panels/form grids, components/ui.html, icons, badges, tokens and page-specific scripts. Academic forms already share components/_academic_request_fields.html; no framework or duplicate scheduling service is needed. Preserve the Student shell and services.

| Group | Current state and next scope | Acceptance boundary |
|---|---|---|
| PUI-01 | Instructor navigation includes Academic Requests; add a coherent professor Home | Real destinations, no student-only services, admin controls or invented activity route |
| PUI-02 | Existing appointments/hours verified; apply shared visual components | Current revision, all required approvals, rejection/conflict/history; no peer-calendar browsing |
| PUI-03 | Personal timetable/blocks verified; visual refinement | Own blocks, confirmed commitments protected, optional invitations distinct |
| PUI-04 | Functional academic list/detail, filters/pagination/history/bindings implemented; refine presentation | Separate eligibility/allocation/calendar states, owner-only and real empty/error states |
| PUI-05 | Four functional intake forms and unpublished revisions implemented; refine field presentation | Declarations, explicit resources/slots, pending review, no reservation, published read-only explanation |
| PUI-06 | Existing calendar/Inbox verified; align shared visuals | Month/week/day/filters/privacy, no invented academic notifications or attribution entitlement |
| PUI-07 | Repeat visual and cross-role acceptance after redesign | Real PostgreSQL/C++, allowed/denied POSTs, 1440/768/390/320, keyboard, overflow, console/network, real screenshots |

Keep a single ProfessorService owner/state contract for JSON and Jinja. Minimal admin review may be refined without exposing admin controls to professors. CommitteeMeeting remains separate from appointments. Versioned replacements and academic notifications are deferred, not represented as working controls.
