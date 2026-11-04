# Campus Space — UI-02 Login handoff (design approved only after review)

## Existing backend contract (verified against main, 2026-11-03)

`web/templates/login.html`: existing POST login form with `name="username"`, `name="password"`, hidden `csrf_token` from `csrf_token()`, a server-provided `error` displayed as `role="alert"`, and native required fields. Username maxlength=100; password maxlength=256; autocomplete username/current-password.

## Requirements for production implementation

- Keep actual server form method/action, field names, CSRF token, and error reporting unchanged.
- Preserve role-sensitive post-login destinations and existing session/authentication logic without rewriting it.
- Accessible input labels, visible focus, keyboard submit, password field masking, no exposed credentials.
- `Show` password is optional client-side only; it must not change the backend contract.
- Do **not** add registration, forgotten-password, email/SMS login, SSO, or password reset links unless those routes are actually implemented.
- Avoid styling other users' pages unintentionally; use login-scoped CSS and only minimal shared shell changes if necessary.
- Test invalid credentials, missing inputs, CSRF failure, authenticated redirect, existing role landing pages, mobile 390/320px and desktop 1440px.
- This HTML file is a standalone design preview, not a real login form. Its submit handler intentionally displays an explanatory preview message rather than sending credentials.

## Page-by-page coverage process for later UI PRs

1. Inventory *every* existing authorized route/action for the selected service by reading templates, route handlers, service layer, use cases and tests.
2. Build a signed-off feature matrix: implemented, partially implemented, deferred, authorization-specific.
3. Design all relevant list, new/edit, detail, approval, cancellation, recurrence, notification, feedback, empty/error/pending states.
4. Implement against the existing service; do not invent or delete business rules.
5. Run tests for each backend action, authorization/privacy, CSRF, accessibility, mobile and regression before next page.

Suggested sequence: UI-01 Home → UI-02 Login → UI-03 Appointments (list/new/details/invitations/approval/reschedule/cancel) → UI-04 Rooms (new/list/details/availability/recurrence/cancel) → UI-05 Equipment (catalog/borrow/loan/returns/extensions) → UI-06 Waiting Lists (policy, joining from eligible requests, positions, withdraw) → UI-07 Feedback & Issues (eligible reports, history) → UI-08 Calendar, personal schedule and notifications. Avoid duplicate service menu in global navigation.
