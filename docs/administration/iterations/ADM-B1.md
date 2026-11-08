# ADM-B1 — Academic administration verification

Base: ADM-B0 `e6e6909f6e8909efd8e76afdf370afbff97ddf81`.
Commit: introducing commit `test(admin): verify academic administration boundaries`;
exact SHA is recorded in the final acceptance commit inventory.

Reused EligibilityService, Repository guarded snapshots, EngineGateway,
execute_allocation, ProfessorService and explicit calendar publication/bindings.
No academic behavior, database migration, scheduling algorithm or permission changed.

Command: existing `tests/professor/run_tests.py --child administration/ADM-B1`
with modules `test_academic_eligibility test_eligibility_migration
test_professor_intake test_postgres_workflow test_university_calendar
test_identity_sessions test_logout_sessions test_logout_migration`.

Fresh result: **77 executed, 77 passed, 0 failed, 0 errors, 0 skipped**;
500.218 seconds. PostgreSQL 17, uniquely owned schemas in the new administration
test database; real rebuilt C++17 engine. Raw output remains ignored in
`build/professor-tests/administration/ADM-B1/`.

Verified persisted owner submissions, reasoned decisions, approval invalidation,
stale/tampered snapshot refusal, five strategies, atomic publication, concurrent
review/revision, legacy review barrier and unchanged active reservations. Tested
administrator separation, foreign ownership, all roles, CSRF and durable logout.
Migration upgrade/downgrade protections for 0051a/0051b were exercised by existing
regressions. Only disposable schemas changed; demonstrations were not accessed.

Files changed: this report. No screenshots for this backend-only stage.
Limitations: academic notifications, cancellation and published replacements remain
deferred; explicit calendar bindings still require verified applicability dates.
Conclusion: **verified**, continue to operational administration.
