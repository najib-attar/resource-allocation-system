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

This document records the reviewed integration design; implementation and actual
verification evidence are recorded as the iteration is completed.
