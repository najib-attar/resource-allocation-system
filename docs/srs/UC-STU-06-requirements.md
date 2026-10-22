# UC-STU-06 - Resource feedback and issue reporting

Complements the [approved use case](../use-cases/UC-STU-06-resource-feedback-issue-reporting.pdf).

- One shared capability serves rooms and physical equipment. Feedback is optional;
  skipping never affects a reservation, physical return or future legitimate access.
- Categories: problem, improvement and general feedback. All require bounded text
  and an actual server-verified usage association.
- Active room reservations and handed-over loans permit problems. Completed room
  periods and verified per-unit returns permit all categories. Future/pending/
  cancelled rooms and uncollected equipment do not establish actual resource use.
- Organizers and explicitly registered room participants submit independently.
  Counts and unanswered/declined invitations never infer membership. Student group
  registration reuses existing room participation; professor invitations stay optional.
- Equipment uses recorded borrowers and actual unit reservations; no unsupported
  participant model is fabricated. Partial returns are evaluated per unit.
- Only reporter and currently responsible room-faculty manager/equipment custodian
  may read private reports. Other group members cannot read one another's content.
- Staff prioritize, respond, resolve/close and reopen with an explanation:
  Submitted -> Under Review -> Resolved/Closed; reopening returns to Under Review.
  Reporters may clarify open reports, not perform staff decisions.
- Preserve original usage/content, status revisions, responses, actors, recipients
  and timestamps. Unchanged retries are idempotent; stale/conflicting actions fail.
- Reuse the notification inbox: staff receive new reports, reporters receive staff
  updates and resolution. Generic previews do not disclose confidential descriptions.
- Urgent safety flags advise immediate staff contact. Submission never blocks a
  resource. Existing authorized closures/condition changes remain separate, audited
  and transactional; no reservation is silently cancelled.
- Use shared responsive components, authenticated server-side identity, CSRF,
  safe text rendering, private caching and own/managed resource filters.
- Preserve C++/JSON behavior, booking approvals, verified physical returns,
  appointments, calendar projections and shared waiting-list semantics.

See [architecture](../architecture/resource-feedback-design.md).
