# Autonomous Development Execution

This guide applies only when the user explicitly authorizes autonomous implementation and local milestone commits. It does not independently authorize pushing, merging, deployment, or destructive operations; AGENTS.md and the current task's scope still apply.

## Before Implementation

- Read AGENTS.md and relevant development guidelines.
- Inspect the existing implementation.
- Confirm the approved architecture.
- Create an ordered implementation plan.
- Identify dependencies and risks.

## During Implementation

For each milestone:

1. Implement the approved changes.
2. Add or update relevant tests.
3. Run the tests.
4. Investigate failures.
5. Fix regressions.
6. Review the implementation.
7. Update progress documentation.
8. Commit the verified changes.
9. Continue to the next milestone.

## Stop Conditions

Stop and request user approval when:

- An architectural decision conflicts with the approved plan.
- A destructive data migration is required.
- Existing behavior would need to change unexpectedly.
- Requirements are ambiguous.
- Tests repeatedly fail without a clear solution.
- A significant security or data-integrity issue is found.
- A major dependency or technology change is necessary.

## Git Rules

- Work on the approved development branch.
- Keep commits focused.
- Do not include generated files or secrets.
- Do not merge into main automatically.
- Do not force-push without explicit approval.

## Completion

Provide:
- Implemented milestones.
- Modified components.
- Architecture decisions.
- Test results.
- Known limitations.
- Documentation updates.
- Commit history.
- Remaining work.
