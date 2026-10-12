# Physical schema catalog

Generated from SQLAlchemy metadata. `alembic_version` is migration infrastructure, not one of the 18 application tables.

All foreign keys use PostgreSQL **NO ACTION**: no implicit cascading deletion. Nullable columns are explicitly listed; all others are NOT NULL.
ORM Python defaults are not server defaults. SQL import/admin tools must supply required values unless an identity/server default is listed.

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

- Primary key: `id`.
- Foreign key: `(active_run_id) -> allocation_run (id)`; NO ACTION.
- Check: `id = 1 AND input_revision >= 0`.
- Check: `strategy IN ('greedy','priority','multi_room_exam_greedy','multi_room_exam_best_fit','shared_room_exam_best_fit')`.

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

## resource_request

Ordered request identity, requester, preferred resource and requirements.

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

- Primary key: `id`.
- Foreign key: `(requester_id) -> university_user (id)`; NO ACTION.
- Foreign key: `(resource_id) -> resource (id)`; NO ACTION.
- Check: `(submission_key IS NULL AND submission_fingerprint IS NULL) OR (submission_key IS NOT NULL AND submission_fingerprint IS NOT NULL AND submission_key ~ '^[0-9a-f]{32}$' AND submission_fingerprint ~ '^[0-9a-f]{64}$')`.
- Check: `id > 0 AND participant_count > 0 AND revision > 0`.
- Check: `submission_order > 0`.
- Check: `type IN ('OneTime','Recurring','Exam','CommitteeMeeting')`.
- Unique: `submission_key`.
- Unique: `submission_order`.
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
