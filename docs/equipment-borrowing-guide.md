# Equipment borrowing

## Setup

Build with `python scripts/build_backend.py`, configure PostgreSQL and the existing
session secret, then run `python -m alembic upgrade head`. Head `0044c` is
additive and leaves existing users, room allocations and appointments intact.
Normal Flask operation still uses PostgreSQL only. The existing launcher reuses
the same primary local database as appointments and rooms; fresh setups include
equipment inventory. A second operational database is not required.

For an **existing fictional development database** with accounts/faculties but no
equipment configuration, explicitly select its `DATABASE_URL` and run:

```powershell
python scripts/seed_equipment_demo.py --administrator <existing-admin-user-id> --confirm-development-database
```

`--seed 44` is reproducible. `--size large` creates 400 units per faculty instead
of 40. The tool creates no approved loans or reservations, refuses existing
equipment configuration and commits the seed atomically. It never resets a
database. Do not use this seed command against production.

## Administrator

Open **Administration -> Equipment Custodians**. Choose a faculty and an enabled
staff/administrator account. Each faculty has one current assignment. Replacing
it transfers workflow authority immediately; it does not change room approvers.
Missing or disabled assignments block borrowing, rather than approving silently.

## Custodian

Open **Equipment**, then your faculty inventory. Register a type/category,
description, exact specifications, maximum loan days, pickup/return information
and optional eligible faculties. Add physical units with unique asset tags.
Record condition changes with a reason; disable a type when new borrowing must
stop. Outstanding borrowed devices cannot be marked usable in lieu of a return.

The equipment inbox includes requests assigned to your faculty. Open a pending
request to approve the complete quantity or reject with an optional reason.
Approval reserves exact units; it does not record collection. During the approved
period, inspect the listed assets and record their condition using **Confirm
collection**. Do not hand out an unreturned device from another loan.

For returns, select the physically inspected units and outcome. Select a subset
for partial return. Damaged/maintenance units remain blocked. Missing/lost means
not returned; later recovery requires a new physical-return inspection. Review
extensions before approving: existing reservations and maximum duration still apply.
Inventory attention flags identify overdue units and affected future reservations.

## Student

1. Sign in and open **Equipment -> Browse and borrow**.
2. Choose pickup and expected-return times in the displayed university timezone;
   refresh the catalog. Choose one owning faculty and quantities for its types.
3. Enter purpose and optional notes. Additional exact specification requirements
   are optional. Check availability/alternatives, then submit for approval.
4. Open your request to see decisions, due date, reserved asset identifiers after
   approval, and history. Collect only after the custodian verifies handover.
5. Indicate return intent if useful; physically return to the custodian. Intent
   alone never changes availability. Request an extension with a later due date
   and reason when necessary. It is not effective until approved.

Pending/uncollected reservations can be cancelled. Borrowed equipment cannot be
cancelled. A declined extension does not cancel the existing loan. Notification
updates are in the shared bell/inbox. Overdue alerts refresh when the equipment
inbox is opened; there is no email delivery or background reminder scheduler.

## Limits and recovery

Matching uses exact text specifications, not semantic guessing or machine learning.
Unreturned units conservatively block new future allocations even before their
planned due date; staff can still inspect already approved future reservations.
Requests contain at most 50 types/1000 units per item; the gateway enforces bounded
snapshot sizes and a process timeout. A busy faculty returns retry guidance;
engine failures roll back the operation. Existing approved results remain intact.
Use the existing database backup/recovery procedures; do not edit SQL loan state
by hand or bypass physical-return verification.
