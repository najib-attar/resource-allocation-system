# Student Portal UI-01

UI-01 applies the approved Campus Space Concept 04 visual direction to the existing
Flask/Jinja Student Home and student navigation. It introduces no routes, database
changes, scheduling changes, frontend framework, or service business rules.

## Design comparison

The implementation keeps the reference's pale desktop sidebar, four primary
destinations, generous whitespace, blue appointment card, sand room card, sage
equipment card, two secondary service tiles, and smaller activity/calendar column.
At tablet and mobile widths navigation moves to the bottom; cards and secondary
content stack as space decreases. At 320px the service pairs become single columns.

The real account menu, notification feed, CSRF-protected sign out and keyboard skip
link replace prototype controls. Search, pretend filters, service dialogs, sample
counts and fictional prototype activity are omitted. Calendar markers indicate
actual dated entries; decorative prototype timeline bars are replaced with linked,
dated events and their original kinds.

## Preserved application routes

| Destination | Existing route |
| --- | --- |
| Home | `/student/` |
| My Activity | `/student/#my-activity` |
| University Calendar | `/calendar/` |
| Inbox | `/notifications/` |
| Appointments | `/appointments/` |
| Rooms and spaces | `/rooms/` |
| Equipment borrowing | `/equipment/` |
| Waiting lists | `/waiting-lists/` |
| Feedback and issues | `/feedback/` |
| Personal schedule and blocks | `/appointments/calendar` |

The five service hubs appear in Home's service area, not the student's primary
navigation. Their existing lists, forms, details, history, availability checks,
invitations and permitted actions remain authoritative. Instructor, staff and
administrator navigation retain the existing shell. A Student who also has
administrator authority retains administration navigation.

## Existing data and limits

`StudentDashboardService.load` remains unchanged and supplies one student-scoped
database snapshot. Home presents up to five supplied current appointment/room
cards ordered by scheduled start time. This is a request summary, not a complete
recent-update feed: the model supplies neither update timestamps nor equipment,
waiting-list or feedback summaries. Each service's complete list remains available.

Pending requests remain pending and reserve no time. Optional invitations are
identified separately even when the organizer's meeting is confirmed. Recurring
room summaries retain statuses such as `Partially Confirmed` verbatim.

The week preview uses the existing personal schedule, including supplied weekend
entries, optional attendance and personal blocks. It shows up to three unique dated
events; weekday markers link to the real calendar day and View week opens the full
calendar. Equipment reminders belong to the full University Calendar and are not
shown as occupied time. Unresolved academic-period bindings remain a visible
warning. Neither empty previews nor markers are availability checks. No professor
private schedule is queried or displayed.

## Implementation

| File | Change |
| --- | --- |
| `README.md` | Updated student landing-page description and evidence link |
| `web/templates/base.html` | Conditional student shell and Home heading |
| `web/templates/components/_navigation.html` | Four student primary links |
| `web/static/shell.js` | Student bottom navigation with retained account behavior |
| `web/static/student-shell.css` | Student-only responsive chrome |
| `web/templates/student_home.html` | Service discovery, current activity and compact calendar |
| `web/static/student-home.css` | Scoped responsive Home styles |
| `tests/test_student_portal_ui.py` | Presentation, status, escaping and role contracts |
| `tests/test_frontend_prototype.py` | Updated superseded dashboard/navigation expectations |
| `tests/ui/student_portal_preview.py` | Isolated fictional PostgreSQL preview fixture |
| `tests/ui/capture_student_portal.cjs` | Real browser checks and screenshot capture |
| `tests/ui/check_student_controls.cjs` | Keyboard, notification and cross-role mobile controls |

## Reproducing browser verification

Build the existing backend with `python scripts/build_backend.py`. Set
`TEST_DATABASE_URL` to a disposable PostgreSQL database and run
`python -B tests/ui/student_portal_preview.py`. This reuses the test harness to
migrate a unique owned schema, provisions fictional accounts, and serves the real
application on loopback port 5051. Account details are written under ignored
`build/ui01/preview.json`. Stop the preview normally to clean up the owned schema.
`UI01_PORT` overrides the port. The review instance uses
`http://127.0.0.1:5052/student/?week=2030-01-07`, with fictional login
`ui01-student` (populated) or `ui01-empty` (empty), password
`Fictional-UI01-review-password`. These accounts belong only to the disposable
review schema.

With Playwright available, run `node tests/ui/capture_student_portal.cjs`.
Run `node tests/ui/check_student_controls.cjs` for the additional control checks.
`PLAYWRIGHT_NODE_MODULE` can identify an existing Playwright installation;
`CHROMIUM_EXECUTABLE` can select an installed browser. No application routes,
authentication or notification responses are mocked. The script uses Edge by
default and writes captures alongside this document.

## Visual evidence

These captures show the real loopback Flask application using fictional accounts
and PostgreSQL records. The selected fixture week is 7–13 January 2030; the Home
greeting date comes from the real application clock. Fixed mobile navigation
appears at the viewport edge within full-page screenshots, as in the reference.

| Width | Populated | Empty |
| --- | --- | --- |
| 1440px | [Desktop](https://github.com/najib-attar/resource-allocation-system/blob/747c925b14c29368e6cb9bc8b2e2d9d33c494462/docs/ui/student-portal-ui01/populated-1440.png) | [Desktop empty](https://github.com/najib-attar/resource-allocation-system/blob/747c925b14c29368e6cb9bc8b2e2d9d33c494462/docs/ui/student-portal-ui01/empty-1440.png) |
| 768px | [Tablet](https://github.com/najib-attar/resource-allocation-system/blob/747c925b14c29368e6cb9bc8b2e2d9d33c494462/docs/ui/student-portal-ui01/populated-768.png) | [Tablet empty](https://github.com/najib-attar/resource-allocation-system/blob/747c925b14c29368e6cb9bc8b2e2d9d33c494462/docs/ui/student-portal-ui01/empty-768.png) |
| 390px | [Mobile](https://github.com/najib-attar/resource-allocation-system/blob/747c925b14c29368e6cb9bc8b2e2d9d33c494462/docs/ui/student-portal-ui01/populated-390.png) | [Mobile empty](https://github.com/najib-attar/resource-allocation-system/blob/747c925b14c29368e6cb9bc8b2e2d9d33c494462/docs/ui/student-portal-ui01/empty-390.png) |
| 320px | [Small mobile](https://github.com/najib-attar/resource-allocation-system/blob/747c925b14c29368e6cb9bc8b2e2d9d33c494462/docs/ui/student-portal-ui01/populated-320.png) | [Small mobile empty](https://github.com/najib-attar/resource-allocation-system/blob/747c925b14c29368e6cb9bc8b2e2d9d33c494462/docs/ui/student-portal-ui01/empty-320.png) |

Browser results: [dashboard and routes](https://github.com/najib-attar/resource-allocation-system/blob/747c925b14c29368e6cb9bc8b2e2d9d33c494462/docs/ui/student-portal-ui01/browser-results.json),
[keyboard and controls](https://github.com/najib-attar/resource-allocation-system/blob/747c925b14c29368e6cb9bc8b2e2d9d33c494462/docs/ui/student-portal-ui01/controls-results.json).

## Verification

Real browser verification covers both dashboard states at all four widths without
horizontal overflow; real login/logout; all five service routes; notification
feed, popover bounds and persisted mark-all-read; rejected logout without CSRF;
keyboard skip/focus, Activity anchor and account/notification Escape behavior;
student privacy; and unchanged professor/staff/administrator mobile drawers.
No browser JavaScript errors occurred. Student requests to professor office-hours
management remain forbidden.

The keyboard checks also verify that focused controls are unobscured by fixed
navigation. Mobile focus targets have scroll margins so automatic keyboard
scrolling keeps them above the bottom bar.

The full Python/PostgreSQL discovery executed **608 tests across 47 modules:
607 passed, 1 expected platform skip, 0 failures/errors**. The skipped check tests
POSIX executable permissions on Linux; this run used Windows. No PostgreSQL or
workflow tests were skipped. Real backup/restore (4), notifications (11), student
dashboard (14), new UI contracts (10), and existing frontend workflows (8) passed.
All discovered modules ran unchanged with
`python -B -m unittest discover -s tests -p '<module>.py' -v` in six isolated
processes against a dedicated PostgreSQL 17 cluster. Discovery and executed counts
matched exactly. Elapsed time was 22m23s; earlier partial/focused runs are excluded
from these totals. See [Python regression results](https://github.com/najib-attar/resource-allocation-system/blob/747c925b14c29368e6cb9bc8b2e2d9d33c494462/docs/ui/student-portal-ui01/python-results.json).

The C++ regression driver passed **192 tests, 0 failures**. Both existing backend
runtime smoke cases passed: clean-slot and normal-dataset. The authoritative
backend was built from the unchanged local `src/` tree.

## Proposed UI-02

1. Review whether a unified My Activity page is needed. If approved, define a
   paginated cross-service read model with actual update timestamps, ownership
   checks, clear request/booking/invitation/reminder types, and privacy tests.
2. Apply the approved styling to the existing appointment hub/list/detail/form,
   preserving required-professor approval and optional student invitations.
3. Review calendar/Inbox visual consistency separately. Room, equipment, waiting
   list and feedback interiors remain later tasks.

A published-office-hours browser requires a separate privacy review. UI-02 does
not imply access to professors' private schedules or activation of CDMCS.
