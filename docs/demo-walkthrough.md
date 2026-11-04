# Run and explore the fictional university demo

The Windows launcher creates an owned, loopback-only PostgreSQL profile with
fictional university records. It starts the actual Flask application and C++
integration; it does not replace workflows with mock responses.

## Prerequisites and startup

Install Python 3.12/3.13, PostgreSQL 17 tools and a C++17 `g++` compiler. From the
repository root in PowerShell:

```powershell
python scripts/build_backend.py
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_demo.ps1
```

The launcher installs pinned Python dependencies into its profile environment,
prepares its private PostgreSQL server, upgrades that designated demo database,
verifies the authoritative engine and seeds fictional inputs once. Open
`http://127.0.0.1:5000` and keep the terminal open.

If tools are outside the discovered locations, supply `-PythonPath`, `-CompilerPath`
or `-PostgresBin` (the PostgreSQL `bin` directory). The launcher does not install
system tools, modify Windows services or reset an unrelated database. Internet is
needed for missing Python packages.

Build before the first launch and after C++ changes. On Windows PowerShell a
missing/stale engine can stop the launcher's freshness check before its intended
rebuild fallback. The explicit build above avoids that limitation. Use
`python scripts/build_backend.py --compiler PATH` if `g++` is outside PATH.

## Persistent profiles and accounts

The default profile is `build/local-demos/university-demo/`. Its private
`settings.json` selects the connection, generated demo password and explicit
academic period. New profiles default to PostgreSQL port **55443** and fictional
dates **7–31 January 2030**. An existing profile keeps its saved settings, which
may differ. Use the launcher's printed summary rather than a machine-specific port.

The launcher prints generated student, professor and administrator sign-ins.
Choose the displayed users for the walkthrough below; use the generated password
from that profile. Never upload private settings or reuse demo credentials in a
real installation. Normal account provisioning is documented in
[database operations](database-operations.md#accounts-and-appointment-calendars).

All services in a profile share one application database. Rerunning the same
command preserves users, passwords, appointments, requests, notifications and
manual decisions. Conflicting explicit settings are rejected rather than applied
as a reset. Do not delete a profile to repair an error or treat an existing
database as disposable.

To work as two users at once, use separate browser profiles or one normal window
and one InPrivate/incognito window. Two ordinary tabs in the same profile share
the login cookie.

## Appointment walkthrough

Use a future date inside the profile's printed academic period and the selected
professor's published hours. If the saved fictional period is in the past, review
its development calendar explicitly rather than assuming the launcher resets it.

1. Sign in as a printed student. Home links to **Appointments** and the existing
   service hubs; an empty schedule is a valid initial state.
2. Start a new appointment. Select the configured faculty and one printed professor.
   Select more required professors for unanimous approval, and optionally invite
   another printed student through the separate student chooser.
3. Enter purpose/duration and a date. Choose an available-time recommendation or
   a manual proposal. Both are checked against published hours and commitments.
4. Submit for professor approval. **Pending Approval** reserves no time.
5. In the professor's separate browser, open the appointment notification or the
   pending Appointments list and approve the current revision.
6. If multiple professors are required, each must approve independently. After the
   last approval, the appointment becomes **Confirmed**.
7. Open Calendar or My Schedule in both accounts at that date. The confirmed
   mandatory commitments are recorded for the organizer and required professors.
8. An optional student may decline without cancelling the meeting. As organizer,
   reschedule to invalidate earlier approvals, or cancel to release commitments.

Professors publish weekly patterns, validity dates and exclusions through **Office
Hours**. Personal blocks use **My Schedule**. Existing confirmed commitments
remain protected; absent professor hours are not treated as free availability.

## Rooms and equipment

### Student room-request demonstration

From Student Home, open Rooms, describe the activity, capacity/facilities and date,
then review real recommendations and busy/free availability. Submit the selected
room for faculty approval. The detail identifies the responsible approver; use
that printed staff/administrative account to approve or reject. Other accounts
cannot substitute for the assigned approver. Pending requests reserve nothing.

An approved room request appears as confirmed on the authorized calendar. Optional
professor invitations grant attendance choice, not faculty approval authority.
Configured semesters and existing policy govern recurring requests and occurrence
actions. Existing profiles are never silently reassigned room ownership.

### Equipment borrowing

For borrowing, use the [equipment walkthrough](equipment-borrowing-guide.md).
Approval, physical collection and verified return are separate. A due time never
means an asset has physically returned; only authorized custodians perform handover
and inspection. Eligible waiting-list and private feedback links appear in their
existing resource workflows.

### Optional service examples

To add the existing labeled appointment/room/equipment examples to an owned
fictional profile:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_demo.ps1 -ServiceExamples
```

The real services perform these decisions; the printed summary shows detail URLs,
statuses and assigned deciding accounts. Rerunning reports existing examples and
preserves manual decisions. If a date/resource is unavailable, inspect the error;
the tool does not relax calendars or policies to force success. Do not use this
seed against operational data.

## Academic requests, eligibility and allocation

As a professor, open Academic Requests and submit an Exam, OneTime, Recurring or
CommitteeMeeting declaration. These use existing weekly resource contracts;
course/faculty descriptions do not verify affiliations. Submission starts
**Pending Eligibility Review**, without allocation or reservation.

As an administrator, open **Academic Eligibility** and review each relevant request
with a recorded reason. Default seeding/import does not approve academic inputs.
Only eligible current revisions can enter **Run Allocation**. Relevant unreviewed
legacy requests block replacement; rejection preserves current published
reservations until an authorized replacement. Eligibility review itself does not
reserve a room. The administrative request-save shortcut leads to review first.

After allocation, professors can inspect their own outcomes and actual resources.
Eligible and allocated are different states. Active published inputs remain
read-only; material unpublished revisions require review again. Academic
notifications, cancellation and versioned replacements are deferred.

The unified Calendar offers month/week/day navigation and category/status filters.
Weekly academic inputs need explicit **Calendar Setup** applicability; authorized
**Academic Publication** controls visibility. No dates, student enrollment or
professor teaching responsibility are inferred from declarations. Equipment entries
are reminders rather than personal busy time.

## Restart and configuration

`Ctrl+C` stops Flask; the owned PostgreSQL server can remain running locally.
Rerun the same launcher to resume. Restart after Python changes; refreshing a
non-debug server does not reload modules. `-SetupOnly` prepares without serving,
and `-WebPort 5001` selects a different web port.

For a deliberately new fictional profile, `-Profile NAME`, `-PostgresPort PORT`,
`-AcademicStart YYYY-MM-DD` and `-AcademicEnd YYYY-MM-DD` select its initial settings.
These are new-profile options, not a migration/reset procedure for saved users.
Rebuild a missing/stale engine before relaunching; database/configuration failures
never fall back to CSV results. Use [database operations](database-operations.md) for manual
setup, backup and controlled upgrades, and the [developer guide](../web/README.md)
for environment configuration and tests.
