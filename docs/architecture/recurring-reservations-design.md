# Recurring student room and equipment reservations

## Existing behavior and reuse audit

- C++ `RecurringRequest` stores a vector of weekly `TimeSlot` values. Greedy and
  priority strategies reject self-conflicts and evaluate all slots before writing
  allocations; exam strategies delegate ordinary recurring requests. This is not
  an academic calendar and must not be populated with repeated dates collapsed
  onto the same weekday. Existing five strategies and weekly protocol stay intact.
- `calendar_service.expand_weekly`, `local_instant`, `aware` and `epoch` already
  implement bounded dates, explicit timezones and half-open intervals. Legacy
  schedules still need academic-period bindings; missing dates are not guessed.
- `RoomSelectionService`, `room_snapshot` and `RoomRequestService` already own room
  ranking, academic/appointment projections, current faculty approval and calendar
  revision checks. Their current request/reservation aggregate represents one dated
  interval, not multiple calendar weeks.
- `EquipmentMatchingService` and `EquipmentService` already own exact quantities,
  faculty eligibility, conditions, reservations, active possession, handover,
  partial verified returns and extensions. A multi-day continuous loan is already
  supported and must remain one loan, not become a recurring series.
- Existing room/equipment events and notification receipts provide private history
  and recipient deduplication. Personal/unified calendars currently project the
  single request interval; recurrence requires occurrence-aware projections.
- Waiting lists coordinate single-interval requests. Their transaction locks,
  eligibility/matching helpers and promotion implementation are reusable; splitting
  one series into independent queue entries would invent a new approval policy.

## Design and implementation sequence

1. One shared bounded weekly expansion helper produces sorted, non-overlapping
   actual intervals in the configured university timezone. Date bounds refer to
   occurrence start dates, inclusively. Preview includes every pickup/end instant.
   Durations are elapsed minutes, matching existing dated workflows. Technical
   execution bounds are 366 occurrences and a two-year start-date range, not an
   invented university lending entitlement; per-type borrowing limits still apply.
2. A shared series record stores its rule and links exactly one existing room or
   borrowing request. Dated occurrence records retain stable identities, ordering
   and cancellation/completion state; request details, members and requested items
   are not copied for each date. Existing reservations gain optional occurrence
   links and preserve their exclusion constraints.
3. Compatible, separately identified engine operations compose existing C++ room
   ranking and equipment matching over dated intervals. A room must work for the
   entire series before candidate truncation. Equipment units may differ between
   non-overlapping occurrences; an unreturned unit is never assumed available.
4. Extend current services and transactions for complete-series approval and scoped
   future cancellation. Keep actor permissions and events in those services. Process
   eligible existing queues using the same coordinator/locks before consuming stock
   or room availability. A series cannot join a single-interval waiting list; a
   future series queue requires an explicit university policy.
5. Handover and physical return remain occurrence-specific inventory operations.
   Cancelling future occurrences never releases an active physical loan. Changes
   to approved requirements use cancellation of the affected future proposal and
   fresh submission/approval; completed uses remain historical records.
6. Extend existing forms, detail screens, calendar projections and notifications.
   Test expansion, current workflows, all-or-nothing conflicts, permissions,
   idempotency, queue fairness, concurrent writers, physical possession and history.
   Finish with full regression, migration/drift and browser checks, then the
   academic iteration report. No new numbered student use case is introduced.

## Implemented boundaries

```text
Existing room / equipment forms + shared weekly selector
    -> recurrence.expand_recurrence (explicit dates and timezone)
    -> existing RoomRequestService / EquipmentService
        -> PostgreSQL input snapshot -> EngineGateway
        -> C++ rankSeries / repeated existing equipment match
        -> one complete approval transaction + existing reservations/events
    -> read-only personal / unified calendar occurrence projections
```

| Component | Responsibility |
|---|---|
| `web/recurrence.py` | Bounded weekly expansion, explicit DST rejection, half-open dated periods; no resource matching. |
| `web/recurring_records.py` | Shared identity/retry, rule/occurrence persistence and batched display projection; not a booking service. |
| Existing room service | Whole-series same-room validation, faculty approval, organizer commitments and future cancellation. |
| Existing equipment service | Whole-series quantity reservation, occurrence-specific collection/extensions, partial verified returns and aggregate loan state. |
| Existing C++ services | Room eligibility/ranking intersection and per-period equipment matching, without database access or changed legacy strategies. |
| Existing events/inbox | Actor/time history, current authorized audiences and deduplicated receipts. |

`0049a` adds only two application tables. The parent request retains its original
first interval for one-time compatibility; series-aware views use occurrences,
not that interval as a shortcut for future dates. Optional occurrence FKs reuse
existing physical reservations. Database aggregate checks reject incomplete
expansion/confirmation and mismatched reservations, while immutable dates preserve
history. A unit may have only one outstanding physical handover. An extension must
reference its own borrowing series, never another parent's occurrence.

Room confirmation preserves the existing calendar revision/serialization boundary.
Equipment uses the existing policy-share/faculty lock order. Both call the current
waiting-list coordinator before approval so existing eligible queues are processed
without duplicating their allocation rules. Bounded database contention is a clear
busy/retry outcome, not permission to confirm a partial proposal. Rollback preserves
the preceding state. No series-specific queue policy or scheduling worker is added.

The equipment form signs the exact preview payload using the application's
existing signing dependency. An absent, stale or altered recurring preview is
re-evaluated/displayed before submission. This is a review safeguard, not a hold;
approval and handover still recheck authoritative inventory under transaction locks.

Recurring rule/timezone fields are immutable. PostgreSQL timezone-name validation
therefore runs once on insertion, not for every deferred aggregate check: repeated
timezone catalog enumeration was measurably expensive on Windows. Every occurrence
and reservation still receives its integrity checks.

## Operational limits

- Series waiting-list enrollment needs an explicit university series policy. Current
  queues remain single-interval; there is no silent splitting or second queue engine.
- Material changes use cancellation plus a fresh approved proposal. Past uses and
  actual loan facts are not rewritten. There is no speculative revision scheduler.
- Larger series still use bounded synchronous engine execution and existing locks;
  a busy database/engine failure requires retry. There is no distributed job system.
- Legacy academic commitments require explicit period/week bindings. Neither forms
  nor calendar projections infer semester dates or pretend unresolved commitments
  do not exist. Changing the configured display timezone does not rewrite stored dates.

See [database design](database-design.md), [versioned protocol](../engine-protocol.md)
and [operations](../database-operations.md#recurring-room-and-equipment-reservations).
