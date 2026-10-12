# Testing and Continuous Integration Guide

## Before proposing a test plan
Read the current tests and `.github/workflows/` first. The repository already has a Linux GitHub Actions job; improve it instead of replacing it automatically. Establish the commands that actually work in the target environment.

## Current repository commands (from README/workflow; verify locally)
Build C++ backend:
```bash
python scripts/build_backend.py
```
Run Python tests:
```bash
python -m unittest discover -s tests -p 'test_*.py' -v
```
On Windows, run existing C++ test driver (PowerShell):
```powershell
powershell -ExecutionPolicy Bypass -File tests/run_tests.ps1
```
On Linux, the existing workflow compiles C++17 tests from `src/` and `tests/` using `g++`, then runs the binary. Inspect `.github/workflows/shared-file-regression.yml` for its exact command rather than inventing a second canonical runner.

## For every meaningful feature
- Write acceptance tests for the actor flow and negative/edge cases.
- Put pure domain logic under C++ unit tests; cover Flask route/persistence/gateway behavior with Python tests.
- Protect allocation invariants: mandatory rules, room conflicts, capacity, participant conflicts, approval transitions, and rejection non-allocation.
- For appointment/booking logic, test **simultaneous confirmation**, stale availability, cancelled/blocked hours, timezone/date rules, and permission denial.
- For JSON contract changes, test schema/compatibility/errors across both C++ and Flask.
- Verify in browser for UI changes; don't claim visual checks were performed unless they were.

## CI/CD principles
- PR checks should run build and relevant tests; a red CI blocks merging.
- Add static checks, dependency scanning, Windows coverage, browser E2E, and deployment steps **when needed and maintainable**; don't add unconfigured/always-failing checks.
- Keep CI fast and deterministic; use isolated fixture data and never mutate committed user data in tests.
- Distinguish CI (build/test on PR) from CD (deployment). Deployment needs a stable target, secrets/configuration, health and rollback strategy.

## Report results accurately
Summarize command, environment, pass/fail/skip counts and limitations. If a toolchain/service is unavailable, say `NOT RUN` with reason. Never invent successful results.
