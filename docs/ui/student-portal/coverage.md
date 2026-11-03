# Student backend feature coverage

All listed actions use existing routes and services. Presentation never grants
authority: the session principal and service checks still decide. Professor,
custodian and administrator controls retain their original conditions. Tests
listed are executable regression modules, not claims that every test has run;
phase `tests.json` files record actual executions.

| Phase / screen | Existing capability and authorized student actions | Existing endpoint / service | Presentation | Regression tests |
|---|---|---|---|---|
| UI-01 Home | Five service hubs, current own appointment/room summary, optional invitations, upcoming schedule and unresolved-date warning | `student.home`; `StudentDashboardService.load` | `student_home.html`, existing student shell | `test_student_dashboard`, `test_student_portal_ui`, `test_frontend_prototype` |
| UI-01 Navigation | Home, My Activity anchor, Calendar, Inbox; own schedule, profile, CSRF logout | `student.home`, `calendar.index`, `notifications.index`, `appointments.calendar`, `logout` | `_navigation.html`, `_account_controls.html` | `test_student_portal_ui`, `test_identity_sessions`; browser controls |
| UI-02 Login | Provisioned username/password, validation, CSRF, session revocation, safe next URL and role redirect | `login`, `logout`; `AccountService`, `security.py` | `login.html`, `login.css`, `login.js` | `test_identity_sessions`, `test_frontend_prototype`; real browser login/logout |
| UI-03 Appointment list | Own organized appointments and optional invitations; all statuses/history still accessible | `appointments.index`; `AppointmentService.list_for` | `appointments.html` | `test_appointments`, `test_frontend_prototype` |
| UI-03 New appointment | Faculty, multiple required professors, optional students, purpose, duration, one date | `appointments.new`; `AppointmentService.directory/submit` | `appointment_new.html`, `appointments.js` | `test_appointments`, `test_appointment_protocol`, `test_frontend_prototype` |
| UI-03 Available times | Ranked feasible recommendations, same-date manual proposals, invalidation on changed inputs, loading/empty/network/conflict states | `appointments.times`; `AppointmentService.evaluate`; authoritative C++ engine | Time choices, manual time, live state | `test_appointments`, `test_appointment_protocol`; real browser workflow |
| UI-03 Appointment detail | Participant-scoped purpose/time/status, revision-specific required-professor decisions, optional invitation status | `appointments.detail`; `AppointmentService.detail` | `appointment_detail.html` | `test_appointments`, `test_notifications` |
| UI-03 Appointment actions | Organizer reschedule resets approvals; authorized cancellation; invitee decline; retained history | `appointments.reschedule/cancel/decline`; matching service methods | Existing CSRF/revision forms, progress and history | `test_appointments`, `test_identity_sessions`; browser mutation checks |
| UI-04 Room list | Organizer requests, registered-participant access, optional invitations, recurring summary | `rooms.index`; `RoomRequestService.list_for` | `room_requests.html` | `test_room_requests`, `test_recurring_rooms`, `test_resource_feedback` |
| UI-04 New/revised room | Activity, headcount, purpose/description/club, actual registered students, optional professors, faculty/building/facilities, same rules on revision | `rooms.new/revise`; `RoomRequestService.directory/submit` | `room_request_new.html`, `rooms.js` | `test_room_requests`, `test_recurring_rooms` |
| UI-04 Room selection | Ranked eligible rooms, explicit alternative-time selection, recheck on input changes and submission, invalid/conflict states | `rooms.candidates`; `RoomRequestService.recommend` | Candidate cards, selected room and messages | `test_room_requests`; browser candidate workflow |
| UI-04 Recurring rooms | Explicit configured semester, weekdays/range/time, all-required or partial approval consent, complete dated preview | `rooms.candidates/new`; recurrence service | `_recurrence_fields.html`, `recurrence.js` | `test_recurrence`, `test_recurring_rooms` |
| UI-04 Room detail | Exact room/time/facilities, assigned faculty progress, explanation, registered participants, optional invitations and history | `rooms.detail`; `RoomRequestService.detail` | `room_request_detail.html`, activity history | `test_room_requests`, `test_recurring_rooms` |
| UI-04 Room actions | Organizer cancel/revise; allowed future-occurrence cancellation; eligible report link; staff decisions and professor responses retain permissions | `rooms.cancel/cancel_occurrence/revise/decision/invitation`, `feedback.new` | Existing conditional CSRF/revision forms | `test_room_requests`, `test_recurring_rooms`, `test_resource_feedback` |
| UI-04 Availability | Authorized busy/free date query, disabled-room and unresolved-calendar warnings; no private event titles | `rooms.availability`; `RoomRequestService.availability` | `room_availability.html` | `test_room_requests`, `test_calendar_loading` |
| UI-04 Room waiting entry | Unavailable eligible request, explicit owning faculty and current policy consent; recurring requests excluded | `rooms.new` action `wait`; `WaitingListService.join_room` | Contextual waiting fieldset | `test_waiting_lists`, `test_recurring_rooms` |
| UI-05 Equipment list/catalog | Own loans/requests, eligible types/specifications, exact quantities, faculty, availability/pickup/max duration | `equipment.index/catalog`; `EquipmentService.list_for/catalog/directory` | `equipment_requests.html`, `equipment_catalog.html` | `test_equipment`, `test_equipment_web` |
| UI-05 Borrow form | Purpose/notes, pickup/due, exact JSON requirements, explicit recommendations/alternatives; complete quantity only | `equipment.catalog`; `EquipmentService.recommend/submit` | Existing form, `equipment.js` | `test_equipment`, `test_equipment_web` |
| UI-05 Recurring equipment | Explicit semester and approval consent, signed complete dated preview, separate physical loans, changed-preview invalidation | `equipment.catalog`; recurring equipment service | Recurrence form/preview | `test_recurring_equipment`, `test_recurrence` |
| UI-05 Loan details | Borrower/custodian-scoped status, assets/conditions, pickup/actual handover, actual partial/full returns, overdue warning | `equipment.detail`; `EquipmentService.detail` | `equipment_detail.html` | `test_equipment`, `test_equipment_web`, `test_recurring_equipment` |
| UI-05 Borrower actions | Cancel permitted pickup(s), express return intent, request extension of collected loan/occurrence; extension decisions visible | `equipment.transition` cancel/cancel-occurrence/intend-return/extension | Existing conditional forms | `test_equipment`, `test_equipment_web`, `test_recurring_equipment` |
| UI-05 Handover and returns | Students see information; physical handover, inspection and extension approval remain custodian-only | `equipment.transition` approve/reject/handover/return/approve-extension/reject-extension | Original permission guards retained | `test_equipment`, `test_equipment_web`, `test_identity_sessions` |
| UI-05 Waiting/reporting | Eligible unavailable exact request can join; actual borrowers can report | `equipment.catalog` wait, `feedback.new`; waiting/feedback services | Consent and report links | `test_waiting_lists`, `test_resource_feedback` |
| UI-06 Waiting overview | Own queues, contextual position, current policy, no-notice configuration warning, authorized recheck | `waiting.index/refresh`; `WaitingListService.list_for/process` | `waiting_lists.html` | `test_waiting_lists` |
| UI-06 Queue detail | Exact requirements/interval, consent/version/time, preapproval distinct from assignment, explanation/history | `waiting.detail`; `WaitingListService.detail` | `waiting_detail.html` | `test_waiting_lists` |
| UI-06 Queue actions | Withdraw pending/preapproved freely; assigned reservation link; staff preapproval stays staff-only | `waiting.cancel/review`; service guards | Existing CSRF forms | `test_waiting_lists` |
| UI-06 Policy | Actual configured minimum notice, FCFS contextual limits, eligibility/privacy, no invented default | `waiting.policy`; `WaitingListService.policy` | `waiting_policy.html` | `test_waiting_lists` |
| UI-07 Report history | Own private reports with status/category/kind/resource filters; latest 200; staff inbox only when authorized | `feedback.index`; `FeedbackService.list_for/can_manage` | `feedback_list.html` | `test_resource_feedback` |
| UI-07 Eligible report | Booking/loan-scoped eligible resources, problem/improvement/general, active-use limits, urgent safety concern, idempotent submit | `feedback.new`; `FeedbackService.context/submit` | `feedback_new.html` | `test_resource_feedback` |
| UI-07 Report details/actions | Private original/staff response, related usage, reporter clarification in allowed states, revision/idempotency/history | `feedback.detail/update`; `FeedbackService.detail/update` | `feedback_detail.html` | `test_resource_feedback`, `test_notifications` |
| UI-08 University calendar | Month/week/day, previous/today/next/date, audience/category/state filters, published academic details, warnings and distinctions | `calendar.index/academic`; `UniversityCalendarService` | `university_calendar.html`, `_calendar_event.html`, `calendar_academic_detail.html` | `test_university_calendar`, `test_calendar_loading` |
| UI-08 Personal timetable | Own explicitly dated commitments, selected month/week, optional invitations, weekend events, unresolved warning | `appointments.calendar`; `PersonalScheduleService` | `appointment_calendar.html`, `_personal_timetable.html` | `test_personal_schedule`, `test_calendar_loading` |
| UI-08 Personal blocks | Create/remove only own exact-interval blocks; existing conflict validation | `appointments.calendar` POST block/unblock; `AppointmentService.block/unblock` | Existing CSRF forms | `test_appointments`, `test_personal_schedule` |
| UI-08 Inbox | Own latest 100 updates, authorized destinations, read/unread, per-item/all-through-ID mark read, private feed | `notifications.index/feed/read`; `NotificationService` | `notifications.html`, `_notification_items.html`, `notifications.js` | `test_notifications`, `test_identity_sessions`; real browser persistence |
| UI-09 Integration/errors | All student routes reachable; escaped data, backend errors, visible focus, scoped CSS, mobile/tablet/desktop, other roles | All above; error templates; original security and services | Shared service components and phase browser reports | Full Python regression; C++ regression; browser route/keyboard/overflow checks |

## Deliberately deferred

- Unified My Activity endpoint: not approved. Existing scoped Home anchor and all
  service lists remain available; no invented aggregation or update timestamps.
- Standalone published office-hours browser: future feature. Feasible times in
  the existing appointment form are supported; private professor calendars remain
  inaccessible.
- Registration, password recovery, email/availability alerts, public personal
  cost settings and CDMCS activation: no existing authorized student contract.
- The prototype state gallery is a reference, not an application route. Real
  forms and existing service errors provide actual empty/invalid/conflict states.
