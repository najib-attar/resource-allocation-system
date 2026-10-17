# Unified university calendar

The authenticated university calendar integrates existing PostgreSQL records;
it does not create a second booking store or replace service approvals.

- All signed-in university roles have monthly, weekly and daily views, date and
  Previous/Next/Today navigation, category/status filters and authorized detail links.
- Private appointments are visible only to organizers, required professors and
  invited students, including their own invitation and current approval progress.
- Room activities are visible to organizers, invited professors and the currently
  authorized assigned faculty reviewer. Others receive no private activity details.
- Equipment borrowers see their own requests and reminders; current authorized
  custodians see relevant managed requests. Pickup, due and recorded physical
  handover/return times are reminders, never participant-busy intervals.
- Academic activities use active allocations and explicit academic periods,
  planning weeks and exceptions. Own weekly busy slots remain private. Unresolved
  legacy dates produce warnings and are never guessed.
- Public academic metadata requires explicit administrator publication. Committees
  remain private. Publication never exposes enrollment lists or private purposes.
  A professor label is optional and explicit, not an inferred teaching commitment.
- Pending, confirmed, declined/rejected, cancelled, completed and overdue display
  states follow authoritative records. Derived completion does not mutate lifecycle.
- The configured university timezone defaults to Europe/Istanbul. Intervals are
  half-open. Each response reads one coherent database snapshot and is not cached.
- Existing C++ allocation/scheduling protocols, workflows and permissions remain.

Acceptance coverage: `tests/test_university_calendar.py`, existing PostgreSQL,
service, JSON and C++ regression suites, and role-specific browser verification.
