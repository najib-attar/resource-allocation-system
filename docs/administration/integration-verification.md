# Administration control-to-persistence verification

Scope: the approved [UC-ADM contracts](specification.md), on the integrated beta
base `aae966b`. Repeated record links and forms use the same endpoint/permission
contract; this matrix groups those repeated controls. All active rows below are
verified functional through source tracing and automated Flask/PostgreSQL tests.
The evidence column distinguishes additional real-browser POST coverage from
backend regression coverage. It does not claim every possible input was clicked.

Every mutation passes the existing authentication and CSRF middleware, then the
source service's current identity, ownership/designation and state checks. Native
forms redirect only after successful service completion; validation errors retain
their HTTP status and show a safe message. No dashboard mutation endpoint exists.

## Home, navigation and read-only reporting

| Control / submitted parameters | Flask → service → persistence | Response / frontend result | Evidence |
| --- | --- | --- | --- |
| Home, brand, queue metric, queue select/refresh (`queue`) | GET `/administration/` → `AdminDashboardService.load` → one read-only repeatable-read transaction | SQL-bounded five items/group and scoped counts; invalid queue 400; empty state; no engine call | `test_administration`, `test_administration_ui`; UI-01 populated/empty, UI-06 |
| Academic/room/equipment/waiting/issue item links | Queue-specific `/academic-eligibility/<id>`, `/rooms/<id>`, `/equipment/<id>`, `/waiting-lists/<id>`, `/feedback/<id>` → source detail service | Current-authority detail or denied access; no alternate dashboard copy of state | Same tests; UI-02–04 |
| Service cards and configuration links | Existing service list/configuration routes in the rows below | Authorized native workspace; managed-feedback scope is explicit | UI-01–06; source route review |
| Recent run, request outcome links | GET `/administration/runs/<id>` → `run_detail`; `/request/<id>` → `DatabaseResultAdapter` | Explicit historical/active status; outcome links explain that request metadata is current | Administration tests; UI-02 replay |
| Previous/next outcomes (`page`) and segments (`allocation_page`) | `run_detail` → `AllocationRun`, `RequestDecision`, `Allocation`, `Resource` | Independent 50/100 row pages; bounded integer IDs/pages; malformed 400, absent 404 | `test_administration`, `test_administration_ui` pagination/boundary cases |
| Report domain, inclusive dates, Load (`domain,start,end`) | GET `/administration/reports` → `report` → grouped current statuses of dated source records | At most 366 days, university timezone, exact denominator/scope; empty/error states; no export or scheduling | Administration tests; UI-05 original/replay |
| Report source links | Existing allocation/service routes | Opens authoritative record/occurrence context; recurring parent counts never claim all dates approved | UI-05 and recurring regressions |
| User search and role (`q,role`), space search (`q`) | GET `/users`, `/spaces` → pinned `DatabaseResultAdapter` projection, literal case-insensitive filtering | Read-only directory; 100-character search bound, escaping, combined role filter, genuine no-result state | `test_administration_ui`; UI-03 |
| Desktop advanced navigation, mobile primary bar, account menu, skip link | Shared Jinja shell, `shell.js`, semantic details/links | Five primary administrator destinations; advanced actions reachable from Home/Academic on mobile; visible keyboard focus | UI-01–06 at all five widths; Professor cross-role audit |

## Academic eligibility, allocation and calendar publication

| Control / submitted parameters | Flask → service → PostgreSQL / C++ | Response / frontend result | Evidence |
| --- | --- | --- | --- |
| Eligibility queue, review/history links | GET `/academic-eligibility/`, `/<id>` → `EligibilityService.list_for/detail/history` → requests, eligibility/events and active decisions | Current revision, review version, reason/history and preserved-publication warning | Eligibility and migration tests; UI-02/06; legacy browser |
| Approve / reject (`revision,reviewVersion,decision,reason`) | POST review detail → `decide` → state/request locks, `RequestEligibility`, `EligibilityEvent`, request history | Redirect with committed decision; self-review forbidden; stale 409; no room allocated/released by review | Academic eligibility tests; UI-02 stale POST, UI-06 revision/rejection; legacy browser |
| Strategy selection / Save (`strategy`) | POST `/set-strategy` → `Repository.set_strategy` → `ApplicationState` input revision | Saved supported strategy; no engine call or automatic reservation | PostgreSQL workflow/concurrency, strategy tests; UI-02 replay independently checks saved value |
| Add request, Committee Meeting shortcut, conditional type/participant/slot fields | GET/POST `/add-request` → existing request parser/repository persistence | Valid supported request saved; eligibility remains separate; invalid contract shown without false success | Flask/PostgreSQL workflow tests; existing Professor browser and contract regressions |
| Run Allocation | POST `/run-allocation` → `execute_allocation` → guarded eligible snapshot → `EngineGateway` → C++ JSON v1 → `Repository.publish_run` | Validated atomic active-run replacement; pending/rejected excluded; failures keep prior run | Academic gate, PostgreSQL workflow/concurrency, gateway; UI-02/06 and legacy browser |
| Run Allocation Now for saved request | POST `/run-allocation-now/<id>` → same guarded pipeline | Revalidates complete eligible snapshot; no eligibility bypass or alternate engine | Eligibility/direct-entry tests; Professor independent browser executes this route |
| Request list/detail, summary, schedules/type selector, technical data | GET `/requests`, `/request/<id>`, `/allocation-summary`, `/schedules`, `/raw-data` → consistent database adapter | Persisted engine outcomes/segments, not fictional cached success; private technical admin interface | Adapter/Flask/PostgreSQL tests; UI-02; five-role access tests |
| Calendar applicability (`periodName,fromDate,untilDate,requestId,weekStart`) | POST `/appointments/calendar-setup` → `AppointmentService.bind_legacy` → `AcademicPeriod`, `LegacyCalendarBinding` | Explicit date binding committed; allocation rows unchanged; invalid/stale applicability refused | Calendar/foundation/Professor tests; UI-04/06 |
| Publish/private and optional instructor (`id,visibility,instructor`) | POST `/calendar/publications` → `UniversityCalendarService.publish` → request visibility/attribution, calendar revision | Explicit audience/attribution; no inferred teaching affiliation and no allocation mutation | University calendar/Professor tests; UI-04/06 committed-state checks |
| Month/week/day, previous/next/today, date/category/state/scope filters, event links | GET `/calendar/`, `/calendar/academic/<id>` → `UniversityCalendarService.load/academic_detail` → existing scoped source records | Distinct confirmed/pending/optional/reminder states; source detail rechecks privacy | Calendar regressions; UI-04/06 and retained Student/Professor browser audits |

The independent UI-06 browser creates a professor request, runs allocation while
it is unreviewed, approves, materially revises, runs again, approves the new
revision, allocates, binds dates and publishes. Independent committed reads compare
every engine snapshot's request IDs with current Eligible revisions. Rejecting the
published request leaves its allocation/calendar intact; an attempted published
revision is refused. Peer-professor access is denied. The separate legacy browser
verifies the replacement barrier before explicit individual review.

## Room and equipment operations

| Control / submitted parameters | Flask → authoritative service → persistence / C++ | Response / frontend result | Evidence |
| --- | --- | --- | --- |
| Room list/detail/availability and participant links | `/rooms/`, `/<id>`, `/availability/<room>` → `RoomRequestService` | Current designated faculty scope/participant visibility; real reservation/occurrence status | Room/foundation/recurring tests; UI-03 and Student lifecycle browser |
| Room approve/reject, all or selected dates (`revision,decision,reason,selectedDates,occurrenceIds`) | POST `/rooms/<id>/decision` → `decide` → existing C++ room/series feasibility and revision recheck → reservations/events | Confirmation only for actually approved feasible dates; conflict/stale rejection preserves existing state | Room/recurring tests; UI-03 confirmation and Student lifecycle partial/all-date checks |
| Authorized cancellation / occurrence cancellation (`revision`) | Existing room cancel routes → `cancel/cancel_occurrence` | Source authority/state rules; actual releases/history; no added administrator override | Room/recurring regressions; Student lifecycle browser |
| Faculty approver (`action=approver,faculty,approver`) | POST `/rooms/configuration` → `configure_approver` → `FacultyRoomApprover`, calendar revision | Explicit active designated account; existing reservations unchanged | Room tests; UI-06-controls actual form |
| Room policy (`action=policy,roomId,faculty,enabled,categories,restricted,allowedUsers`) | Same route → `configure_room` → `RoomPolicy`, `RoomAccess` | Existing access policy only; future confirmed reservations block incompatible edits | Room/foundation tests; UI-06-controls actual form |
| Add/remove dated closure (`action=close/reopen,roomId,start,end,reason/closureId`) | Same route → `close_room/reopen_room` → `RoomClosure` | Current authorized scope and conflict checks; no silent booking cancellation | Room/foundation tests; UI-06-controls create/delete committed checks |
| Equipment requests, catalog, own faculty inventory links | `/equipment/`, `/catalog`, `/inventory/<faculty>` → `EquipmentService` | Borrower/current-custodian permissions; condition, possession, overdue and attention states distinct | Equipment/web tests; UI-03 and Student lifecycle browser |
| Approve/reject, selected occurrences | POST `/equipment/<id>/<action>` → `decide` → existing C++ equipment/series match → reservations/events | Approval reserves units; does not mark physical collection | Equipment/recurring tests; UI-03 and Student lifecycle browser |
| Handover (`condition,occurrenceId`), verified full/partial return (`unitIds,condition,notes`) | Same transition route → `handover/return_units` → reservation handed/returned timestamps, events | Current custodian only; physical evidence remains explicit; partial-return status persists | Equipment/security tests; UI-03 and Student lifecycle browser |
| Extension approval/rejection (`extensionId`) | Transition route → `decide_extension` → `BorrowExtension`, feasibility/conflict checks and persisted due/reservations | Only current custodian; no borrower self-approval; conflict response preserves original due date | Equipment/web/recurring tests; Student lifecycle extension browser |
| Equipment cancel/occurrence actions and priority | Existing transition/priority routes → source service | Original borrower/custodian permissions; released stock can trigger existing waiting assignment | Equipment/recurring/waiting tests; UI-04 and Student lifecycle browser |
| Register type (`action=type,name,category,description,specifications,max_days,pickup,eligible_faculties`) | Inventory POST → `create_type` → `EquipmentType`/category and audit | Current owning-faculty custodian only; bounded JSON/text/numeric constraints | Equipment tests; UI-06-controls actual form and persisted specification checks |
| Register asset (`action=unit,type_id,asset_tag,condition`) | Inventory POST → `add_unit` → `EquipmentUnit`/event | Unique asset; duplicate 409 with unchanged domain state | Equipment tests; UI-03 duplicate and UI-06-controls |
| Condition (`action=condition,unit_id,condition,notes`) | Inventory POST → `set_condition` → unit/event | Current custodian, physical-hold restrictions; no invented return | Equipment tests; UI-06-controls actual form |
| Type policy (`action=policy,type_id,enabled,max_days`) | Inventory POST → `configure_type` → equipment type/event | Existing loans preserved; applies to new evaluations | Equipment tests; UI-06-controls actual form |
| Assign/replace custodian (`faculty,custodian`) | POST `/equipment/custodians` → `assign_custodian` → `EquipmentCustodian`/event | Existing administrative configuration only; former custodian immediately loses operational access | Equipment tests; UI-06-controls reassignment, denied inventory GET, restoration |

## Waiting, feedback, Inbox and shared personal actions

| Control / parameters | Flask → service → persistence | Response / frontend result | Evidence |
| --- | --- | --- | --- |
| Queue/detail/policy, Refresh | `/waiting-lists/`, `/<id>`, `/policy`; POST `/refresh` → `WaitingListService` | Scoped current review/queue position; existing service recheck may allocate eligible available stock; Home aggregation itself never rechecks | Waiting tests; UI-04 idempotent refresh |
| Preapprove/reject (`decision,reason`), permitted withdrawal | POST waiting review/cancel → `review/cancel` → `WaitingListEntry` and history | Preapproval alone reserves nothing; approved assignment requires existing availability/notice/consent rules | Waiting/recurring tests; UI-04 real stock release → assignment |
| Minimum notice (`noticeMinutes`) | POST waiting configuration → `configure_notice` → `ApplicationState` | Explicit positive notice; no guessed default | Waiting tests; UI-04, missing CSRF rejected |
| Recurring quotas/priorities (`action=reservation-policy`, four quota fields, `priorities`) | Same route → `configure_reservations` → state limits/levels | Positive explicit quotas; unset remains unset; no historical reservation rewriting | Recurring-policy tests; UI-06-controls saved values |
| Semester (`action=semester,name,start,end`) | Same route → `configure_semester` → `AcademicPeriod` | Exact named dates; mismatched existing period rejected | Recurring-policy tests; UI-04/06-controls |
| Bind legacy series (`action=bind-series,kind,requestId,periodId`) | Same route → `bind_series_semester` → `ReservationSeries` | Only a suitable existing unbound series fitting explicit semester; dates unchanged | Recurring-policy positive/negative tests; UI-06-controls real non-series rejection with unchanged state |
| Priority (`priority,reason`) | POST `/waiting-lists/priority/<kind>/<id>` → `override_priority` → parent + `ReservationPriorityOverride`/history | Current responsible actor, configured different priority and justification; no eligibility/conflict override | Recurring-policy tests; UI-06-controls real room override |
| Managed issues, status/category/resource filters, detail/history | `/feedback/?scope=managed`, `/<id>` → `FeedbackService.list_for/detail` | Current resource responsibility; other faculty and unrelated reporter details refused | Resource-feedback tests; UI-04 foreign-staff 403 |
| Staff response/status/priority (`action,revision,status,priority,response,action_key`) | POST `/feedback/<id>/update` → `update` → `ResourceFeedback`, `FeedbackEvent`, addressed `Notification` | Revision/idempotency checks; no automatic closure or inventory mutation | Feedback tests; UI-04 response, reporter clarification and stale 409 |
| Eligible own report/reporter clarification | Existing feedback new/update routes → source service context/submit/update | Original actual-use eligibility and reporter ownership; administration grants no reporter bypass | Feedback tests; retained Student lifecycle browser |
| Bell, Inbox, source link, unread count | GET notification feed/index → `NotificationService.inbox` → recipient + current parent visibility | Bounded feed; authorized source link; no academic notification invented | Notification tests; UI-05 and five-role browser |
| Read/read-all (`id` or `throughId`) | POST `/notifications/read` → `mark_read` → addressed rows only | AJAX success or native redirect; repeat is idempotent; foreign ID 403 | Notification tests; UI-05 original/replay committed checks |
| Sign out, account menu, personal appointments/schedule/blocks | Existing logout and appointment routes/services | Durable per-login logout denial; own personal permissions retained; no on-behalf-of approvals | Identity/logout/appointment tests; all-five-role logout race, Student/Professor browser |

## Explicitly unavailable controls

Browser account provisioning/privilege delegation, arbitrary resource CRUD, broad
exports, academic notification creation, academic cancellation/versioned published
replacement, optimizer activation and production database operations have no
functional placeholder buttons. Text identifies deferrals and points to supported
work queues or trusted operator guidance. Existing supported conditional controls
(such as a recurring equipment waiting action) retain their visible disabled reason.

No disconnected administration control or unresolved confirmed defect remains in
the reviewed scope. Coverage has finite synthetic inputs; deployment and
institutional policy approval remain separate from this implementation audit.
