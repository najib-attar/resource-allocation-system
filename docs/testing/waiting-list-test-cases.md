# Resource waiting-list acceptance cases

The executable cases are in [test_waiting_lists.py](../../tests/test_waiting_lists.py).
They use real PostgreSQL, the compiled C++ engine, isolated schemas and explicit
fictional dates. Browser checks exercise the real authenticated forms separately.
This is risk-based coverage, not a claim to exhaust every possible execution.

Verification on 21 October 2026: **48 waiting-list tests passed, zero failures**
on Windows with PostgreSQL 17.11 and the real engine. A fresh C++ build passed
**172 tests**, plus the two isolated standalone CLI runtime smokes.
The complete Python/PostgreSQL suite ran **370 tests: 369 passed, zero failed,
one skipped** (the Linux-only executable-permission test on Windows). The 48
waiting-list tests are a subset, not an additional 48 application tests. Room and
equipment maintenance CLI smokes also passed two repeated runs each without
duplicate notifications or premature reservations. See the
[iteration report](../iteration-reports/Iteration_47.pdf).

Playwright with installed Chrome also verified real login/logout, policy reading
and consent enforcement, cancellation, faculty pre-approval/rejection, top-three
and position-one notifications, room reopening to automatic confirmation,
equipment release to full-quantity reservation, and unrelated-student/wrong-faculty
privacy denial. Desktop 1440px and mobile 390px views were inspected; the mobile
page had no body-level horizontal overflow. All browser data was isolated.

Cancellation removes **active eligibility and position**, not the audit record.
Pre-approval does not mean a room or equipment is already reserved.

| Case | Scenario | Expected result | Coverage |
|---|---|---|---|
| W01 | Join without consent, with an old policy or an invalid identity | Reject; create no waiting entry or reservation | Shared |
| W02 | Join an unavailable but eligible request | Pending Review; estimated contextual position; zero reservations | Both |
| W03 | Resource is already available, or mandatory eligibility fails | Use normal submission or reject; do not misuse a waiting queue | Both |
| W04 | Cancel a pending or pre-approved entry | Cancelled; no active position; history retained; never assigned later | Both |
| W05 | Cancel through the existing parent-request workflow | Same withdrawal semantics; no parallel active queue remains | Both |
| W06 | Another student or another faculty tries to inspect, cancel or review | Permission denied; no private details or state changes | Both |
| W07 | Responsible staff pre-approve while unavailable | Preapproved; eligible contextual position; still unreserved | Both |
| W08 | Responsible staff reject | Rejected; no active position; decision/history/notification retained | Both |
| W09 | Availability returns before review | Stay Pending Review; availability alone cannot authorize assignment | Both |
| W10 | Availability returns after pre-approval | Assign complete original requirements automatically; no second acceptance | Both |
| W11 | Two compatible eligible requests compete | Process join sequence deterministically; no duplicate reservation | Both |
| W12 | Request first enters the eligible top three | One durable student notification; no repeated movement spam | Shared |
| W13 | Request reaches eligible position one | One durable student notification, including after earlier cancellation | Shared |
| W14 | Different intervals or mandatory requirements | Contextual positions, not a misleading single global position | Shared |
| W15 | Double-click/retry, including concurrent submissions | Same immutable submission key returns the same entry; changed payload fails | Both |
| W16 | Two worker processes promote the same last resource | Exactly one valid winner; no double-booking or excess quantity | Both |
| W17 | Normal approval competes with waiting-list promotion | Existing reservation locks/constraints allow only one winner | Both |
| W18 | Cancellation races with final assignment | Serialized outcome; an already assigned request requires normal cancellation | Room/shared locking |
| W19 | Engine fails during promotion | Roll back all new reservations/results; request remains retryable | Both |
| W20 | Engine fails after another request is cancelled or rejected | Withdrawal/decision stays committed; positions update; failed refresh is logged | Both/shared rejection |
| W21 | Notification persistence fails during assignment | Roll back reservation and assignment together; retry sends one assignment | Both |
| W22 | Minimum notice has never been configured | No automatic assignment; explicit paused explanation | Shared |
| W23 | Exactly enough notice, then one second too late | Exact boundary allowed; insufficient notice blocked | Shared |
| W24 | Current notice is reduced after a larger minimum was recorded | Do not reduce the entry's recorded protection | Shared |
| W25 | Requested start passes without assignment | Expired; no reservation or penalty; one expiry notification | Both |
| W26 | Policy version changes or student identity is disabled | Ineligible; no automatic assignment under obsolete authority | Shared |
| W27 | Faculty reviewer/custodian is replaced or disabled | Fresh Pending Review required; old staff cannot authorize assignment | Both |
| W28 | Room policy or equipment specifications become incompatible | Ineligible; never silently relax mandatory requirements | Both |
| W29 | Only one of two required devices becomes usable | Keep waiting until the complete quantity is available | Equipment |
| W30 | Equipment becomes due, overdue, or has return intent only | Remains held; only verified physical return releases it | Equipment |
| W31 | Returned equipment is damaged | Do not allocate until an explicit usable-condition repair/update | Equipment |
| W32 | Equipment is assigned automatically | Approved/reserved physical units; handover remains a separate action | Equipment |
| W33 | Adjacent intervals and equivalent UTC/Istanbul timestamps | Half-open intervals do not conflict; equivalent times share queue context | Room/shared dates |
| W34 | Academic allocation publication releases a compatible room | Re-evaluate waiting requests using authoritative current commitments | Room |
| W35 | Optional professor invitation | No private queue-position/consent access; normal assignment notification | Room |
| W36 | Browser form, login/logout, CSRF, status details and notification menu | Authorized working flow; accurate current status; no CSV runtime fallback | Both |
| W37 | Migration, downgrade/re-upgrade and invalid parent relationships | Schema matches models; original data preserved; invalid queue shapes rejected | PostgreSQL |

## Running the regression suite

With the normal pinned dependencies, built backend and an isolated
`TEST_DATABASE_URL`, run:

```text
python -m unittest discover -s tests -p test_waiting_lists.py -v
python -m unittest discover -s tests -p test_*.py -v
```

Each test creates and removes its own schema. Do not point test setup at an
operational database. See [database operations](../database-operations.md).

The broader suite additionally covers existing appointments, calendar privacy,
room/equipment lifecycle transitions, all five academic allocation strategies,
backup/restore, concurrent database writes and JSON compatibility.
