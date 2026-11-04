# UI-04 Rooms

> Historical phase record. UI-01–UI-10 are complete and merged; see the
> [current Student Portal guide](../README.md). Scope statements, test counts
> and follow-up plans below describe this phase at its recorded revision.
> Later shared-component and authentication changes are documented in the current guides.

Room request list, new/revision forms, details, recurring series and busy/free
availability use the shared student service components. Activity, time/requirements
and ranked-room selection are separate panels. Required facilities, faculty and
building preferences, declared club affiliation, registered students, optional
professors, semester and approval consent are retained with their original fields.

Ranked candidates link to the existing date-specific busy/free route. The link
opens a labeled new tab and exposes no event details. Input changes or a failed
availability check clear the candidate and disable ordinary submission. Live
status and busy state reflect actual requests; no loading or success is simulated.

The detail preserves faculty decisions, revision, recurring occurrence controls,
participant registration, optional invitations, feedback eligibility, waiting
status, history and allowed cancellation/revision actions. Shared error recovery
now returns users to the service they were using. No route, service, business
rule, staff privilege or calendar semantics changed.

`tests.json` / `tests.txt` record room, recurrence, real concurrency, views and
partial-approval policy regression results. `browser-results.json` records all
screen captures at 1440/768/390/320px, plus empty/error/forbidden states and CSRF,
keyboard, focus and overflow checks. `workflow-results.json` records actual
ranked-room selection, registered participant and invitation, busy/free link,
offline failure, revision, cancellation, unavailable capacity and occurrence
cancellation using the running Flask application and synthetic PostgreSQL records.
