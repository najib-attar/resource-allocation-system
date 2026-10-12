# Engineering and Architecture Standards

## Quality goal
Build correct, readable, testable, secure, and maintainable software; not the most abstract or most pattern-heavy software. Explain trade-offs when choosing designs. Follow repository conventions unless a specific deficiency warrants a proposed change.

## Design principles
- Single responsibility and clear boundaries: **domain rules in C++**, web request/response handling in Flask, I/O behind persistence/gateway interfaces where practical.
- Favor composition over inheritance for new behavior unless polymorphism clearly helps existing architecture.
- Apply SOLID pragmatically. Don't create factories/interfaces/services simply to satisfy a pattern checklist.
- Reuse existing rule/strategy/factory abstractions when appropriate; identify new abstraction only if it reduces duplication or couples fewer things.
- Validate at both UI/application boundaries and the domain engine; do not trust client input.
- Errors must be actionable and handled safely; don't silently drop requests or pretend a failed operation succeeded.
- Keep request lifecycle states explicit and test legal transitions. Confirm bookings atomically; do not rely only on a free/busy display to prevent double-booking.
- Do not leak private schedules to other users: present free/busy or permitted details, not raw personal event metadata.

## Safe change checklist
- Determine the source of truth for the data and who is allowed to mutate it.
- Evaluate schema/data migration needs, rollback, idempotency, and concurrent requests.
- Check compatibility of existing CSV import/export, JSON snapshot/result and UI adapter behavior.
- Check adjacent request types, allocation strategies, status handling, and schedule views.
- Review dependency, deployment, configuration and security impact; avoid premature rewrites.
- Keep changes small and cohesive; add typed interfaces where they help understanding.

## Design patterns
State **which pattern is already used**, **what problem needs solving**, and **why a new pattern is or is not justified**. Current repository uses strategies, factories, rules, and a gateway/adapter boundary. Document only meaningful patterns introduced or materially changed; no mandatory pattern per iteration.

## Learning-oriented output
After each meaningful design proposal or implementation, include a short explanation: *What changed? Why this design? What alternatives were rejected? What trade-off remains?*
