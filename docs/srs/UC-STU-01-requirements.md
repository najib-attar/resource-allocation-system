# UC-STU-01 - Implemented scheduling requirements

This current addendum complements [the approved use case](../use-cases/UC-STU-01-student-professor-appointment.pdf)
and the original SRS PDF without rewriting historical requirements.

- Authenticated students select a configured faculty, one or more professors,
  purpose, duration and optional invited students. All four one/many student and
  professor combinations are supported.
- Professors publish bounded weekly office hours with explicit validity dates and
  exclusions; dated blocks exclude whole dates or intervals. Organizer unavailability
  is represented by personal blocks and applicable confirmed university commitments.
- Students choose feasible recommended times or manually propose a time. The same
  mandatory availability rules apply: organizer and all professors must be free,
  inside published professor windows, for the complete duration.
- Optional students influence deterministic ranking but never confirmation. Invitations
  may remain unanswered or decline; organizers cancel rather than decline themselves.
- Pending requests reserve nothing. Every required professor approves the same revision;
  rejection prevents confirmation. Availability is rechecked and confirmed mandatory
  commitments saved transactionally, with per-person overlap protection.
- Organizer time changes invalidate approvals and release any previous reservations.
  The organizer or selected professor may cancel; cancellation releases commitments
  and updates participant-visible history/calendars.
- Dated calendars use explicitly configurable Europe/Istanbul and half-open intervals.
  Existing undated weekly room allocation remains unchanged. Legacy applicability
  requires explicit academic-period association; unknown mandatory applicability
  produces a configuration error, never an assumed conflict-free recommendation.
- Appointment data and calendars are visible only to participants; administrative
  technical views require a separately granted management permission. No email,
  self-registration, university directory synchronization or enrollment roster is
  implied. Activity/status pages provide in-application request and invitation visibility.

See [architecture](../architecture/appointments-design.md), [engine contract](../engine-protocol.md)
and [operations](../database-operations.md) for technical boundaries and configuration.
