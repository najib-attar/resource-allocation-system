# Frontend Design System and Prototype

The frontend remains Flask/Jinja with small, page-specific JavaScript modules.
One `base.html` composes shared navigation and account controls; it does not own
scheduling or database queries. No new frontend framework is required.

## Scope and Review Boundary

The current design checkpoint includes the authenticated application shell,
student home (`/student/`) and new professor-appointment form
(`/appointments/new`). Other student, professor, faculty staff and administrator
pages inherit the shell but retain their existing content and workflows.
This is not a completed application-wide visual migration. Wider rollout requires
visual review of the prototype first.

## Audit and Priorities

The audit covered all 44 existing Jinja templates, the 1,372-line legacy stylesheet,
the separate calendar stylesheet, four page scripts, role-specific routes and their
regression tests. Browser checks focus on the prototype and shared chrome; not
every existing page has received a visual redesign or an accessibility certification.

| Priority | Finding | Response |
|---|---|---|
| High | Wrapping pill navigation competes with headings and user controls, especially on phones and administrator pages. | Shared sidebar, compact header, grouped administration and a keyboard-accessible mobile drawer. |
| High | Student home puts a large timetable before actions, repeats meeting information and offers weak discovery of equipment borrowing. | Real summary cards, next meeting, three service actions and bounded request lists; existing timetable remains expandable. |
| High | New appointment form mixes participants, dates and time feedback without a clear hierarchy. | Three labelled groups, separate searchable participant pickers, explicit selection and validation feedback, approval explanation. |
| High | Shared navigation needs a skip target, consistent focus styling and predictable keyboard dismissal. | Skip link, labelled main region, visible focus, Escape/focus restoration, modal drawer focus containment and inert background. |
| Medium | `panel`, `panel-card`, `form-card`, several badge styles and accumulating global rules produce inconsistent radii, shadows and form spacing. | Opt-in `ui-*` vocabulary and tokens for the prototype; migrate legacy page interiors incrementally, not through global overrides. |
| Medium | Appointment/room lists and detail pages use dense paragraphs; status treatments differ from equipment and administrative pages. | Preserve their behavior now; unify list/detail hierarchy and badges in the approved rollout. |
| Medium | Equipment catalog/inventory combine long forms, tables and raw specification JSON. | Retain all existing capabilities; separate browse/request/desk tasks during later rollout, without changing matching rules. |
| Medium | Administrator request, allocation, raw-data and schedule pages expose technical information at the same visual weight as primary actions. | Keep tools accessible in a separate navigation group; defer content redesign. |
| Medium | Calendars and wide administrative tables need horizontal scrolling and careful mobile labelling. | Preserve bounded scroll containers and existing calendar controls; verify shared shell does not introduce page-level overflow. |
| Low | Repeated CSS values and retired page-specific selectors remain in the legacy stylesheet. | Retain the compatibility stylesheet until its remaining callers migrate; remove selectors only after reference and regression checks. |

The existing shared account, notification, history and timetable components are
useful reuse points, not duplicate implementations to discard. No new global
JavaScript state framework or duplicated backend authorization is introduced.

## Visual Direction and Framework Decision

[Tabler's layout](https://docs.tabler.io/ui/layout/page-layouts) and
[component guidance](https://docs.tabler.io/ui/components) informed the restrained
dashboard hierarchy: persistent workspace navigation, compact page chrome, calm
surfaces and readable state labels. Tabler is a Bootstrap-based UI kit, but neither
Tabler nor Bootstrap is installed or copied into this prototype. Adding another
global stylesheet/reset over the current application would increase collision risk
and require a wider migration than this checkpoint allows.

Lightweight local CSS, semantic Jinja components and existing vanilla JavaScript
provide the needed behavior without a frontend build pipeline, remote CDN or new
dependency. Inline line icons are defined once in the component macro. No external
font, photograph, fabricated chart or production statistic is requested at runtime.

### Design Tokens

`web/static/tokens.css` is the single token entry point. The `--ui-*` namespace
avoids accidentally changing the legacy service palette.

| Area | Baseline |
|---|---|
| Typography | Local Bahnschrift / Avenir Next / Trebuchet fallback stack; restrained weights, short headings and tabular summary numbers. Rendering varies with installed fonts. |
| Surfaces | Neutral `#f5f6f8` workspace, white cards, subtle background tint and low-elevation shadows. |
| Navigation | Deep slate-teal `#172f36`, muted readable labels, explicit active text/icon marker. |
| Primary action | Teal `#17695d`, hover `#105247`; secondary actions use bordered white surfaces. |
| Text | `#202e3b` primary and `#5b6a79` secondary. |
| Control boundaries | `#81908f` against white (3.32:1); structural card dividers remain lighter. |
| States | Separate success, warning and danger foreground/background pairs; always accompanied by text, never color alone. |
| Spacing | 4, 8, 12, 16, 24, 32 and 48px tokens; compact controls and generous section separation. |
| Shape | 6px controls, 12px cards, 16px larger surfaces; light borders instead of heavy gradients/shadows. |
| Focus and motion | Visible blue focus ring, 44px primary controls, reduced-motion support; no ornamental animation. |

The seven checked text/state pairs have contrast ratios from 5.55:1 to 13.86:1.
This checks core palette pairs, not every legacy page or every possible composition.

### CSS and Template Composition

```text
base.html
  + tokens.css                   shared design values
  + shell.css / shell.js          authenticated chrome and drawer only
  + components/_navigation.html  role-aware links, existing endpoints
  + components/_account_controls.html
  + components/ui.html           icons, badges, stats, section headings
  + page content
      student_home.html          existing StudentDashboardService data
      appointment_new.html       existing appointment endpoints and payload
          + prototype.css        opt-in component and page styles
          + appointments.js      existing picker/time flow and feedback
```

`style.css` remains the compatibility layer for unmigrated page interiors, loaded
before the new files. `shell.css` owns only authenticated chrome; `prototype.css`
is loaded by the two prototype pages and scopes legacy overrides to
`.portal-prototype`. Do not restyle unrelated service interiors by adding global
element overrides. Reuse `.ui-card`, `.ui-button`, `.ui-field`, `.ui-alert`,
`badge`, `stat_card` and `section_heading` for approved future pages. Existing
table/timetable components are retained, not replaced with a second calendar.
The mobile navigation drawer is the only new modal surface; a generic dialog
framework is unnecessary until a real workflow needs one.

### Prototype Behavior

Student cards use existing participant-scoped PostgreSQL queries and their real
totals. Appointment invitations are not counted as organizer reservations. Room
counts are clearly labelled; equipment is a catalog action, not a fabricated loan
count. Bookings, pending requests, invitations, history links and month/week
timetable selection remain accessible. Explicit week/month links open the
timetable automatically; unresolved calendar bindings remain visible warnings.

The appointment form retains all existing field names, endpoints, CSRF token,
faculty filtering, optional invitations, manual proposals and engine-generated
recommendations. Client feedback adds a validation summary, busy indication,
selected-time treatment and distinct integration-error messaging. Native validation
and server checks remain authoritative; no scheduling decision is computed in CSS
or JavaScript. The approval explanation is future-tense guidance, not a fake saved
request status. Existing server-error and detail pages remain available unchanged.

On mobile/tablet, the sidebar becomes a labelled drawer. Escape and close restore
focus; focus is contained while open and page content is inert. Navigation remains
available if JavaScript is disabled. Account actions use a native disclosure and
POST/CSRF sign-out; notifications retain their existing service and script.

## Rollout After Visual Approval

1. Refine the prototype against desktop/mobile feedback before changing more pages.
2. Migrate student appointment/room/equipment list and detail views to the shared
   components, preserving permissions, history and lifecycle controls.
3. Migrate professor office-hours/approval views and faculty room/equipment desks
   separately; maintain role-specific information and scope.
4. Migrate administrative tables, filters and request forms; use one semantic,
   responsive table/form vocabulary instead of page-specific copies.
5. Review calendar presentation and retire legacy CSS only after every caller is
   migrated and regression checks pass. Broader accessibility and cross-browser
   testing follow the full rollout, not a claim of completion at this checkpoint.

Each batch requires route, CSRF, authorization/privacy, responsive and keyboard
checks. PostgreSQL records, C++ rules/strategies and JSON protocols are outside
this visual migration.

## Verification

Eight focused prototype tests cover role navigation, escaped identity/components,
local assets, main/skip targets, POST/CSRF sign-out, real dashboard data, private
peer isolation, unchanged form payloads, successful persistence, rejection of
unauthorized/invalid submissions and engine time feedback. Token-level assertions
guard 4.5:1 text/state contrast and 3:1 control-boundary contrast. Two notification tests'
markup assertions now check actual destinations/components rather than a particular
text-node nesting.

| Executed verification | Result |
|---|---|
| Full Python/PostgreSQL suite on Windows | 322 run: 321 passed, 0 failed, 1 POSIX executable-permission test skipped; includes all five strategy parity checks, JSON, migrations, rollback, concurrency, recovery and existing Flask workflows. |
| Final focused prototype rerun | 8 passed, 0 failed after final markup/test assertions. |
| Fresh C++ suite via `tests/run_tests.ps1` | 172 passed, 0 failed; both isolated CLI smoke scenarios passed. |
| Existing authenticated route checks | 32 passed across student, professor and administrator; runtime CSV/result-file access forbidden. Staff shell/permissions covered by isolated tests. |
| Browser acceptance | Real login, faculty/participant selection, empty availability, recommendations, required-purpose validation, submission, professor notification/approval, student pending-to-confirmed counts and hourly timetable verified in a disposable PostgreSQL fixture. |
| Responsive/keyboard | Desktop 1440px, tablet 768px, mobile 390px and narrow 320px; no prototype page-level overflow, labelled fields, drawer Tab containment/Escape/focus restoration, account/bell, skip target and timetable navigation checked. |
| Syntax and integrity | All Jinja templates, Python test/SVG syntax and changed JavaScript syntax passed. Primary 47 application tables plus Alembic metadata and four preexisting generated CSV hashes unchanged. |

Before/after dashboard and form screenshots accompany the desktop/mobile review.
The final fresh browser preview logged no console errors. These are local Chromium
checks with resized viewports, not physical-device, Firefox/Safari or full assistive-
technology certification. No standalone CSS linter was installed; appearance was
verified in the browser. Remote CI was not run because this checkpoint remains local.

| Boundary | Responsibility |
|---|---|
| `components/_navigation.html` | One shared navigation definition; student Home, professor Office Hours and granted Administration tools |
| `components/_account_controls.html` | Circular initials avatar, display name, role, notification bell and sign-out |
| `components/_notification_items.html` | One autoescaped notification-list renderer, reused by dropdown and full inbox |
| `notifications.js` | Bell disclosure, keyboard/outside dismissal, unread badge, read actions and bounded visible-page refresh |
| `notification_routes.py` | Authenticated presentation and CSRF-protected read actions; never accepts a caller-supplied recipient |
| `NotificationService` | Bounded recipient-scoped queries, current source visibility and durable read state |
| Existing student / appointment / room blueprints | Their own forms, services, permissions and lifecycle actions |
| Equipment blueprint and `equipment.js` | Student catalog/forms, scoped custodian inventory/loan actions and administrator assignment; shared layout, no client-side matching rules |

Role-aware navigation is a convenience, not authorization. Existing backend role,
ownership and designated-faculty checks remain authoritative. An administrator is
not automatically a participant in every private appointment/room notification.
Shared components contain no duplicated allocation rules or role-specific business
logic. Scheduling stays in C++; transactions remain in application services.

History and notification receipts are written in the same transaction using
`publish_event`. The inbox follows structured foreign keys rather than parsing
history text. Normalized source events retain the original explanation, including
approval, rejection, invitations, revisions and cancellations. Read operations
do not modify request status. Mark-all-read does not acknowledge newer arrivals.

The dropdown loads at page entry and opening, on return to the page, and once per
minute while visible. Failure is shown as unavailable, not a false empty inbox.
The full inbox and read-all form work without JavaScript. Private responses use
`Cache-Control: no-store`; strings remain Jinja-escaped. Removed invitees lose
access even to previously delivered updates. Equipment history events use the
same inbox with borrower/current-custodian visibility; catalog availability never
reveals other borrowers or inventory identifiers before approval.

No profile photographs are stored today: initials are an honest fallback, not a
photo-upload implementation. Future approved photo storage and availability alerts
can extend the account component and notification boundary without copying the
header or modifying role-specific pages. No availability watcher, email/push,
message queue or WebSocket infrastructure is implied.
