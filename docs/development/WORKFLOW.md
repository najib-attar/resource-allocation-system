# Feature Analysis and Delivery Workflow

Use this for any new feature, enhancement, bug fix, or refactor. Task-specific requirements belong in the user's prompt or approved requirements; don't create a new Markdown specification for every feature.

## Phase A - Explore (read-only by default)
1. Restate the goal, actor, observable behavior, and acceptance criteria. Distinguish **agreed requirements** from assumptions.
2. Inspect relevant routes/templates, persistence, gateway/JSON schema, C++ models/rules/strategies, existing tests and reports. Use actual file/line references where practical.
3. Trace the full flow: browser -> Flask route/service -> persistence/snapshot -> JSON gateway -> C++ -> result adapter -> UI.
4. Note what can be reused; identify design smells, hidden coupling, compatibility assumptions, and failure/concurrency cases.
5. Compare 2-3 viable options **only when trade-offs are meaningful**. Recommend the simplest robust approach and explain why.
6. Return: **Current behavior | Gaps | Proposed design | Files affected | Test plan | Risks/questions**.
7. Stop before writing code until the user approves the proposal, unless implementation was expressly requested.

## Phase B - Implement (after authorization)
1. Confirm scope and acceptance criteria. Split large work into reviewable, reversible changes.
2. Protect current behavior with tests where necessary; add tests for the change.
3. Implement the smallest coherent vertical slice; prefer stable interfaces to large rewrites.
4. Validate input, access and race conditions; preserve invariants and old behavior unless changes are approved.
5. Run targeted and relevant regression tests; fix failures; explicitly note tests that couldn't run.
6. Review `git diff`, update documentation proportionately, and summarize results and remaining risk.

## Definition of done
- Agreed scenarios and edge cases behave correctly; no known regression.
- Relevant automated tests added/updated and executed (or limitation disclosed).
- Changes follow existing architecture and avoid avoidable duplication/complexity.
- API/JSON changes are documented, versioned/compatibility-reviewed when necessary.
- Important design decisions and repo docs are updated when affected.
- No commit/push/merge unless the user requested it.

## Example analysis-only prompt
> Analyze the attached/approved UC-STU-01 PDF. Do not edit code. Trace existing scheduling, availability, request lifecycle, and JSON interfaces. Tell me what we can reuse, what is missing, 2-3 implementation choices, risks, affected files, and exact tests. Recommend the most maintainable approach; wait for my approval.
