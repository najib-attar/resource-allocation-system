# UC-STU-02 - Implemented student room requirements

UC-STU-06 adds explicit student group registration using existing room
participation records and optional private feedback after use (problem reports
during active use). See [shared feedback requirements](UC-STU-06-requirements.md).
Attendee counts alone do not establish membership. Approval/selection rules remain
unchanged; individual participation does not reserve a personal calendar.

This current addendum complements [the approved use case](../use-cases/UC-STU-02-student-room-allocation.pdf)
and the original SRS without rewriting historical reports.

- Authenticated students describe one activity, total attendance, facilities,
  a dated interval and optional faculty/building preferences. Study, meeting,
  student-led lecture, declared club activity and other permitted purposes use
  one lifecycle. Club membership is not implied or verified.
- C++ proposes eligible single rooms with deterministic best-fit ranking and
  explanations. Students review the top choice or another verified candidate;
  preferences do not grant access. Cross-faculty candidates are supported.
- Explicit ownership, a valid designated faculty approver, capacity, facilities,
  category policy, whitelists, closures and applicable academic schedules are
  mandatory. Unknown legacy calendar applicability is never treated as free.
- Pending faculty approval holds nothing. Only the assigned, currently designated
  room-faculty approver may confirm/reject. Confirmation revalidates the exact
  revision/room/time and creates exclusive room and organizer commitments atomically.
- A stale selection needs revision, never silent substitution. Material revisions
  reset approval and invitations. Confirmed changes require cancellation and a
  new request. Organizer/current assigned approver cancellation releases time and
  retains history. Later academic allocation publication must respect reservations.
- Optional professors accept/decline independently. Acceptance checks their known
  calendar, but remains optional attendance rather than an exclusive reservation;
  neither response vetoes room approval or changes existing commitments.
- In-app request lists/details expose decisions, invitations and history only to
  organizer, assigned approver and invitees. Other permitted room-calendar viewers
  see free/busy only. Authentication, backend authorization and CSRF remain enabled.
- Dates use configurable Europe/Istanbul and half-open intervals. PostgreSQL is
  authoritative; C++ has no SQL dependency. Existing academic/exam allocation and
  appointment protocols remain compatible.

See [architecture](../architecture/student-room-design.md), [database](../architecture/database-design.md)
and [engine contract](../engine-protocol.md).

Unavailable eligible requests may explicitly opt into the separate
[UC-STU-05 waiting-list extension](UC-STU-05-requirements.md). It adds consent and
faculty-scoped pre-approval, without replacing normal available-room submission.

## Bounded recurring room extension

Students may select weekly weekdays, explicit inclusive start/end dates and a
local start/duration, previewing every actual dated occurrence. One eligible room
is preferred consistently; conflicting dates are explained without silent room
substitution. Students select all occurrences required or partial approval allowed.
The owning faculty reviews exact dates: all-required confirmation is atomic;
partial mode permits selected feasible dates, with persistent unapproved,
unavailable, rejected and cancelled outcomes. Only confirmed dates reserve rooms.
An explicitly designated semester must contain every interval; missing configuration
blocks recurrence, not one-time bookings. Configured quotas have no invented defaults.
Existing eligible waiting requests retain priority/FCFS ordering. Responsible staff
may override configured priority only with immutable actor/time/old/new/reason audit;
eligibility, safety and confirmed reservations are never overridden. Optional professors remain non-vetoing.
Organizer/current approver may cancel one future occurrence or remaining future
dates, preserving past uses. Material changes require a fresh approval. Calendar
entries come from actual occurrences, not guessed academic dates. Single-period
waiting-list consent does not create a series queue. See
[shared recurrence architecture](../architecture/recurring-reservations-design.md).
