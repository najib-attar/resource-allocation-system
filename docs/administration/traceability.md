# Administration backend audit and traceability

Reviewed baseline: `aae966bf8fa6390348c6e6a2d53a24faf6c0ab70` (beta,
Student #24, Professor #25, documentation #26). Dedicated administration worktree;
existing four worktrees and local demo data preserved. Requirements are in
[the specification](specification.md).

| UC | Existing route → authoritative service | Permission and storage | Engine / regression coverage | Required administration work |
| --- | --- | --- | --- | --- |
| 01 Home | New `/administration/` → AdminDashboardService | Active administrative account; scoped operational queues; repeatable-read PostgreSQL | No engine on dashboard reads; new dashboard tests | Add bounded composition and Home |
| 02 Directory | `/users`, `/spaces` → DatabaseResultAdapter; `/rooms/configuration` → RoomRequestService.directory/configure_room/configure_approver | Technical admin directory; configuration admin; closures also current designated manager. User/Resource/RoomPolicy/FacultyRoomApprover/RoomClosure | `test_room_foundation`, `test_room_requests`, existing Flask adapter tests | Reuse read/search and existing policy controls; general CRUD deferred |
| 03 Access | Trusted `scripts/manage_accounts.py` → AccountService.provision(reset=True)/identity/revoke_session | Operator CLI, existing identities; LoginAccount, LoggedOutSession; no web grant endpoint | `test_identity_sessions`, `test_logout_sessions`, `test_logout_migration` | Verify unchanged; browser account console deferred |
| 04 Eligibility | `/academic-eligibility/`, `/<id>` → EligibilityService.list_for/detail/decide/history | Active admin, reviewer ≠ owner; state + request row locks, request revision/review version; RequestEligibility/EligibilityEvent/RequestHistory | No engine on decisions; `test_academic_eligibility`, `test_eligibility_migration` | Preserve; compose queue, improve presentation |
| 05 Allocation | `/set-strategy`, `/run-allocation`, `/run-allocation-now/<request_id>`, `/requests`, `/request/<id>`, `/allocation-summary`, `/schedules` → Repository.set_strategy/start_run/publish_run, execute_allocation | Technical admin HTTP; ApplicationState revision lock; only current Eligible input, legacy review barrier; AllocationRun/RequestDecision/Allocation/history | EngineGateway canonical snapshot → JSON v1 → C++17; validated atomic result persistence. `test_academic_eligibility`, `test_postgres_workflow`, gateway/Flask tests | Keep engine strategies and transactions; clearer allocation workspace |
| 06 Calendar | `/appointments/calendar-setup` → AppointmentService.bind_legacy; `/calendar/publications` → UniversityCalendarService.publications/publish | Admin, explicit dates/bindings; AcademicPeriod/LegacyCalendarBinding and ResourceRequest publication fields; no inferred course membership | Existing engine results projected, no new allocation; `test_university_calendar`, `test_room_foundation`, `test_professor_portal` | Reuse controls; explain allocation vs dated audience publication |
| 07 Rooms | `/rooms/`, `/<id>`, `/<id>/decision`, occurrence cancellation, `/configuration` → RoomRequestService | Designated **current** faculty approver AND stored request approver for decisions; no blanket admin approval. StudentRoomRequest/RoomReservation/RoomEvent/series records | Room JSON evaluation/recheck + transaction revision; `test_room_requests`, `test_recurring_workflows` | Authorized queue/navigation; preserve recurrence, participants, idempotency |
| 08 Equipment | `/equipment/`, `/<id>/<action>`, `/inventory/<faculty_id>`, `/custodians` → EquipmentService | Current designated custodian for approvals/custody; existing admin configuration only. BorrowRequest/BorrowItem/EquipmentReservation/EquipmentUnit/EquipmentEvent | Equipment JSON availability; verified handover/partial returns remain separate; `test_equipment`, `test_equipment_web`, `test_waiting_lists` | Scoped queue/inventory links; no global custody grant |
| 09 Waiting/recurrence | `/waiting-lists/`, `/<id>/review`, `/refresh`, `/priority/<kind>/<id>`, `/configuration` → WaitingListService | Current responsible faculty reviewer/custodian; admin policy; explicit consent/notice/semester/quotas. WaitingListEntry/ApplicationState/AcademicPeriod/ReservationSeries/ReservationOccurrence and audit | Existing room/equipment matching and locks; `test_waiting_lists`, `test_recurring_workflows` | Compose scoped pending entries and policy links |
| 10 Issues | `/feedback/?scope=managed`, `/<id>`, `/<id>/update` → FeedbackService.list_for/detail/update | Current resource responsibility via managed_scope; reporter remains private. ResourceFeedback/FeedbackEvent/Notification | No automatic closure/cancellation; `test_resource_feedback` | Scoped issue summary, authorized navigation |
| 11 Reports | Existing `/raw-data`, allocation/service histories; new `/administration/reports` read aggregation | Admin; bounded dates/domain and exact denominators; operational totals retain faculty scope; no broad PII export | No engine or writes; new administration tests | Add documented read-only reporting, no new reporting tables |
| 12 Inbox | `/notifications`, read/read-all → NotificationService | Addressed recipient plus current parent visibility, no blanket administrator delivery. Notification/source events | `test_notifications`, `test_logout_sessions` | Reuse existing Inbox; academic work queue is separate |

## Verified architectural boundaries

- `security.py` authenticates before routes and checks CSRF for every mutation.
  Services recheck current identity and authority; dashboard authority must do so too.
- Eligibility decisions lock ApplicationState before requests. Database triggers
  invalidate approvals on material changes and prevent active-publication input edits.
- Repository snapshots filter current Eligible revisions, assert outstanding legacy
  reviews, and use canonical guarded input. Engine work occurs outside transactions;
  publication rechecks revision proofs and preserves the previous run on failure.
- Calendar publication uses explicit applicability. Reviewing or rejecting an old
  published request does not remove existing allocations or calendars.
- Room approval, equipment reservation, physical custody and queue preapproval have
  distinct states. Aggregation must not collapse them into a generic booking count.
- Dashboard source queries must share one read-only repeatable-read transaction.
  Reuse scope helpers; do not call full unbounded list services then slice in Python.

## Decisions and deferred scope

No policy decision is needed for read-only composition. UC-03's browser console,
arbitrary resource editing, PII exports, academic notifications, published version
replacement/cancellation, SIS import and CDMCS activation remain explicitly deferred.
No schema, C++ protocol, scheduling semantics or permissions change is planned.

## Verification status

ADM-B0 is a source/contract audit, **not** a test pass. Focused backend executions,
full acceptance and browser evidence are recorded in subsequent iteration reports.
