# UC-STU-03 - Equipment borrowing requirements

This current addendum complements the [approved use case](../use-cases/UC-STU-03-student-equipment-borrowing.pdf).

- Equipment types describe specifications and faculty borrowing policy; physical
  units have unique asset identifiers and separately recorded condition. Categories
  are extensible. Existing room resource types and strategies are not repurposed.
- Students browse eligible equipment without other borrowers' details, request
  multiple types/quantities from one faculty, and provide purpose, dated pickup,
  expected return and optional notes/specifications. Separate faculties require
  separate requests. Repeated unchanged form submission is idempotent.
- C++ matches exact requirements, eligibility, policy, condition, possession and
  overlapping reservations. Deterministic selection never duplicates an asset or
  silently fulfills a smaller quantity. Compatible alternatives require an explicit
  amended selection; infeasibility is explained.
- Each faculty has one current active authorized staff/administrator equipment
  custodian. Administration explicitly assigns/replaces this responsibility;
  room-approver assignment does not imply equipment authority. Missing/disabled
  custodian configuration prevents new approval/submission.
- Pending requests reserve nothing. Custodian approval rechecks complete availability
  and atomically reserves exact units. Rejection records a decision without a hold.
- Approved means awaiting pickup, not borrowed. Custodian handover verifies actual
  identifiers and condition during the reservation interval and records possession,
  actor, time and due date. A student cannot check equipment out themselves.
- Only custodian-verified physical return releases a unit. Return intent does not.
  Partial returns leave outstanding units borrowed. Damaged/maintenance returns
  remain unavailable; missing/lost units are not recorded as physically returned.
- Pending/approved uncollected requests may be cancelled. Borrowed loans cannot
  be cancelled; they require return. Students may request an extension, which
  requires custodian approval and fresh policy/reservation checks.
- An unreturned device stays unavailable regardless of due date. Existing future
  reservations threatened by an outstanding or unusable device are flagged for
  staff; handover cannot override physical possession. Overdue warnings and durable
  in-app alerts have no financial penalties or automatic return assumption.
- Students see their own loan records only. Custodians access their current faculty
  scope; administrators assign authority but do not automatically inspect every
  private loan. CSRF and service-level permissions protect every modifying action.
- PostgreSQL holds state/history, serializes inventory mutations per faculty and
  excludes overlapping asset reservations. C++ owns matching via a separate version-1
  operation. Existing allocation and appointment JSON operations stay compatible.

See [architecture](../architecture/equipment-borrowing-design.md),
[user walkthrough](../equipment-borrowing-guide.md), and [protocol](../engine-protocol.md).
