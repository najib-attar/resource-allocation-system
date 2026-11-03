# UI-08 Calendar, My Schedule and Inbox

University month/week/day views, all original date/audience/category/status
controls, academic details, personal timetable/blocks and Inbox now use the shared
student service layout. Tablet/mobile week/day and personal schedules render the
same authorized day entries as an agenda; desktop retains the hourly tables.
The existing event macro is reused. No new calendar read model or scheduling
logic is introduced. Weekend room entries now link to their existing details.

Compact events retain their source notes as well as status. This preserves the
distinction between mandatory confirmed commitments, pending requests, optional
invitations, published academic schedules and nonblocking equipment reminders.
The original unresolved-date warnings remain visible; a separate synthetic
warning account exercises them without changing the populated account's rules.

Personal blocks keep their original CSRF-protected add/remove actions. Existing
blocks are grouped into labeled records, including a truthful empty state and
descriptive remove buttons. Invalid block submissions recover to My Schedule.
Inbox retains per-item link/read, mark-all-through-ID, unread counts and the
private feed. Visible Read/Unread text accompanies the existing styling.

The real preview includes a C++-allocated, explicitly dated and authorized
published academic activity. The fixture and all review accounts live only in
an owned test schema. There is no course-enrollment inference or professor private
schedule browser.

Evidence covers every view at four widths, empty and unresolved calendars, errors,
academic privacy, keyboard/focus/overflow and CSRF. Live browser flows verify view
navigation, actual filters, published details, personal-block creation/removal and
conflict rejection, single/all notification read persistence and cross-account
read denial. `tests.json` / `tests.txt` record the 50 executed calendar, schedule,
loading and notification regressions. No scheduling, notification or security
service code changed.
