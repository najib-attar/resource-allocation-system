# UC-STU-05 - Resource waiting lists

The [approved use case](../use-cases/UC-STU-05-resource-waiting-lists.pdf) extends,
not replaces, UC-STU-02 and UC-STU-03. See the
[implementation boundaries](../architecture/waiting-lists-design.md).

- Authenticated eligible students may join when their original complete room or
  equipment requirements cannot currently be met. Current versioned policy must
  be explicitly accepted; PostgreSQL records the student, version and timestamp.
- Room review is scoped to one explicitly selected owning faculty; only compatible
  rooms from that faculty may be automatically assigned. Equipment retains its
  original single-faculty request and exact quantities/specifications.
- Current responsible staff may pre-approve or reject despite unavailable stock.
  Pending and pre-approved requests reserve nothing. A replacement responsible
  authority must review again; normal approval routes cannot bypass a queue.
- Automatic assignment reuses C++ feasibility/matching and existing PostgreSQL
  reservations, with fresh authorization, policies, unchanged mandatory needs,
  adequate advance notice and concurrent-writer protection. No second offer
  acceptance is needed; equipment collection remains a separate verified handover.
- Minimum advance notice has no invented default: an administrator must explicitly
  configure positive minutes. Larger already-recorded minima are retained. Late
  availability cannot cause a last-minute automatic booking or penalty. Entries
  still waiting at their requested start expire without a reservation.
- FCFS order uses the join sequence. Estimated and eligible positions are explicitly
  contextual to the same faculty, kind, exact interval and mandatory requirements;
  other compatible queues may compete. A position is not a guarantee. Requests
  cannot be partially fulfilled or silently moved to another interval.
- Students may withdraw waiting entries without penalty. Rejection, cancellation,
  expiration, eligibility changes and fulfillment remove active positions.
- Existing notifications cover join, review, first eligible top-three entry,
  reaching one, assignment and closure. Milestone notifications are deduplicated.
- Room release/reopening and verified usable equipment return/repair trigger
  reevaluation. Overdue dates and return intent never count as physical returns.
  Maintenance rechecks recover safely after interruptions or direct data changes.
- Students see only their own queue information. Current responsible staff see
  authorized applicants/history. Existing authentication, CSRF, notifications,
  appointments, calendars and all academic allocation strategies are preserved.
- No financial penalty, automatic no-show ban or university-wide restriction is
  introduced. Such conduct rules require a separately approved university policy.
