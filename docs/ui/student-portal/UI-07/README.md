# UI-07 Feedback and Issues

> Historical phase record. UI-01–UI-10 are complete and merged; see the
> [current Student Portal guide](../README.md). Scope statements, test counts
> and follow-up plans below describe this phase at its recorded revision.
> Later shared-component and authentication changes are documented in the current guides.

Private report list, server filters, eligible report form, detail, staff response,
clarification and history use the shared student service layout. The list explains
how to open an eligible booking/loan instead of adding an unrestricted creation
route. All status/category/service/resource filters remain server-scoped.

The form uses the service's actual per-resource completed-use flag. Active use
offers problem reports; completed use permits all existing categories. Safety
flags apply to problems. These are presentation hints: service eligibility,
privacy, CSRF, idempotency and revision validation remain authoritative. No report
management permission is added. Staff review and reporter clarification keep their
original role and lifecycle guards.

Keyboard verification found a clarification field beneath the fixed tablet
navigation. Scoped root scroll padding now accounts for the navigation; all four
widths pass unobscured focus checks. Evidence includes empty, eligible, ineligible,
private and invalid-filter pages, real submission and escaped content, forbidden
student review, reporter clarification, authorized staff response/resolution,
privacy from another student and a real status filter. Exact executed suites and
browser results are recorded alongside the real Flask captures.
