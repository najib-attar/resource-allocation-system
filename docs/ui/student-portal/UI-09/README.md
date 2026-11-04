# UI-09 Integration and acceptance evidence

All existing student service rules are accounted for. `routes.md` / `routes.csv`
inventory all 68 Flask rules, including 47 service rules and their role boundaries.
`contracts.json` verifies original named form controls and unchanged protected
business services, security, persistence, migrations, C++ and CDMCS sources.

The shared service base and scoped stylesheet keep student pages coherent without
applying the student redesign to other roles. Input and secondary-button borders
were strengthened after the contrast review; sampled text/status pairs, control
boundaries and focus indicators are recorded in `contrast.json`.

`web/app.py` adds presentation-only handling of existing failures for ordinary
students. It preserves status codes, method headers, CSRF rejection and busy retry
headers, safely escapes validation descriptions, hides internal service details
and makes personalized errors private/noncacheable. Other roles retain existing
error responses. No routes, permissions, scheduling rules or authentication logic
changed. Four explicit presentation/error-contract tests accompany the change.

## Executed verification

- Full Python/PostgreSQL discovery: **614 run, 613 passed, 1 expected platform skip,
  0 failures, 0 errors**, across 47 modules. Discovery and executed counts match.
  No database tests skipped. Real dump/restore, concurrency, private preferences
  and policy foundations, all student lifecycles and existing role flows ran.
  Elapsed: 1,551.08 seconds. `tests.json` has per-module counts; `tests.txt` has every
  result; `modules/` retains each subprocess's exact evidence.
- Only skip: `test_linux_execute_permission_is_checked` — "POSIX permission check
  runs on Linux." This execution used Windows.
- C++: **192 passed, 0 failed**. Both existing runtime smoke cases passed, using
  unchanged C++ sources. See `cpp-tests.txt`.
- Final real-browser audit: **182 page views, 1,611 keyboard steps, 0 JavaScript
  errors**. Student pages were checked at 1440/768/390/320px, with complete main
  keyboard traversal, visible/unobscured focus, labels, one main heading, primary
  navigation, privacy, HTTP status, CSRF and no horizontal page overflow.
- Professor: 9 existing views; staff: 11; administrator: 7, each at desktop/mobile.
  Original shells, absence of student CSS, drawer/Escape/focus and overflow passed.
- Actual missing-CSRF browser submission retained 400. A separate isolated review
  server with a tiny existing engine timeout produced actual 503 pages at four
  widths; no API responses or browser screenshots were mocked.
- Final live loading observation confirmed busy state, disabled submission and
  cleared selection at the native fetch boundary, followed by 31 real appointment
  choices and 3 real room candidates. Notification loading was also observed.
  Requests and responses were not delayed or replaced; see `loading-results.json`.

The phase screenshots include current Login, Home, My Schedule, role views and
CSRF/service-failure states. Earlier phase directories retain each group's empty,
populated, invalid, private and workflow captures. The acceptance report links the
complete feature matrix, commit and file inventories and screenshot index.

Review servers were stopped and all eight uniquely identified synthetic review
schemas created during this task were removed. Unrelated schemas and operational
databases were preserved; see `cleanup.json`.

Student Services v1 is ready for final user acceptance review. This is not a merge
or deployment. Target-device and assistive-technology user testing remain part of
acceptance; the executed checks are not an accessibility certification.
