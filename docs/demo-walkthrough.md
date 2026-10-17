# Run and explore the fictional university demo

For the equipment service, see [the equipment walkthrough](equipment-borrowing-guide.md).
New fictional profiles include inventory automatically; existing profiles remain
unchanged and can use the explicit additive development seed described there.

From Windows PowerShell in the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_demo.ps1
```

## Ready-made student service examples

Use the same primary local database for appointments, rooms and equipment:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_demo.ps1 `
  -ServiceExamples
```

The existing users, resources and equipment are fictional. Nine clearly labeled
`[Demo]` requests exercise **Accepted**, **Rejected** and **Pending** outcomes for
appointments, rooms and equipment. The real services and C++ engine perform the
decisions; the tool does not insert fake approved allocations. Its printed summary
lists each detail URL, current status, deciding account and actual assignments.
The current local setup uses the explicit fictional period **19 October through
13 November 2026**. Saved dates never reset. A fresh installation must configure
its own explicit academic period; do not infer dates for existing records.

- `student1`: all nine requests, received decisions, upcoming confirmed timetable.
- `professor1`: appointment decisions and room invitations.
- `admin` (or the printed assigned account): room decisions and equipment custody.
- `student2`: optional appointment invitations.

The password is printed by the launcher and remains in the profile's private
`settings.json` as `demoPassword`. Existing profiles and passwords are not changed.
For October examples, select the **19 Oct** week in My Schedule. Appointment
acceptance is called **Confirmed**, rejection **Declined**; rooms use Confirmed /
Rejected, and equipment uses Approved / Rejected. Approved equipment is reserved,
not physically borrowed until verified handover.

Pending examples remain undecided so you can try either action. After deciding,
the request's current status and available actions change; old submission messages
remain as history, not pending tasks. The notification badge counts **unread
updates**, not pending requests. Every notification shows its current request
status, sender, recipient and time. Students see their own activity and outcomes;
professors see requests addressed to them and their own decisions. Only the assigned
room approver or authorized equipment custodian sees the operational audit log,
including actors and actual notification recipients. These records live in PostgreSQL.

Rerunning `-ServiceExamples` reports existing examples and never resets manual
decisions or creates duplicates. To add the examples to an already initialized,
owned fictional profile without starting Flask:

```powershell
python scripts/seed_service_examples.py --state-dir build/local-demos/university-demo
```

If preparation fails partway, completed examples are retained and reported on a
rerun. The tool refuses unowned profiles and never changes calendars or policies to
force an unavailable request to succeed. Do not use it against production data.

The launcher installs `requirements.txt` into its own environment, prepares a
password-protected, loopback-only PostgreSQL server, migrates the **single application
database**, verifies/builds the C++ executable and seeds fictional university
inputs. Allocation results come from the real engine. It starts Flask at
`http://127.0.0.1:5000`; keep the terminal open. This is local development, not
production deployment.

Prerequisites are Python 3.12/3.13, PostgreSQL 17 tools and C++17 `g++`. Existing
repository-local tools or PATH installations are discovered automatically.
If tools live elsewhere, use `-PythonPath`, `-CompilerPath` and `-PostgresBin`.
The launcher does not install system software, alter Windows services or modify
an unrelated database. Internet is needed only for missing Python packages.

## One local application database

The primary local profile is `build/local-demos/university-demo/`. Its private
`settings.json` selects **resource_allocation** on `127.0.0.1:55448` in the current
installation. All users, appointments, equipment, room requests, notifications and
history belong to this same database. The historical profile directory name does
not imply a second operational database. The launcher reuses the saved connection;
you do not need a different profile for each service.

The data is fictional but this is the application's actual local persistence,
not a CSV copy or a second demo database. Retired fixtures are kept only in private
backups outside the repository. PostgreSQL's `postgres`, `template0` and `template1`
are system databases, not additional application databases, and must not be deleted.
Automated integration tests use disposable isolated databases/schemas which are
removed afterward; never run destructive tests against this primary database.

## Initial data and sign-in

| Data | Default |
|---|---:|
| Students | 80 |
| Professors (Instructor role) | 12 |
| Administrators | 2 |
| Teaching assistants / staff | 6 / 6 |
| Resources | 20 |
| Room requests | 120 |
| Professor office-hour patterns | 60 |

Names, emails and request details are fictional and generated reproducibly using
seed 42. The first two professors belong to **Faculty of Applied Sciences** so
the multi-professor demonstration is easy. Their actual generated names appear
in the launcher's account list. Weekday office hours are 09:00-17:00 Istanbul time.

The launcher prints one randomly generated **demo password**. Use it with:

| Username | Use |
|---|---|
| `student1` | Organize an appointment |
| `student2` | View/decline an optional invitation |
| `professor1` | Publish hours and approve requests |
| `professor2` | Second required approval |
| `admin` | Dashboard, users, resources and allocation results |

Other accounts are `student1` through `student80`, `professor1` through
`professor12` and `admin2`. The shared password is only a convenience for this
isolated fictional demo; never use these credentials in a real installation.
Private settings and data live under `build/local-demos/university-demo/`, which
Git ignores. Do not upload that directory: `settings.json` contains credentials.

## Appointment walkthrough

Use dates in the saved explicit academic period; the current walkthrough uses
October 19-November 13, 2026. A fresh installation's default remains January 7-31,
2030 unless configured explicitly. Neither assigns dates to real university records.

1. Sign in as `student1`. **Home** shows a current-month hourly timetable,
   your next confirmed meeting, bookings, pending requests and optional invitations. New
   accounts correctly show empty states. Click **Schedule an appointment**.
2. Select **Faculty of Applied Sciences**, open **Choose professors**, and search
   for the names shown for `professor1` and `professor2`. Use the separate
   **Choose students** list for `student2` if you want optional participation.
   Numeric fictional-name suffixes are hidden; accounts and stored IDs stay unchanged.
3. Enter a purpose and duration, for example 30 minutes. Select **Appointment date**
   `2026-10-26` once for the current local data. Feasible time buttons load automatically; **Refresh times**
   retries the check. University commitments and personal blocks are considered.
4. Select a recommendation and **Submit for professor approval**. Its status is
   **Pending Approval**; no time has been reserved yet.
5. Sign out, sign in as `professor1`, open the request under **Appointments** and
   approve it. With two professors selected, it remains pending.
6. Sign in as `professor2` and approve the same revision. It becomes **Confirmed**.
7. Return to student **Home**: the confirmed booking and next-meeting card now
   appear. Click **Show this week**, or choose October 2026 under **Month** and
   select the **26 Oct - 30 Oct** week. **My Schedule** uses the same hourly
   timetable for students and professors. Pending requests do not reserve time.
8. As `student2`, open the invitation and decline it. Confirmation is unaffected;
   professors can see the declined status. No acceptance is required.
9. As the organizer, change the proposed time to clear all professor approvals,
   or cancel to release the reserved time. A selected professor can also cancel.

For one professor, select just one. For multiple students, invite additional
students. These selections demonstrate all four supported configurations.
Professors manage recurring publications through **Office Hours**, and everyone
can add date-specific blocks through **My Schedule**. Do not remove hours needed
by future confirmed appointments before cancelling/rescheduling them.

## Explore room allocation

### Student room-request demonstration

Use the same database and login accounts as the appointment walkthrough:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_demo.ps1
```

1. Sign in as `student1`, then choose **Find a room** from Home or **Room Requests**.
2. Enter a study/meeting/lecture/club/other purpose, total attendees, facilities,
   optional faculty/building preferences and professor invitations. Use an explicit
   fictional date such as `2026-10-26 10:00`, with a 60-minute duration.
3. Review the ranked room and its owning faculty. Submit for faculty approval;
   pending requests reserve nothing. The detail page names the assigned approver.
4. Sign in as `admin` or `admin2`, whichever the detail page assigns. Open
   **Room Requests**, inspect the pending event and **Recheck and approve** or reject
   with an explanation. Other faculty approvers cannot approve it.
5. Return as `student1`: view Confirmed and October 2026 under My Schedule.
   As an invited professor, open Room Requests to accept or decline optional attendance.
6. Cancel as organizer or the assigned faculty administrator to release the room.
   Revise pending requests for a new room/time and approval; confirmed changes require
   cancellation plus a new request. Activity history remains available.

New demo profiles explicitly configure fictional room ownership. An existing profile
is never automatically reassigned: use **Room Policies** as its administrator to
designate faculty approvers and configure the actual known room owners. Unconfigured
rooms deliberately remain unavailable to student requests. Professor appointments
and the ordinary administrative allocation dashboard remain separate workflows.

Sign in as `admin`. Open **Users**, **Spaces**, **Requests**, **Allocation Summary**
and **Schedules**. The seed has already run the real allocation engine. Select a
strategy on **Dashboard** and use **Run Allocation** to compare its results.
**Add Request** supports Save Only and Submit and Run. Weekly room schedules are
separate from dated appointment calendars; anonymous exam attendees do not define
student enrollment schedules.

## Restart and options

`Ctrl+C` stops Flask. Rerun the same command to resume with existing requests,
appointments and passwords preserved. The private PostgreSQL server stays local
and can be reused. `-SetupOnly` prepares the demo without serving Flask;
`-WebPort 5001` selects another web port.
After Python application changes, restart the launcher to load the new code;
refreshing an already running, non-debug server does not reload Python modules.

Reruns use the primary profile's saved settings. Explicitly conflicting settings
are rejected, never applied as a reset. To change the academic calendar, use an
explicitly reviewed data/configuration change rather than creating another
operational database. A failed setup can leave saved inputs; inspect the error
without deleting the database. Missing or stale engines are rebuilt; malformed database/configuration
does not trigger CSV fallback. Keep the normal application setup in
[database operations](database-operations.md) for non-demo use.
