# Git, Iterations, and Pull Requests

## Before starting
1. Check clean working tree: `git status --short`.
2. Fetch latest remote refs: `git fetch origin` and inspect main branch state.
3. Determine the **latest documented iteration** from `docs/iteration-reports/`, relevant design/report files, recent merged PRs and README. Do not assume README is current.
4. Choose the next unused iteration number **only if this change is an iteration-worthy feature**. Current README reports Iteration 40 as a historical checkpoint, not a guaranteed next number.
5. Create a branch from up-to-date `main`, e.g. `iteration/41-professor-appointments` **only after confirming 41 is unused**. For minor maintenance, use `fix/…` or `docs/…` without manufacturing an iteration.

## Example commands (after checking remote/working tree)
```bash
git switch main
git pull --ff-only origin main
git switch -c iteration/41-example-feature  # replace 41 after checking
```

## While implementing
- Make focused commits with meaningful messages, e.g. `feat(appointments): add availability rules`.
- Avoid unrelated generated files, private data, credentials, cached artifacts and compiled executables.
- Reconcile updated docs/SRS and tests with the actual code change.
- Never force-push shared branches or edit `main` directly unless requested.

## Iteration review and PR
1. Run tests listed in `TESTING_CI.md`; review results.
2. Review `git diff --check`, `git diff`, changed files, and any generated artifacts.
3. Update a short iteration report **for significant iterations** (see `DOCUMENTATION.md`); add/refresh diagrams only if architecture changed.
4. If user explicitly requested publishing: commit, push branch and open PR. Record summary, test results, design changes and screenshots if UI changed.
5. Wait for CI and code review; fix failures. Merge into `main` **only when explicitly authorized** and checks pass.
6. After merge, bring local `main` up to date; clean up branch only if appropriate and approved.

## Avoid documentation overhead
One coherent feature can span multiple commits and sometimes multiple PRs. A small bug fix need not be assigned a new numbered iteration. Numbering is for meaningful academic milestones, not every code change.
