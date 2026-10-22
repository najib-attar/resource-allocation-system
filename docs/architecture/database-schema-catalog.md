# Physical schema catalog

Generated from SQLAlchemy metadata. `alembic_version` is migration infrastructure, not one of the 50 application tables.

All foreign keys use PostgreSQL **NO ACTION**: no implicit cascading deletion. Nullable columns are explicitly listed; all others are NOT NULL.
ORM Python defaults are not server defaults. SQL import/admin tools must supply required values unless an identity/server default is listed.

## academic_period

Explicit named calendar validity and timezone; no inferred legacy dates.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| id | integer | PK | no | identity |
| name | varchar(200) | - | no | - |
| start_date | date | - | no | - |
| end_date | date | - | no | - |
| timezone | varchar(100) | - | no | - |

- Primary key: `id`.
- Check: `start_date <= end_date`.
- Unique: `name`.

## allocation

Assigned resource/time/count, linked to exactly one run/request decision.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| id | bigint | PK | no | identity |
| run_id | bigint | FK -> request_decision.run_id | no | - |
| request_id | integer | FK -> request_decision.request_id | no | - |
| engine_id | integer | - | no | - |
| resource_id | integer | FK -> resource.id | no | - |
| day | integer | - | no | - |
| start_minutes | integer | - | no | - |
| end_minutes | integer | - | no | - |
| assigned_participants | integer | - | no | - |

- Primary key: `id`.
- Foreign key: `(resource_id) -> resource (id)`; NO ACTION.
- Foreign key: `(run_id, request_id) -> request_decision (run_id, request_id)`; NO ACTION.
- Check: `assigned_participants > 0`.
- Check: `day BETWEEN 1 AND 7`.
- Check: `engine_id >= 0`.
- Check: `start_minutes >= 0 AND start_minutes < end_minutes AND end_minutes <= 1440`.
- Unique: `run_id, engine_id`.
- Index: `ix_allocation_decision (run_id, request_id)`.
- Index: `ix_allocation_request_id (request_id)`.
- Index: `ix_allocation_resource_id (resource_id)`.

## allocation_participant

Ordered required human commitments of an allocation.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| allocation_id | bigint | PK; FK -> allocation.id | no | - |
| user_id | integer | PK; FK -> university_user.id | no | - |
| ordinal | integer | - | no | 0 |

- Primary key: `allocation_id, user_id`.
- Foreign key: `(allocation_id) -> allocation (id)`; NO ACTION.
- Foreign key: `(user_id) -> university_user (id)`; NO ACTION.
- Check: `ordinal >= 0`.
- Index: `ix_allocation_participant_user_id (user_id)`.

## allocation_run

Immutable input/build provenance and execution status for one engine batch.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| id | bigint | PK | no | identity |
| correlation_id | varchar(32) | - | no | - |
| input_revision | bigint | - | no | - |
| strategy | varchar(50) | - | no | - |
| status | varchar(20) | - | no | ORM: running |
| snapshot | jsonb | - | no | - |
| build | jsonb | - | no | ORM callable |
| engine_version | text | - | no | ORM:  |
| error | text | - | no | ORM:  |
| created_at | timestamp with time zone | - | no | now() |

- Primary key: `id`.
- Check: `input_revision >= 0`.
- Check: `status IN ('running','success','failed','superseded')`.
- Check: `strategy IN ('greedy','priority','multi_room_exam_greedy','multi_room_exam_best_fit','shared_room_exam_best_fit')`.
- Unique: `correlation_id`.
- Index: `ix_allocation_run_status (status)`.

## application_state

Singleton strategy, input revision and currently published run.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| id | integer | PK | no | - |
| input_revision | bigint | - | no | ORM: 0 |
| strategy | varchar(50) | - | no | ORM: greedy |
| active_run_id | bigint | FK -> allocation_run.id | yes | - |
| calendar_revision | bigint | - | no | 0 |
| waiting_notice_minutes | integer | - | yes | - |

- Primary key: `id`.
- Foreign key: `(active_run_id) -> allocation_run (id)`; NO ACTION.
- Check: `id = 1 AND input_revision >= 0`.
- Check: `strategy IN ('greedy','priority','multi_room_exam_greedy','multi_room_exam_best_fit','shared_room_exam_best_fit')`.
- Check: `waiting_notice_minutes > 0`.

## appointment

Dated organizer request, duration, current revision and lifecycle state.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| id | bigint | PK | no | identity |
| organizer_id | integer | FK -> university_user.id | no | - |
| purpose | text | - | no | - |
| duration_minutes | integer | - | no | - |
| start_at | timestamp with time zone | - | no | - |
| end_at | timestamp with time zone | - | no | - |
| revision | integer | - | no | ORM: 1 |
| status | varchar(30) | - | no | ORM: Pending Approval |
| created_at | timestamp with time zone | - | no | now() |

- Primary key: `id`.
- Foreign key: `(organizer_id) -> university_user (id)`; NO ACTION.
- Check: `end_at = start_at + duration_minutes * interval '1 minute'`.
- Check: `revision > 0 AND duration_minutes > 0 AND start_at < end_at`.
- Check: `status IN ('Pending Approval','Declined','Confirmed','Cancelled')`.
- Index: `ix_appointment_organizer_start (organizer_id, start_at)`.

## appointment_commitment

Confirmed mandatory-person reservations with half-open overlap exclusion.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| appointment_id | bigint | PK; FK -> appointment.id | no | - |
| user_id | integer | PK; FK -> university_user.id | no | - |
| start_at | timestamp with time zone | - | no | - |
| end_at | timestamp with time zone | - | no | - |
| period | tstzrange | - | no | computed: tstzrange(start_at, end_at, '[)') |

- Primary key: `appointment_id, user_id`.
- Foreign key: `(appointment_id) -> appointment (id)`; NO ACTION.
- Foreign key: `(user_id) -> university_user (id)`; NO ACTION.
- Check: `start_at < end_at`.

## appointment_event

Participant-visible, timestamped appointment lifecycle history.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| id | bigint | PK | no | identity |
| appointment_id | bigint | FK -> appointment.id | no | - |
| actor_id | integer | FK -> university_user.id | no | - |
| revision | integer | - | no | - |
| message | text | - | no | - |
| created_at | timestamp with time zone | - | no | now() |

- Primary key: `id`.
- Foreign key: `(actor_id) -> university_user (id)`; NO ACTION.
- Foreign key: `(appointment_id) -> appointment (id)`; NO ACTION.
- Check: `revision > 0`.
- Index: `ix_appointment_event_actor_id (actor_id)`.
- Index: `ix_appointment_event_appointment_id (appointment_id)`.

## appointment_invitation

Optional student participation status; no mandatory acceptance.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| appointment_id | bigint | PK; FK -> appointment.id | no | - |
| user_id | integer | PK; FK -> university_user.id | no | - |
| status | varchar(20) | - | no | ORM: Invited |

- Primary key: `appointment_id, user_id`.
- Foreign key: `(appointment_id) -> appointment (id)`; NO ACTION.
- Foreign key: `(user_id) -> university_user (id)`; NO ACTION.
- Check: `status IN ('Invited','Declined')`.
- Index: `ix_appointment_invitation_user_id (user_id)`.

## appointment_professor

Required professor decisions for the appointment revision.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| appointment_id | bigint | PK; FK -> appointment.id | no | - |
| user_id | integer | PK; FK -> university_user.id | no | - |
| revision | integer | - | no | - |
| decision | varchar(20) | - | no | ORM: Pending |

- Primary key: `appointment_id, user_id`.
- Foreign key: `(appointment_id) -> appointment (id)`; NO ACTION.
- Foreign key: `(user_id) -> university_user (id)`; NO ACTION.
- Check: `decision IN ('Pending','Approved','Declined')`.
- Check: `revision > 0`.
- Index: `ix_appointment_professor_user_id (user_id)`.

## borrow_extension

Explicit custodian decision on a proposed later due date for an active loan.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| id | integer | PK | no | identity |
| request_id | integer | FK -> borrow_request.id | no | - |
| due_at | timestamp with time zone | - | no | - |
| status | varchar(20) | - | no | ORM: Pending |
| reason | text | - | no | - |
| decided_by | integer | FK -> login_account.user_id | yes | - |
| created_at | timestamp with time zone | - | no | now() |

- Primary key: `id`.
- Foreign key: `(decided_by) -> login_account (user_id)`; NO ACTION.
- Foreign key: `(request_id) -> borrow_request (id)`; NO ACTION.
- Check: `status IN ('Pending','Approved','Rejected')`.
- Index: `ix_borrow_extension_decided_by (decided_by)`.
- Index: `ix_borrow_extension_request_id (request_id)`.
- Index: `uq_pending_borrow_extension (request_id)`.

## borrow_item

Same-faculty requested type, quantity and exact additional specifications.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| id | integer | PK | no | identity |
| request_id | integer | FK -> borrow_request.id | no | - |
| faculty_id | integer | FK -> borrow_request.faculty_id; FK -> equipment_type.faculty_id | no | - |
| type_id | integer | FK -> equipment_type.id | no | - |
| quantity | integer | - | no | - |
| specifications | jsonb | - | no | ORM callable |

- Primary key: `id`.
- Foreign key: `(request_id, faculty_id) -> borrow_request (id, faculty_id)`; NO ACTION.
- Foreign key: `(type_id, faculty_id) -> equipment_type (id, faculty_id)`; NO ACTION.
- Check: `quantity BETWEEN 1 AND 1000 AND jsonb_typeof(specifications) = 'object'`.
- Unique: `id, type_id`.
- Unique: `request_id, type_id`.
- Index: `ix_borrow_item_faculty_id (faculty_id)`.
- Index: `ix_borrow_item_request_faculty (request_id, faculty_id)`.
- Index: `ix_borrow_item_type_faculty (type_id, faculty_id)`.

## borrow_request

Student borrowing interval, purpose, lifecycle and idempotent submission identity.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| id | integer | PK | no | identity |
| borrower_id | integer | FK -> university_user.id | no | - |
| faculty_id | integer | FK -> organization_unit.id | no | - |
| purpose | text | - | no | - |
| notes | text | - | no | ORM:  |
| start_at | timestamp with time zone | - | no | - |
| due_at | timestamp with time zone | - | no | - |
| status | varchar(30) | - | no | ORM: Pending Approval |
| submission_key | varchar(32) | - | no | - |
| submission_fingerprint | varchar(64) | - | no | - |
| created_at | timestamp with time zone | - | no | now() |

- Primary key: `id`.
- Foreign key: `(borrower_id) -> university_user (id)`; NO ACTION.
- Foreign key: `(faculty_id) -> organization_unit (id)`; NO ACTION.
- Check: `start_at < due_at`.
- Check: `status IN ('Pending Approval','Approved','Rejected','Borrowed','Partially Returned','Returned','Cancelled')`.
- Check: `submission_key ~ '^[0-9a-f]{32}$' AND submission_fingerprint ~ '^[0-9a-f]{64}$'`.
- Unique: `borrower_id, submission_key`.
- Unique: `id, faculty_id`.
- Index: `ix_borrow_faculty_status (faculty_id, status)`.
- Index: `ix_borrow_request_borrower_id (borrower_id)`.

## busy_slot

Explicit weekly user commitments, independent of allocation runs.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| id | integer | PK | no | identity |
| user_id | integer | FK -> university_user.id | no | - |
| source_order | integer | - | no | - |
| day | integer | - | no | - |
| start_minutes | integer | - | no | - |
| end_minutes | integer | - | no | - |
| reason | text | - | no | ORM:  |

- Primary key: `id`.
- Foreign key: `(user_id) -> university_user (id)`; NO ACTION.
- Check: `day BETWEEN 1 AND 7`.
- Check: `source_order > 0`.
- Check: `start_minutes >= 0 AND start_minutes < end_minutes AND end_minutes <= 1440`.
- Unique: `source_order`.
- Index: `ix_busy_slot_user_id (user_id)`.

## calendar_block

Private dated unavailable intervals for a university user.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| id | bigint | PK | no | identity |
| user_id | integer | FK -> university_user.id | no | - |
| start_at | timestamp with time zone | - | no | - |
| end_at | timestamp with time zone | - | no | - |
| reason | text | - | no | ORM:  |

- Primary key: `id`.
- Foreign key: `(user_id) -> university_user (id)`; NO ACTION.
- Check: `start_at < end_at`.
- Index: `ix_calendar_block_user_start (user_id, start_at)`.

## equipment_category

Extensible named equipment categories, independent of room types.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| id | integer | PK | no | identity |
| name | varchar(150) | - | no | - |

- Primary key: `id`.
- Unique: `name`.

## equipment_custodian

One current designated equipment staff/administrator account per owning faculty.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| faculty_id | integer | PK; FK -> organization_unit.id | no | - |
| user_id | integer | FK -> login_account.user_id | no | - |

- Primary key: `faculty_id`.
- Foreign key: `(faculty_id) -> organization_unit (id)`; NO ACTION.
- Foreign key: `(user_id) -> login_account (user_id)`; NO ACTION.
- Index: `ix_equipment_custodian_user_id (user_id)`.

## equipment_event

Actor/time/faculty-scoped inventory, configuration and borrowing lifecycle audit.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| id | bigint | PK | no | identity |
| faculty_id | integer | FK -> organization_unit.id | no | - |
| request_id | integer | FK -> borrow_request.id | yes | - |
| unit_id | integer | FK -> equipment_unit.id | yes | - |
| actor_id | integer | FK -> university_user.id | no | - |
| message | text | - | no | - |
| created_at | timestamp with time zone | - | no | now() |

- Primary key: `id`.
- Foreign key: `(actor_id) -> university_user (id)`; NO ACTION.
- Foreign key: `(faculty_id) -> organization_unit (id)`; NO ACTION.
- Foreign key: `(request_id) -> borrow_request (id)`; NO ACTION.
- Foreign key: `(unit_id) -> equipment_unit (id)`; NO ACTION.
- Index: `ix_equipment_event_actor_id (actor_id)`.
- Index: `ix_equipment_event_faculty_id (faculty_id)`.
- Index: `ix_equipment_event_request_id (request_id)`.
- Index: `ix_equipment_event_unit_id (unit_id)`.

## equipment_reservation

Specific reserved asset, excluded overlapping interval, physical handover and verified return.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| id | integer | PK | no | identity |
| item_id | integer | FK -> borrow_item.id | no | - |
| type_id | integer | FK -> borrow_item.type_id; FK -> equipment_unit.type_id | no | - |
| unit_id | integer | FK -> equipment_unit.id | no | - |
| start_at | timestamp with time zone | - | no | - |
| due_at | timestamp with time zone | - | no | - |
| period | tstzrange | - | no | computed: tstzrange(start_at, due_at, '[)') |
| released | boolean | - | no | ORM: False |
| handed_at | timestamp with time zone | - | yes | - |
| handed_by | integer | FK -> login_account.user_id | yes | - |
| handover_condition | text | - | yes | - |
| returned_at | timestamp with time zone | - | yes | - |
| received_by | integer | FK -> login_account.user_id | yes | - |
| return_condition | text | - | yes | - |

- Primary key: `id`.
- Foreign key: `(handed_by) -> login_account (user_id)`; NO ACTION.
- Foreign key: `(item_id, type_id) -> borrow_item (id, type_id)`; NO ACTION.
- Foreign key: `(received_by) -> login_account (user_id)`; NO ACTION.
- Foreign key: `(unit_id, type_id) -> equipment_unit (id, type_id)`; NO ACTION.
- Check: `NOT released OR handed_at IS NULL OR returned_at IS NOT NULL`.
- Check: `handed_at IS NULL OR (handed_by IS NOT NULL AND handover_condition IS NOT NULL)`.
- Check: `returned_at IS NULL OR (handed_at IS NOT NULL AND returned_at >= handed_at AND released)`.
- Check: `returned_at IS NULL OR (received_by IS NOT NULL AND return_condition IS NOT NULL)`.
- Check: `start_at < due_at`.
- Index: `ix_equipment_reservation_handed_by (handed_by)`.
- Index: `ix_equipment_reservation_item_type (item_id, type_id)`.
- Index: `ix_equipment_reservation_received_by (received_by)`.
- Index: `ix_equipment_reservation_type_id (type_id)`.
- Index: `ix_equipment_reservation_unit_type (unit_id, type_id)`.

## equipment_type

Faculty-owned equipment catalog, exact specifications and configurable borrowing policy.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| id | integer | PK | no | identity |
| faculty_id | integer | FK -> organization_unit.id | no | - |
| category_id | integer | FK -> equipment_category.id | no | - |
| name | varchar(200) | - | no | - |
| description | text | - | no | ORM:  |
| specifications | jsonb | - | no | ORM callable |
| max_loan_days | integer | - | no | - |
| eligible_faculty_ids | jsonb | - | no | ORM callable |
| pickup_instructions | text | - | no | ORM:  |
| enabled | boolean | - | no | ORM: True |

- Primary key: `id`.
- Foreign key: `(category_id) -> equipment_category (id)`; NO ACTION.
- Foreign key: `(faculty_id) -> organization_unit (id)`; NO ACTION.
- Check: `jsonb_typeof(specifications) = 'object' AND jsonb_typeof(eligible_faculty_ids) = 'array'`.
- Check: `max_loan_days BETWEEN 1 AND 365`.
- Unique: `id, faculty_id`.
- Index: `ix_equipment_type_category_id (category_id)`.
- Index: `ix_equipment_type_faculty_id (faculty_id)`.

## equipment_unit

Individually identifiable physical asset and current physical condition.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| id | integer | PK | no | identity |
| type_id | integer | FK -> equipment_type.id | no | - |
| asset_tag | varchar(150) | - | no | - |
| condition | varchar(20) | - | no | ORM: usable |
| notes | text | - | no | ORM:  |

- Primary key: `id`.
- Foreign key: `(type_id) -> equipment_type (id)`; NO ACTION.
- Check: `condition IN ('usable','maintenance','damaged','missing','lost','retired')`.
- Unique: `asset_tag`.
- Unique: `id, type_id`.
- Index: `ix_equipment_unit_type_id (type_id)`.

## exam_details

Optional one-to-one examination metadata.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| request_id | integer | PK; FK -> resource_request.id | no | - |
| course_code | text | - | no | ORM:  |
| course_name | text | - | no | ORM:  |
| exam_type | text | - | no | ORM:  |
| can_split | boolean | - | no | ORM: False |

- Primary key: `request_id`.
- Foreign key: `(request_id) -> resource_request (id)`; NO ACTION.

## faculty_room_approver

Current designated administrative account for a room-owning faculty.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| faculty_id | integer | PK; FK -> organization_unit.id | no | - |
| user_id | integer | FK -> login_account.user_id | no | - |

- Primary key: `faculty_id`.
- Foreign key: `(faculty_id) -> organization_unit (id)`; NO ACTION.
- Foreign key: `(user_id) -> login_account (user_id)`; NO ACTION.
- Index: `ix_faculty_room_approver_user_id (user_id)`.

## feedback_event

Private actor/time/status history, staff responses and idempotent actions; existing notification receipts are reused.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| id | bigint | PK | no | identity |
| report_id | bigint | FK -> resource_feedback.id | no | - |
| actor_id | integer | FK -> university_user.id | no | - |
| revision | integer | - | no | - |
| status | varchar(20) | - | no | - |
| message | text | - | no | - |
| action_key | varchar(32) | - | no | - |
| fingerprint | varchar(64) | - | no | - |
| created_at | timestamp with time zone | - | no | clock_timestamp() |

- Primary key: `id`.
- Foreign key: `(actor_id) -> university_user (id)`; NO ACTION.
- Foreign key: `(report_id) -> resource_feedback (id)`; NO ACTION.
- Check: `action_key ~ '^[0-9a-f]{32}$' AND fingerprint ~ '^[0-9a-f]{64}$'`.
- Check: `revision > 0 AND length(btrim(message)) BETWEEN 1 AND 4500`.
- Check: `status IN ('Submitted','Under Review','Resolved','Closed')`.
- Unique: `report_id, action_key`.
- Unique: `report_id, revision`.
- Index: `ix_feedback_event_actor_id (actor_id)`.
- Index: `ix_feedback_event_report_id (report_id)`.

## legacy_calendar_binding

Explicit period/planning-week association for an undated busy slot or request.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| id | bigint | PK | no | identity |
| period_id | integer | FK -> academic_period.id | no | - |
| busy_slot_id | integer | FK -> busy_slot.id | yes | - |
| request_id | integer | FK -> resource_request.id | yes | - |
| week_start | date | - | yes | - |
| excluded_dates | jsonb | - | no | ORM callable |

- Primary key: `id`.
- Foreign key: `(busy_slot_id) -> busy_slot (id)`; NO ACTION.
- Foreign key: `(period_id) -> academic_period (id)`; NO ACTION.
- Foreign key: `(request_id) -> resource_request (id)`; NO ACTION.
- Check: `(busy_slot_id IS NULL) <> (request_id IS NULL)`.
- Unique: `period_id, busy_slot_id`.
- Unique: `period_id, request_id`.
- Index: `ix_legacy_calendar_binding_busy_slot_id (busy_slot_id)`.
- Index: `ix_legacy_calendar_binding_period_id (period_id)`.
- Index: `ix_legacy_calendar_binding_request_id (request_id)`.

## login_account

Trusted login identity, password hash, administration grant, revocation and throttling.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| user_id | integer | PK; FK -> university_user.id | no | - |
| username | varchar(100) | - | no | - |
| password_hash | text | - | no | - |
| enabled | boolean | - | no | ORM: True |
| administrator | boolean | - | no | ORM: False |
| session_version | integer | - | no | ORM: 1 |
| failed_attempts | integer | - | no | ORM: 0 |
| locked_until | timestamp with time zone | - | yes | - |

- Primary key: `user_id`.
- Foreign key: `(user_id) -> university_user (id)`; NO ACTION.
- Check: `failed_attempts >= 0 AND session_version > 0`.
- Unique: `username`.

## meeting_suggestion

Ranked structured time/resource alternatives returned by C++.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| run_id | bigint | PK; FK -> suggestion_group.run_id | no | - |
| request_id | integer | PK; FK -> suggestion_group.request_id | no | - |
| rank | integer | PK | no | - |
| resource_id | integer | FK -> resource.id | no | - |
| day | integer | - | no | - |
| start_minutes | integer | - | no | - |
| end_minutes | integer | - | no | - |
| score | integer | - | no | - |
| time_distance | integer | - | no | - |
| day_distance | integer | - | no | - |
| conflict_count | integer | - | no | - |
| reason | text | - | no | - |

- Primary key: `run_id, request_id, rank`.
- Foreign key: `(resource_id) -> resource (id)`; NO ACTION.
- Foreign key: `(run_id, request_id) -> suggestion_group (run_id, request_id)`; NO ACTION.
- Check: `day BETWEEN 1 AND 7`.
- Check: `rank > 0 AND score >= 0 AND time_distance >= 0 AND day_distance >= 0 AND conflict_count >= 0`.
- Check: `start_minutes >= 0 AND start_minutes < end_minutes AND end_minutes <= 1440`.
- Index: `ix_meeting_suggestion_resource_id (resource_id)`.

## notification

Recipient-scoped event inbox and durable read state; exactly one appointment/room/equipment/private-feedback history event.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| id | bigint | PK | no | identity |
| recipient_id | integer | FK -> university_user.id | no | - |
| appointment_event_id | bigint | FK -> appointment_event.id | yes | - |
| room_event_id | bigint | FK -> room_event.id | yes | - |
| equipment_event_id | bigint | FK -> equipment_event.id | yes | - |
| feedback_event_id | bigint | FK -> feedback_event.id | yes | - |
| read_at | timestamp with time zone | - | yes | - |

- Primary key: `id`.
- Foreign key: `(appointment_event_id) -> appointment_event (id)`; NO ACTION.
- Foreign key: `(equipment_event_id) -> equipment_event (id)`; NO ACTION.
- Foreign key: `(feedback_event_id) -> feedback_event (id)`; NO ACTION.
- Foreign key: `(recipient_id) -> university_user (id)`; NO ACTION.
- Foreign key: `(room_event_id) -> room_event (id)`; NO ACTION.
- Check: `num_nonnulls(appointment_event_id, room_event_id, equipment_event_id, feedback_event_id) = 1`.
- Unique: `recipient_id, appointment_event_id`.
- Unique: `recipient_id, equipment_event_id`.
- Unique: `recipient_id, feedback_event_id`.
- Unique: `recipient_id, room_event_id`.
- Index: `ix_notification_appointment_event_id (appointment_event_id)`.
- Index: `ix_notification_equipment_event_id (equipment_event_id)`.
- Index: `ix_notification_feedback_event_id (feedback_event_id)`.
- Index: `ix_notification_recipient_read_id (recipient_id, read_at, id)`.
- Index: `ix_notification_room_event_id (room_event_id)`.

## organization_unit

Named university units with optional known type and parent.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| id | integer | PK | no | identity |
| name | varchar(255) | - | no | - |
| unit_type | varchar(100) | - | yes | - |
| parent_id | integer | FK -> organization_unit.id | yes | - |

- Primary key: `id`.
- Foreign key: `(parent_id) -> organization_unit (id)`; NO ACTION.
- Check: `parent_id IS NULL OR parent_id <> id`.
- Unique: `name`.
- Index: `ix_organization_unit_parent_id (parent_id)`.

## professor_availability

Bounded weekly published office-hour patterns and date exceptions.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| id | bigint | PK | no | identity |
| user_id | integer | FK -> university_user.id | no | - |
| day | integer | - | no | - |
| start_minutes | integer | - | no | - |
| end_minutes | integer | - | no | - |
| valid_from | date | - | no | - |
| valid_until | date | - | no | - |
| timezone | varchar(100) | - | no | - |
| excluded_dates | jsonb | - | no | ORM callable |

- Primary key: `id`.
- Foreign key: `(user_id) -> university_user (id)`; NO ACTION.
- Check: `day BETWEEN 1 AND 7`.
- Check: `start_minutes >= 0 AND start_minutes < end_minutes AND end_minutes <= 1440`.
- Check: `valid_from <= valid_until`.
- Index: `ix_professor_availability_user_id (user_id)`.

## request_decision

One decision per run/request, including immutable engine detail/history.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| run_id | bigint | PK; FK -> allocation_run.id | no | - |
| request_id | integer | PK; FK -> resource_request.id | no | - |
| ordinal | integer | - | no | - |
| status | varchar(20) | - | no | - |
| reason | text | - | no | - |
| payload | jsonb | - | no | - |

- Primary key: `run_id, request_id`.
- Foreign key: `(request_id) -> resource_request (id)`; NO ACTION.
- Foreign key: `(run_id) -> allocation_run (id)`; NO ACTION.
- Check: `ordinal > 0`.
- Check: `status IN ('Approved','Rejected')`.
- Unique: `run_id, ordinal`.
- Index: `ix_request_decision_request_id (request_id)`.

## request_history

Timestamped save/import/decision events with optional run provenance.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| id | bigint | PK | no | identity |
| request_id | integer | FK -> resource_request.id | no | - |
| run_id | bigint | FK -> allocation_run.id | yes | - |
| kind | varchar(30) | - | no | - |
| message | text | - | no | - |
| created_at | timestamp with time zone | - | no | now() |

- Primary key: `id`.
- Foreign key: `(request_id) -> resource_request (id)`; NO ACTION.
- Foreign key: `(run_id) -> allocation_run (id)`; NO ACTION.
- Index: `ix_request_history_request_id (request_id)`.
- Index: `ix_request_history_run_id (run_id)`.

## request_participant

Ordered required committee participants and descriptive roles.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| request_id | integer | PK; FK -> resource_request.id | no | - |
| user_id | integer | PK; FK -> university_user.id | no | - |
| ordinal | integer | - | no | - |
| role | text | - | no | ORM: Participant |

- Primary key: `request_id, user_id`.
- Foreign key: `(request_id) -> resource_request (id)`; NO ACTION.
- Foreign key: `(user_id) -> university_user (id)`; NO ACTION.
- Check: `ordinal > 0`.
- Unique: `request_id, ordinal`.
- Index: `ix_request_participant_user_id (user_id)`.

## request_slot

Ordered weekly occurrences; multiple rows represent recurrence.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| request_id | integer | PK; FK -> resource_request.id | no | - |
| ordinal | integer | PK | no | - |
| day | integer | - | no | - |
| start_minutes | integer | - | no | - |
| end_minutes | integer | - | no | - |

- Primary key: `request_id, ordinal`.
- Foreign key: `(request_id) -> resource_request (id)`; NO ACTION.
- Check: `day BETWEEN 1 AND 7`.
- Check: `ordinal > 0`.
- Check: `start_minutes >= 0 AND start_minutes < end_minutes AND end_minutes <= 1440`.

## resource

Typed classrooms, laboratories and meeting rooms with facilities and capacity.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| id | integer | PK | no | identity |
| source_order | integer | - | no | - |
| type | varchar(30) | - | no | - |
| name | text | - | no | - |
| capacity | integer | - | no | - |
| building | text | - | no | ORM:  |
| projector | boolean | - | no | ORM: False |
| whiteboard | boolean | - | no | ORM: False |
| computers | boolean | - | no | ORM: False |
| available | boolean | - | no | ORM: True |

- Primary key: `id`.
- Check: `id > 0 AND capacity > 0`.
- Check: `source_order > 0`.
- Check: `type IN ('Classroom','Laboratory','MeetingRoom')`.
- Unique: `source_order`.

## resource_feedback

Private optional room/equipment usage report, immutable reporter/booking association, current review state and retry identity.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| id | bigint | PK | no | identity |
| room_request_id | bigint | FK -> student_room_request.id | yes | - |
| room_resource_id | integer | FK -> resource.id | yes | - |
| room_revision | integer | - | yes | - |
| equipment_reservation_id | integer | FK -> equipment_reservation.id | yes | - |
| reporter_id | integer | FK -> university_user.id | no | - |
| faculty_id | integer | FK -> organization_unit.id | no | - |
| assigned_to_id | integer | FK -> login_account.user_id | no | - |
| category | varchar(20) | - | no | - |
| description | text | - | no | - |
| status | varchar(20) | - | no | ORM: Submitted |
| priority | varchar(10) | - | no | ORM: normal |
| response | text | - | no | ORM:  |
| revision | integer | - | no | ORM: 1 |
| submission_key | varchar(32) | - | no | - |
| fingerprint | varchar(64) | - | no | - |
| created_at | timestamp with time zone | - | no | clock_timestamp() |
| updated_at | timestamp with time zone | - | no | clock_timestamp() |

- Primary key: `id`.
- Foreign key: `(assigned_to_id) -> login_account (user_id)`; NO ACTION.
- Foreign key: `(equipment_reservation_id) -> equipment_reservation (id)`; NO ACTION.
- Foreign key: `(faculty_id) -> organization_unit (id)`; NO ACTION.
- Foreign key: `(reporter_id) -> university_user (id)`; NO ACTION.
- Foreign key: `(room_request_id) -> student_room_request (id)`; NO ACTION.
- Foreign key: `(room_resource_id) -> resource (id)`; NO ACTION.
- Check: `(room_request_id IS NOT NULL AND room_resource_id IS NOT NULL AND room_revision IS NOT NULL AND room_revision > 0 AND equipment_reservation_id IS NULL) OR (room_request_id IS NULL AND room_resource_id IS NULL AND room_revision IS NULL AND equipment_reservation_id IS NOT NULL)`.
- Check: `category IN ('problem','improvement','general')`.
- Check: `length(btrim(description)) BETWEEN 1 AND 4000 AND length(response) <= 4000 AND revision > 0`.
- Check: `priority IN ('low','normal','high','urgent')`.
- Check: `status IN ('Submitted','Under Review','Resolved','Closed')`.
- Check: `submission_key ~ '^[0-9a-f]{32}$' AND fingerprint ~ '^[0-9a-f]{64}$'`.
- Unique: `reporter_id, submission_key`.
- Index: `ix_feedback_faculty_status (faculty_id, status, id)`.
- Index: `ix_feedback_reporter_created (reporter_id, created_at, id)`.
- Index: `ix_resource_feedback_assigned_to_id (assigned_to_id)`.
- Index: `ix_resource_feedback_equipment_reservation_id (equipment_reservation_id)`.
- Index: `ix_resource_feedback_room_request_id (room_request_id)`.
- Index: `ix_resource_feedback_room_resource_id (room_resource_id)`.

## resource_request

Ordered request identity, requirements and private-by-default academic publication; optional explicit instructor label.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| id | integer | PK | no | identity |
| submission_order | bigint | - | no | identity |
| type | varchar(30) | - | no | - |
| requester_id | integer | FK -> university_user.id | no | - |
| resource_id | integer | FK -> resource.id | no | - |
| participant_count | integer | - | no | - |
| title | text | - | no | ORM:  |
| purpose | text | - | no | ORM:  |
| required_feature | text | - | no | ORM:  |
| required_building | text | - | no | ORM:  |
| revision | integer | - | no | ORM: 1 |
| submission_key | varchar(32) | - | yes | - |
| submission_fingerprint | varchar(64) | - | yes | - |
| calendar_public | boolean | - | no | false |
| academic_instructor_id | integer | FK -> university_user.id | yes | - |

- Primary key: `id`.
- Foreign key: `(academic_instructor_id) -> university_user (id)`; NO ACTION.
- Foreign key: `(requester_id) -> university_user (id)`; NO ACTION.
- Foreign key: `(resource_id) -> resource (id)`; NO ACTION.
- Check: `(submission_key IS NULL AND submission_fingerprint IS NULL) OR (submission_key IS NOT NULL AND submission_fingerprint IS NOT NULL AND submission_key ~ '^[0-9a-f]{32}$' AND submission_fingerprint ~ '^[0-9a-f]{64}$')`.
- Check: `NOT calendar_public OR type <> 'CommitteeMeeting'`.
- Check: `id > 0 AND participant_count > 0 AND revision > 0`.
- Check: `submission_order > 0`.
- Check: `type IN ('OneTime','Recurring','Exam','CommitteeMeeting')`.
- Unique: `submission_key`.
- Unique: `submission_order`.
- Index: `ix_resource_request_academic_instructor_id (academic_instructor_id)`.
- Index: `ix_resource_request_requester_id (requester_id)`.
- Index: `ix_resource_request_resource_id (resource_id)`.

## role

Primary engine roles and preserved assigned-role labels; not authentication permissions.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| id | integer | PK | no | identity |
| name | varchar(100) | - | no | - |

- Primary key: `id`.
- Unique: `name`.

## room_access

Allowed university users for explicitly restricted student rooms.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| resource_id | integer | PK; FK -> room_policy.resource_id | no | - |
| user_id | integer | PK; FK -> university_user.id | no | - |

- Primary key: `resource_id, user_id`.
- Foreign key: `(resource_id) -> room_policy (resource_id)`; NO ACTION.
- Foreign key: `(user_id) -> university_user (id)`; NO ACTION.
- Index: `ix_room_access_user_id (user_id)`.

## room_closure

Dated room unavailability, independent of private request details.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| id | bigint | PK | no | identity |
| resource_id | integer | FK -> resource.id | no | - |
| start_at | timestamp with time zone | - | no | - |
| end_at | timestamp with time zone | - | no | - |
| reason | text | - | no | ORM:  |

- Primary key: `id`.
- Foreign key: `(resource_id) -> resource (id)`; NO ACTION.
- Check: `start_at < end_at`.
- Index: `ix_room_closure_resource_start (resource_id, start_at)`.

## room_event

Private timestamped room request lifecycle and invitation history.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| id | bigint | PK | no | identity |
| request_id | bigint | FK -> student_room_request.id | no | - |
| actor_id | integer | FK -> university_user.id | no | - |
| revision | integer | - | no | - |
| message | text | - | no | - |
| created_at | timestamp with time zone | - | no | now() |

- Primary key: `id`.
- Foreign key: `(actor_id) -> university_user (id)`; NO ACTION.
- Foreign key: `(request_id) -> student_room_request (id)`; NO ACTION.
- Check: `revision > 0`.
- Index: `ix_room_event_actor_id (actor_id)`.
- Index: `ix_room_event_request_id (request_id)`.

## room_invitation

Optional professor attendance response for the current room request revision.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| request_id | bigint | PK; FK -> student_room_request.id | no | - |
| user_id | integer | PK; FK -> university_user.id | no | - |
| revision | integer | - | no | - |
| status | varchar(20) | - | no | ORM: Invited |

- Primary key: `request_id, user_id`.
- Foreign key: `(request_id) -> student_room_request (id)`; NO ACTION.
- Foreign key: `(user_id) -> university_user (id)`; NO ACTION.
- Check: `revision > 0`.
- Check: `status IN ('Invited','Accepted','Declined')`.
- Index: `ix_room_invitation_user_id (user_id)`.

## room_organizer_commitment

Confirmed organizing-student interval with cross-appointment conflict protection.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| request_id | bigint | PK; FK -> student_room_request.id | no | - |
| user_id | integer | FK -> university_user.id | no | - |
| start_at | timestamp with time zone | - | no | - |
| end_at | timestamp with time zone | - | no | - |
| period | tstzrange | - | no | computed: tstzrange(start_at, end_at, '[)') |

- Primary key: `request_id`.
- Foreign key: `(request_id) -> student_room_request (id)`; NO ACTION.
- Foreign key: `(user_id) -> university_user (id)`; NO ACTION.
- Check: `start_at < end_at`.
- Index: `ix_room_organizer_commitment_user_id (user_id)`.

## room_policy

Explicit owning faculty, bookability, permitted categories and whitelist policy.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| resource_id | integer | PK; FK -> resource.id | no | - |
| faculty_id | integer | FK -> organization_unit.id | no | - |
| enabled | boolean | - | no | ORM: False |
| restricted | boolean | - | no | ORM: False |
| categories | jsonb | - | no | ORM callable |

- Primary key: `resource_id`.
- Foreign key: `(faculty_id) -> organization_unit (id)`; NO ACTION.
- Foreign key: `(resource_id) -> resource (id)`; NO ACTION.
- Check: `jsonb_typeof(categories) = 'array' AND jsonb_array_length(categories) BETWEEN 1 AND 5 AND '["study","meeting","lecture","club","other"]'::jsonb @> categories`.
- Index: `ix_room_policy_faculty_id (faculty_id)`.

## room_reservation

Exact confirmed exclusive room interval; GiST overlap exclusion.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| request_id | bigint | PK; FK -> student_room_request.id | no | - |
| resource_id | integer | FK -> resource.id | no | - |
| start_at | timestamp with time zone | - | no | - |
| end_at | timestamp with time zone | - | no | - |
| period | tstzrange | - | no | computed: tstzrange(start_at, end_at, '[)') |

- Primary key: `request_id`.
- Foreign key: `(request_id) -> student_room_request (id)`; NO ACTION.
- Foreign key: `(resource_id) -> resource (id)`; NO ACTION.
- Check: `start_at < end_at`.
- Index: `ix_room_reservation_resource_id (resource_id)`.

## student_room_request

Student needs, selected verified room, faculty approval, dated interval and revision.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| id | bigint | PK | no | identity |
| organizer_id | integer | FK -> university_user.id | no | - |
| resource_id | integer | FK -> resource.id | no | - |
| faculty_id | integer | FK -> organization_unit.id | no | - |
| approver_id | integer | FK -> login_account.user_id | no | - |
| category | varchar(30) | - | no | - |
| purpose | text | - | no | - |
| description | text | - | no | ORM:  |
| club_affiliation | text | - | no | ORM:  |
| attendee_count | integer | - | no | - |
| required_features | jsonb | - | no | ORM callable |
| preferred_faculty_id | integer | FK -> organization_unit.id | yes | - |
| preferred_building | text | - | no | ORM:  |
| start_at | timestamp with time zone | - | no | - |
| end_at | timestamp with time zone | - | no | - |
| duration_minutes | integer | - | no | - |
| revision | integer | - | no | ORM: 1 |
| status | varchar(30) | - | no | ORM: Pending Faculty Approval |
| approved_revision | integer | - | yes | - |
| approved_by | integer | FK -> login_account.user_id | yes | - |
| explanation | text | - | no | ORM:  |
| created_at | timestamp with time zone | - | no | now() |

- Primary key: `id`.
- Foreign key: `(approved_by) -> login_account (user_id)`; NO ACTION.
- Foreign key: `(approver_id) -> login_account (user_id)`; NO ACTION.
- Foreign key: `(faculty_id) -> organization_unit (id)`; NO ACTION.
- Foreign key: `(organizer_id) -> university_user (id)`; NO ACTION.
- Foreign key: `(preferred_faculty_id) -> organization_unit (id)`; NO ACTION.
- Foreign key: `(resource_id) -> resource (id)`; NO ACTION.
- Check: `category IN ('study','meeting','lecture','club','other')`.
- Check: `end_at = start_at + duration_minutes * interval '1 minute'`.
- Check: `jsonb_typeof(required_features) = 'array' AND '["projector","whiteboard","computers"]'::jsonb @> required_features`.
- Check: `revision > 0 AND attendee_count > 0 AND duration_minutes BETWEEN 1 AND 1440 AND start_at < end_at`.
- Check: `status <> 'Confirmed' OR (approved_revision IS NOT NULL AND approved_revision = revision AND approved_by IS NOT NULL AND approved_by = approver_id)`.
- Check: `status IN ('Pending Faculty Approval','Needs Revision','Rejected','Confirmed','Cancelled')`.
- Index: `ix_student_room_approver_status (approver_id, status)`.
- Index: `ix_student_room_organizer_start (organizer_id, start_at)`.
- Index: `ix_student_room_request_approved_by (approved_by)`.
- Index: `ix_student_room_request_faculty_id (faculty_id)`.
- Index: `ix_student_room_request_preferred_faculty_id (preferred_faculty_id)`.
- Index: `ix_student_room_request_resource_id (resource_id)`.

## suggestion_group

Decision-specific suggestion scan, including a scan yielding no alternatives.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| run_id | bigint | PK; FK -> request_decision.run_id | no | - |
| request_id | integer | PK; FK -> request_decision.request_id | no | - |
| ordinal | integer | - | no | - |

- Primary key: `run_id, request_id`.
- Foreign key: `(run_id, request_id) -> request_decision (run_id, request_id)`; NO ACTION.
- Check: `ordinal > 0`.
- Unique: `run_id, ordinal`.

## university_user

University identity and profile; primary role and optional primary unit.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| id | integer | PK | no | identity |
| source_order | integer | - | no | - |
| name | text | - | no | - |
| primary_role_id | integer | FK -> role.id | no | - |
| primary_unit_id | integer | FK -> organization_unit.id | yes | - |
| email | text | - | no | ORM:  |
| status | text | - | no | ORM: active |
| student_no | text | - | no | ORM:  |
| program | text | - | no | ORM:  |
| year_level | integer | - | no | ORM: 0 |
| title | text | - | no | ORM:  |
| office_room | text | - | no | ORM:  |
| assistant_type | text | - | no | ORM:  |
| job_title | text | - | no | ORM:  |
| admin_level | text | - | no | ORM:  |

- Primary key: `id`.
- Foreign key: `(primary_role_id) -> role (id)`; NO ACTION.
- Foreign key: `(primary_unit_id) -> organization_unit (id)`; NO ACTION.
- Check: `id > 0`.
- Check: `source_order > 0`.
- Check: `year_level >= 0`.
- Unique: `source_order`.
- Index: `ix_university_user_primary_role_id (primary_role_id)`.
- Index: `ix_university_user_primary_unit_id (primary_unit_id)`.

## user_role

Ordered many-to-many assigned role labels.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| user_id | integer | PK; FK -> university_user.id | no | - |
| role_id | integer | PK; FK -> role.id | no | - |
| ordinal | integer | - | no | - |

- Primary key: `user_id, role_id`.
- Foreign key: `(role_id) -> role (id)`; NO ACTION.
- Foreign key: `(user_id) -> university_user (id)`; NO ACTION.
- Check: `ordinal > 0`.
- Unique: `user_id, ordinal`.
- Index: `ix_user_role_role_id (role_id)`.

## waiting_list_entry

Shared consent, responsible-staff preapproval, contextual FCFS identity and notification milestones; requirements and reservations remain in the original room/borrowing records.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| id | bigint | PK | no | identity |
| room_request_id | bigint | FK -> student_room_request.id | yes | - |
| borrow_request_id | integer | FK -> borrow_request.id | yes | - |
| owner_id | integer | FK -> university_user.id | no | - |
| faculty_id | integer | FK -> organization_unit.id | no | - |
| submission_key | varchar(32) | - | no | - |
| fingerprint | varchar(64) | - | no | - |
| queue_key | varchar(64) | - | no | - |
| policy_version | varchar(100) | - | no | - |
| accepted_at | timestamp with time zone | - | no | clock_timestamp() |
| notice_minutes | integer | - | yes | - |
| status | varchar(20) | - | no | ORM: Pending Review |
| approved_by | integer | FK -> login_account.user_id | yes | - |
| approved_at | timestamp with time zone | - | yes | - |
| top_three_notified | boolean | - | no | ORM: False |
| first_notified | boolean | - | no | ORM: False |
| explanation | text | - | no | ORM: Awaiting responsible staff review; no resource is reserved. |

- Primary key: `id`.
- Foreign key: `(approved_by) -> login_account (user_id)`; NO ACTION.
- Foreign key: `(borrow_request_id) -> borrow_request (id)`; NO ACTION.
- Foreign key: `(faculty_id) -> organization_unit (id)`; NO ACTION.
- Foreign key: `(owner_id) -> university_user (id)`; NO ACTION.
- Foreign key: `(room_request_id) -> student_room_request (id)`; NO ACTION.
- Check: `length(policy_version) > 0 AND (notice_minutes IS NULL OR notice_minutes > 0)`.
- Check: `num_nonnulls(room_request_id, borrow_request_id) = 1`.
- Check: `status IN ('Pending Review','Preapproved','Assigned','Rejected','Cancelled','Expired','Ineligible')`.
- Check: `status NOT IN ('Preapproved','Assigned') OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)`.
- Check: `submission_key ~ '^[0-9a-f]{32}$' AND fingerprint ~ '^[0-9a-f]{64}$' AND queue_key ~ '^[0-9a-f]{64}$'`.
- Unique: `borrow_request_id`.
- Unique: `owner_id, submission_key`.
- Unique: `room_request_id`.
- Index: `ix_waiting_faculty_status_id (faculty_id, status, id)`.
- Index: `ix_waiting_list_entry_approved_by (approved_by)`.
- Index: `ix_waiting_list_entry_owner_id (owner_id)`.
- Index: `ix_waiting_queue_status_id (queue_key, status, id)`.

## Confirmed appointment overlap protection

Revision `0042a` uses PostgreSQL btree_gist and an exclusion constraint on `(user_id WITH =, period WITH &&)` in `appointment_commitment`. The generated timestamp range is `[start_at, end_at)`; adjacent reservations are allowed. Cancellation releases commitment rows while appointment/history records remain.

## alembic_version (infrastructure)

Alembic's existing revision marker, not an additional application entity.

| Column | PostgreSQL Type | Keys | Nullable | Generated / Default |
|---|---|---|---|---|
| version_num | varchar(32) | PK | no | - |

No foreign keys, additional indexes or cascading deletion.

## Deferred request subtype integrity

Revision `0041d` adds commit-time constraint triggers to `resource_request`, `request_slot`, `exam_details` and `request_participant`.
Every request has 1-10000 slots; non-recurring requests have exactly one. Exam details exist if and only if the request is an Exam. Participant mappings belong only to CommitteeMeeting requests (an empty committee remains a valid rejected engine input).
Before child writes, a no-op parent revision update serializes each request aggregate and prevents concurrent child-table write skew, including under repeatable read. The triggers do not evaluate allocation rules or increment the application input revision.
SQLAlchemy metadata/Alembic drift checks do not inspect SQL functions; dedicated live tests verify these migration-owned triggers. The physical diagram shows at least one request slot; subtype-specific cardinality is conditional.
