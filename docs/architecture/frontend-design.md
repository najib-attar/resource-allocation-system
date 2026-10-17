# Shared frontend shell and role-specific workflows

The frontend remains Flask/Jinja with small, page-specific JavaScript modules.
One `base.html` composes shared navigation and account controls; it does not own
scheduling or database queries. No new frontend framework is required.

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
