# Run and explore the fictional university demo

From Windows PowerShell in the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_demo.ps1
```

The launcher installs `requirements.txt` into its own environment, prepares a
password-protected, loopback-only PostgreSQL server, migrates its **separate demo
database**, verifies/builds the C++ executable and seeds fictional university
inputs. Allocation results come from the real engine. It starts Flask at
`http://127.0.0.1:5000`; keep the terminal open. This is local development, not
production deployment.

Prerequisites are Python 3.12/3.13, PostgreSQL 17 tools and C++17 `g++`. Existing
repository-local tools or PATH installations are discovered automatically.
If tools live elsewhere, use `-PythonPath`, `-CompilerPath` and `-PostgresBin`.
The launcher does not install system software, alter Windows services or modify
your existing database. Internet is needed only for missing Python packages.

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

The default **explicit fictional calendar** is January 7-31, 2030. It does not
assign invented dates to real university records. Remember to change the date
fields from today's date when exploring this fixture.

1. Sign in as `student1`. **Home** shows a current-month hourly timetable,
   your next confirmed meeting, bookings, pending requests and optional invitations. New
   accounts correctly show empty states. Click **Schedule an appointment**.
2. Select **Faculty of Applied Sciences**, open **Choose professors**, and search
   for the names shown for `professor1` and `professor2`. Use the separate
   **Choose students** list for `student2` if you want optional participation.
   Numeric fictional-name suffixes are hidden; accounts and stored IDs stay unchanged.
3. Enter a purpose and duration, for example 30 minutes. Select **Appointment date**
   `2030-01-14` once. Feasible time buttons load automatically; **Refresh times**
   retries the check. University commitments and personal blocks are considered.
4. Select a recommendation and **Submit for professor approval**. Its status is
   **Pending Approval**; no time has been reserved yet.
5. Sign out, sign in as `professor1`, open the request under **Appointments** and
   approve it. With two professors selected, it remains pending.
6. Sign in as `professor2` and approve the same revision. It becomes **Confirmed**.
7. Return to student **Home**: the confirmed booking and next-meeting card now
   appear. Click **Show this week**, or choose January 2030 under **Month** and
   select the **14 Jan - 18 Jan** week. **My Schedule** uses the same hourly
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

To prepare a different explicit fictional calendar without resetting any data:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_demo.ps1 `
  -Profile another-demo -PostgresPort 55444 -Seed 17 `
  -AcademicStart 2031-01-06 -AcademicEnd 2031-01-31
```

Reruns of a profile use its saved settings. Explicitly conflicting settings are
rejected, never applied as a reset. A failed initial setup can leave saved inputs;
inspect the failure or choose a new profile rather than deleting an existing
database. Missing or stale engines are rebuilt; malformed database/configuration
does not trigger CSV fallback. Keep the normal application setup in
[database operations](database-operations.md) for non-demo use.
