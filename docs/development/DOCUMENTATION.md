# Documentation, Design Patterns, and Iteration Reporting

## Maintain a useful record, not documentation for its own sake
The goal is for the user and supervisor to understand *what changed, why, how it was tested, and what remains*. Preserve existing reports and diagrams; update only what a change affects.

## When to write what
- **User-facing feature**: concise one-page PDF use case when preparing a professor-facing presentation; detailed task requirements may live in the approved prompt, issue or SRS. No mandatory Markdown file per use case.
- **Meaningful numbered iteration**: short report (typically half to one page, unless a larger design warrants more).
- **New or materially changed architecture**: update relevant class/sequence/component diagram. Diagrams should match the code, not be drawn merely to meet a quota.
- **New architectural trade-off**: add a brief ADR (Architecture Decision Record) or section to the iteration report when genuinely useful.
- **Changed user requirement**: update the central SRS/backlog once agreed; do not leave contradicting sources of truth.
- **Bug fix/cleanup**: concise commit/PR description plus tests may suffice; no mandatory design-pattern report.

## Minimal iteration report template
```markdown
# Iteration NN - Descriptive title
**Goal:** ...
**Behavior delivered:** ...
**Important code locations:** ...
**Architecture/design decision and rationale:** ... (or "No architectural change")
**Tests:** commands/results; limitations
**Known trade-offs / follow-up:** ...
```

## Design patterns
Record a pattern **only if added, removed or materially changed**:
- Name and intent (e.g. Strategy selects allocation policy).
- Which real problem it solves and where implemented.
- Trade-offs vs a simpler alternative.
- Small diagram **only when it clarifies an architectural change**.
Do not introduce a pattern solely to provide something to document. High quality comes from correct boundaries, test coverage, small changes and explainable decisions.

## Review before publication
Confirm report and diagrams reflect merged code and tested behavior; name incomplete work honestly. Prefer one maintained diagram over a new nearly identical diagram every iteration.
