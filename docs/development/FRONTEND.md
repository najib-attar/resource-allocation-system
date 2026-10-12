# Frontend and UX Guidelines

## Current position
The project already has Flask + Jinja templates, HTML/CSS and JavaScript. **Do not migrate to React by default.** First inspect existing templates, scripts and routes, and identify an actual problem the change would solve.

## User experience
- Make each user's tasks obvious: request resources, schedule appointments, track status, manage availability, approve/decline, etc.
- Use consistent navigation, components, terminology, empty states and error messages.
- Validate fields both in the browser for convenience and on the server for correctness/security.
- Make calendars and time slots explicit about day/date, timezone, duration, tentative vs confirmed state.
- Ensure keyboard access, readable labels, responsive layouts and status feedback; never rely on color alone.
- Show students only permitted availability information, not private details of professor schedules.

## Existing stack: recommended default
- Keep Flask/Jinja server-rendered pages for forms, request lists, dashboards and administration.
- Use focused vanilla JavaScript where interactivity truly improves the experience (slot selection, calendar filtering, progressive updates).
- Refactor templates into reusable partials/macros when duplication appears; avoid a large UI rewrite in the same PR as critical domain changes.

## When to propose React
- Repeated complex client-side state and interactive multi-view workflows are demonstrably cumbersome in Jinja/vanilla JS.
- A cohesive front-end app is warranted and the team can own a build pipeline, client routing/state, API contract, error handling, auth and test strategy.
- Compare React migration effort, risks, benefits, and the current server-rendered alternative **in a separate architecture decision** before coding. React does not itself improve allocation correctness or maintainability.
- If approved, design a clean backend application/API layer first, migrate incrementally with tests; don't replace everything at once.
