# UC-STU-02 - Implemented student room requirements

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
