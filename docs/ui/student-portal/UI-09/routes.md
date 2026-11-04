# Complete route inventory

Generated from the running Flask route map. Service methods continue to enforce ownership, role, state and revision checks.

| Route | Methods | Endpoint | Phase | Access |
|---|---|---|---|---|
| `/` | GET | index | UI-01 / role redirect | Session-scoped student capability; service guards remain authoritative |
| `/add-exam` | GET,POST | add_exam | Existing administration / static asset | Existing administration / static asset |
| `/add-one-time` | GET,POST | add_one_time | Existing administration / static asset | Existing administration / static asset |
| `/add-request` | GET,POST | add_request | Existing administration / static asset | Existing administration / static asset |
| `/allocation-summary` | GET | allocation_summary | Existing administration / static asset | Existing administration / static asset |
| `/allocations` | GET | allocations | Existing administration / static asset | Existing administration / static asset |
| `/appointments/` | GET | appointments.index | UI-03 | Session-scoped student capability; service guards remain authoritative |
| `/appointments/<int:appointment_id>` | GET | appointments.detail | UI-03 | Session-scoped student capability; service guards remain authoritative |
| `/appointments/<int:appointment_id>/cancel` | POST | appointments.cancel | UI-03 | Session-scoped student capability; service guards remain authoritative |
| `/appointments/<int:appointment_id>/decision` | POST | appointments.decision | UI-03 | Required professor only |
| `/appointments/<int:appointment_id>/decline-invitation` | POST | appointments.decline | UI-03 | Session-scoped student capability; service guards remain authoritative |
| `/appointments/<int:appointment_id>/reschedule` | POST | appointments.reschedule | UI-03 | Session-scoped student capability; service guards remain authoritative |
| `/appointments/availability` | GET,POST | appointments.availability | Future student browsing / professor management only | Professor office-hours management; student denied |
| `/appointments/calendar` | GET,POST | appointments.calendar | UI-08 | Session-scoped student capability; service guards remain authoritative |
| `/appointments/calendar-setup` | GET,POST | appointments.bindings | Administration only | Administration only |
| `/appointments/new` | GET,POST | appointments.new | UI-03 | Session-scoped student capability; service guards remain authoritative |
| `/appointments/times` | POST | appointments.times | UI-03 | Session-scoped student capability; service guards remain authoritative |
| `/calendar/` | GET | calendar.index | UI-08 | Session-scoped student capability; service guards remain authoritative |
| `/calendar/academic/<int:request_id>` | GET | calendar.academic | UI-08 | Session-scoped student capability; service guards remain authoritative |
| `/calendar/publications` | GET,POST | calendar.publications | UI-08 | Administration only |
| `/equipment/` | GET | equipment.index | UI-05 | Session-scoped student capability; service guards remain authoritative |
| `/equipment/<int:request_id>` | GET | equipment.detail | UI-05 | Session-scoped student capability; service guards remain authoritative |
| `/equipment/<int:request_id>/<action>` | POST | equipment.transition | UI-05 | Session-scoped student capability; service guards remain authoritative |
| `/equipment/catalog` | GET,POST | equipment.catalog | UI-05 | Session-scoped student capability; service guards remain authoritative |
| `/equipment/custodians` | GET,POST | equipment.custodians | UI-05 | Administration only |
| `/equipment/inventory/<int:faculty_id>` | GET,POST | equipment.inventory | UI-05 | Current owning-faculty custodian only |
| `/exam-summary` | GET | exam_summary | Existing administration / static asset | Existing administration / static asset |
| `/feedback/` | GET | feedback.index | UI-07 | Session-scoped student capability; service guards remain authoritative |
| `/feedback/<int:report_id>` | GET | feedback.detail | UI-07 | Session-scoped student capability; service guards remain authoritative |
| `/feedback/<int:report_id>/update` | POST | feedback.update | UI-07 | Session-scoped student capability; service guards remain authoritative |
| `/feedback/new/<kind>/<int:booking_id>` | GET,POST | feedback.new | UI-07 | Session-scoped student capability; service guards remain authoritative |
| `/login` | GET,POST | login | UI-02 | Session-scoped student capability; service guards remain authoritative |
| `/logout` | POST | logout | UI-02 | Session-scoped student capability; service guards remain authoritative |
| `/notifications/` | GET | notifications.index | UI-08 | Session-scoped student capability; service guards remain authoritative |
| `/notifications/feed` | GET | notifications.feed | UI-08 | Session-scoped student capability; service guards remain authoritative |
| `/notifications/read` | POST | notifications.read | UI-08 | Session-scoped student capability; service guards remain authoritative |
| `/raw-data` | GET | raw_data | Existing administration / static asset | Existing administration / static asset |
| `/request-added/<request_id>` | GET | request_added | Existing administration / static asset | Existing administration / static asset |
| `/request/<request_id>` | GET | request_detail | Existing administration / static asset | Existing administration / static asset |
| `/requests` | GET | requests | Existing administration / static asset | Existing administration / static asset |
| `/results` | GET | results | Existing administration / static asset | Existing administration / static asset |
| `/rooms/` | GET | rooms.index | UI-04 | Session-scoped student capability; service guards remain authoritative |
| `/rooms/<int:request_id>` | GET | rooms.detail | UI-04 | Session-scoped student capability; service guards remain authoritative |
| `/rooms/<int:request_id>/cancel` | POST | rooms.cancel | UI-04 | Session-scoped student capability; service guards remain authoritative |
| `/rooms/<int:request_id>/decision` | POST | rooms.decision | UI-04 | Assigned faculty approver only |
| `/rooms/<int:request_id>/invitation` | POST | rooms.invitation | UI-04 | Invited professor response only |
| `/rooms/<int:request_id>/occurrences/<int:occurrence_id>/cancel` | POST | rooms.cancel_occurrence | UI-04 | Session-scoped student capability; service guards remain authoritative |
| `/rooms/<int:request_id>/revise` | GET,POST | rooms.revise | UI-04 | Session-scoped student capability; service guards remain authoritative |
| `/rooms/availability/<int:room_id>` | GET | rooms.availability | UI-04 | Session-scoped student capability; service guards remain authoritative |
| `/rooms/candidates` | POST | rooms.candidates | UI-04 | Session-scoped student capability; service guards remain authoritative |
| `/rooms/configuration` | GET,POST | rooms.configuration | UI-04 | Authorized resource management only |
| `/rooms/new` | GET,POST | rooms.new | UI-04 | Session-scoped student capability; service guards remain authoritative |
| `/run-allocation` | POST | run_allocation | Existing administration / static asset | Existing administration / static asset |
| `/run-allocation-now/<request_id>` | POST | run_allocation_now | Existing administration / static asset | Existing administration / static asset |
| `/schedules` | GET | schedules | Existing administration / static asset | Existing administration / static asset |
| `/set-strategy` | POST | set_strategy | Existing administration / static asset | Existing administration / static asset |
| `/spaces` | GET | spaces | Existing administration / static asset | Existing administration / static asset |
| `/static/<path:filename>` | GET | static | Existing administration / static asset | Existing administration / static asset |
| `/student/` | GET | student.home | UI-01 | Session-scoped student capability; service guards remain authoritative |
| `/users` | GET | users | Existing administration / static asset | Existing administration / static asset |
| `/waiting-lists/` | GET | waiting.index | UI-06 | Session-scoped student capability; service guards remain authoritative |
| `/waiting-lists/<int:entry_id>` | GET | waiting.detail | UI-06 | Session-scoped student capability; service guards remain authoritative |
| `/waiting-lists/<int:entry_id>/cancel` | POST | waiting.cancel | UI-06 | Session-scoped student capability; service guards remain authoritative |
| `/waiting-lists/<int:entry_id>/review` | POST | waiting.review | UI-06 | Current responsible faculty/custodian only |
| `/waiting-lists/configuration` | GET,POST | waiting.configuration | UI-06 | Administration only |
| `/waiting-lists/policy` | GET | waiting.policy | UI-06 | Session-scoped student capability; service guards remain authoritative |
| `/waiting-lists/priority/<kind>/<int:request_id>` | POST | waiting.priority | UI-06 | Authorized current resource responsibility only |
| `/waiting-lists/refresh` | POST | waiting.refresh | UI-06 | Session-scoped student capability; service guards remain authoritative |
