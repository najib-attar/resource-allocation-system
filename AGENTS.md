# Resource Allocation System - Codex Instructions

This file is the short, always-on entry point for AI coding assistance. Read the task-specific guidance below; do not load every document unnecessarily.

## Project
- University resource allocation/scheduling application; current repository is a prototype.
- `src/`: C++17 models, rules, strategies, and allocation engine.
- `web/`: Flask/Jinja web application and browser UI.
- PostgreSQL is the operational source of truth; `web/persistence/` owns database records and transactions.
- `data/`: offline CSV import/standalone C++ CLI fixtures and exports; never a normal web fallback.
- Engine execution from Flask uses the **versioned JSON stdin/stdout contract** documented in `docs/engine-protocol.md` via `EngineGateway` and `BackendResultAdapter`.
- Read `docs/architecture/database-design.md` and `docs/database-operations.md` for persistence boundaries, migrations and safe test isolation. `DatabaseResultAdapter` reuses backend-result presentation logic without file reads.
- Read `README.md` and the relevant implementation and tests to confirm actual behavior. Documentation can lag behind code.

## Default mode: analyze before changing code
1. Read the user's task and inspect relevant code, tests, protocol, and documentation.
2. State what exists, what is missing, impacted files, risks, alternative designs, and recommended approach with reasons.
3. For meaningful changes, propose an incremental plan and **wait for explicit approval before implementing**. If the prompt explicitly authorizes implementation, proceed according to its scope.
4. Never claim tests passed without running them. Never silently change unrelated functionality.
5. Be concise, trace claims to concrete repository files, and highlight unresolved product decisions.

## Task-specific guidance (read only what is relevant)
- Analysis and task flow: `docs/development/WORKFLOW.md`
- Code quality and architecture: `docs/development/IMPLEMENTATION.md`
- Tests and CI: `docs/development/TESTING_CI.md`
- Branches, commits, iteration numbering and merge: `docs/development/GIT_ITERATIONS.md`
- Explicitly authorized autonomous implementation and local milestone commits: `docs/development/AUTONOMOUS_EXECUTION.md`
- Flask/Jinja/frontend decisions: `docs/development/FRONTEND.md`
- Iteration reports, design patterns and diagrams: `docs/development/DOCUMENTATION.md`

## Non-negotiable guardrails
- Keep authoritative allocation rules/strategies in C++ unless an explicitly approved redesign changes ownership. Flask must not duplicate allocation decisions.
- Treat `docs/engine-protocol.md` as a compatibility contract; review all callers/tests before changing payloads.
- Check impact across domain models, request persistence, backend JSON, adapters, routes/templates, and tests before editing any cross-cutting feature.
- Preserve conflict, capacity, availability, permission, and data-integrity invariants; consider concurrency and rollback.
- Prefer small coherent changes, regression tests, existing conventions, and straightforward code. Add a design pattern only if it solves a concrete problem.
- Do **not** push, merge, rewrite history, delete data, or alter external services without an explicit user request. Ask before dependency/framework migrations.

## How we work with the user
Explain briefly **why** a design was chosen and its trade-offs; the user is learning architecture, frontend, backend, testing, and delivery. Product requirements specific to a use case come from the current prompt and approved SRS/use-case PDFs, not from inventing requirements here.
