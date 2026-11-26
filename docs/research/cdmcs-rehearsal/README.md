# CDMCS group meeting pilot

The opt-in Campus Space pilot supports persistent one-to-one, one-to-many,
many-to-one, and many-to-many meetings among fictional students,
instructors, research assistants, staff and administrators. It shares
the application session, PostgreSQL calendar, Inbox, and room approval
services. Standard appointments and the original **Meeting rehearsal**
remain available. [Architecture, role matrix and diagrams](group-meeting-architecture.md)

The [weight evaluation](weight-analysis.md) compares all 18 configurations
on common metrics. Use rates 1/2/4, gap weight 1, a 120-minute hard cutoff,
delay 10 per local day, and relocation costs of 25 fixed plus 50 per affected
participant. The weight comparison is provisional and applies to the
rehearsal. [Raw comparison data](weight-observations.csv) ·
[Machine-readable summary](weight-summary.json) · [Comparison export](weight-comparison.csv) ·
[Preliminary W0–W5 record](preliminary-w0-w5.md)

## Run on Windows

Run from the application integration checkout with the repository's Python
dependencies, PostgreSQL tools, a matching production C++ executable and
the separately built [standalone CDMCS executable](../../../research/cdmcs/i1/README.md).
Use the independently verified hash for the standalone build. The archived
Windows research binary has SHA-256
`3cccc1c373393c8fc4acf0f36d9e80edc787a613b27cf8143bd7a0884be55b5f`.

~~~powershell
$python = 'C:\path\to\venv\Scripts\python.exe'
$postgresBin = 'C:\path\to\PostgreSQL\17\bin'
$cdmcs = 'C:\path\to\cdmcs_i1.exe'
$reviewedHash = '3cccc1c373393c8fc4acf0f36d9e80edc787a613b27cf8143bd7a0884be55b5f'
& $python -B scripts/run_cdmcs_rehearsal.py --postgres-bin $postgresBin --engine $cdmcs --engine-sha256 $reviewedHash
~~~

The application executable defaults to the current checkout's
`build/backend/allocation_system.exe`. Build it with
`python scripts/build_backend.py --if-needed` or pass a verified matching
executable with `--backend`. The launcher creates an owned loopback
PostgreSQL cluster, migrates its fresh database, and prints the loopback
web address and path to the generated fictional sign-ins. Open
`fictional-logins.json` privately. Open **Group meetings** from your role
home or from **Appointments**. Staff reaches it from Appointments.
**Account menu → Meeting rehearsal** opens the original comparison preview.
Press Ctrl+C in the launcher terminal to stop the pilot and its database
process. Each launch owns a fresh synthetic database with its own accounts.

The default fixture includes a protected class, a confirmed advising
appointment, a lab block, published instructor hours, and synthetic private
preference revisions. An optional `--course-archive` argument accepts the
reviewed İTÜ Fall 2026–27 JSON and mirrors one published BBB teaching interval
inside the fixture's first three days in the existing course entities.
Only the public slot and its source metadata are mirrored. The instructor
and enrollment are fictional. Omit the optional archive if the available
fixture dates do not contain a matching session inside the academic term.

## Demonstration

1. Sign in as any organizer and open **Group meetings → Find meeting times**.
   Choose required guests, any co-hosts, and optional invitees. Direct options
   show group-level preferred coverage, wait, net gaps and modeled cost.
   A positive gap count means the arrangement adds idle gaps.
2. Select a direct option, enter a purpose, and submit. Sign in separately
   as each required guest or co-host and approve the current revision.
   Verify the confirmation in both Calendar and Inbox. Optional invitees
   may accept or decline without reserving their calendars.
3. Open **Scheduling preferences** to edit the separate dated hard windows
   and soft preferences. To demonstrate relocation, enable consideration
   in each affected person's settings and confirm one online meeting
   explicitly marked flexible. Search again as one of its required attendees
   with the entire old required set included. Propose a conditional option
   and record both the new meeting approvals and the separate move consents.
   A refusal keeps the original booking, and the organizer can search again.
4. For a physical meeting, use the existing Student room request form with
   category **Meeting**, the exact time, the full headcount and facilities.
   Use the assigned Staff approver to decide the request. Attach the
   approved booking in the group form and finish the required approvals.
   The group uses that existing reservation and creates participant commitments.

## Integration stages and boundaries

| Stage | Behavior |
| --- | --- |
| Read | The dedicated startup path verifies an owned loopback database, current authenticated session and exact fictional roster. Calendar reads use the regular teaching, appointment, room-organizer, and personal projections. |
| Rank | The D1 compiler uses scoped private preference revisions and the provisional coefficient contract. Separate result lists summarize group-level metrics. Signed selections are bound to the organizer's session and calendar revision. |
| Book | The existing calendar lock protects required approval, both possible interval writes, and recipient-scoped updates. PostgreSQL rejects incomplete confirmation, overlapping group commitments, and release of a room for a confirmed group. |
| Retain the fallback | Regular Student–Instructor appointments continue through the existing scheduler. The old rehearsal comparison keeps its opt-in test fixtures and standard direct booking handoff. |

The pilot supports only fictional identities. Physical meetings attach an
already approved one-time Student room booking. Physical meetings and
ordinary academic commitments stay fixed. A move considers up to three
eligible flexible targets and four replacement starts per target, including
the earliest and latest available starts. A pending online meeting can be
revised by its organizer. A confirmed group retains its reservation until
an authorized cancellation or a separately consented move. Fully general
confirmed replacement requests, rankings that combine unapproved rooms
with calendar options, and activation on real private calendars remain
outside this pilot.

## Verification commands

~~~powershell
$env:CDMCS_REHEARSAL_TEST_ENGINE = $cdmcs
& $python -B -m unittest discover -s tests -p test_cdmcs_rehearsal.py -v
$env:PLAYWRIGHT_NODE_MODULE = 'C:\path\to\node_modules\playwright-core'
node tests/cdmcs_rehearsal_browser.cjs 'C:\path\to\fictional-logins.json' 'C:\path\to\evidence'
node tests/group_meeting_pilot_browser.cjs 'C:\path\to\fictional-logins.json' 'C:\path\to\pilot-evidence'
~~~

Launch a fresh pilot for each browser script. The original comparison
script verifies a standard student–instructor appointment. The group
script verifies persisted requests, decisions, preferences, room linking,
and change consent. Both capture screenshots from the running Flask server.

## Prior rehearsal verification

On 25 November 2026, 17 rehearsal tests passed with the standalone native
executable. The appointment, calendar and teaching integration suite passed
40 tests. The identity, preference and cost policy suite passed 61. Both
application suites used disposable PostgreSQL and completed with zero
failures or skips.

Edge exercised all four group shapes from their role workspaces, plus the
Administrator's roster boundary. Keyboard navigation and widths of
1440, 1024, 768, 390 and 320 pixels were verified. A direct option became
a standard confirmed appointment visible in both calendars. PostgreSQL
contained two matching commitment rows. The public timetable mirror
retained CRN 12367 and its normalized 27 November interval of
14:00–17:00 Istanbul time. A date-scoped browser search excluded that
interval.

## Persistent pilot verification

Verified on 26 November 2026 with disposable PostgreSQL, the verified
standalone CDMCS executable and the existing production C++ executable.

| Scope | Passed | Failed | Skipped |
| --- | ---: | ---: | ---: |
| Group meetings, relocation, physical booking and teaching protection | 14 | 0 | 0 |
| Group preferences, Inbox/calendar projection and room checks | 18 | 0 | 0 |
| Appointment, calendar loading, course and migration regressions | 36 | 0 | 0 |
| Original rehearsal and native integration | 17 | 0 | 0 |
| Database diagrams and schema catalogue | 1 | 0 | 0 |

Migration checks verified `0051e` → `0051f`, an empty pilot downgrade,
preserved password hashes and prior notifications, and refusal to discard
populated availability. Lifecycle tests exercised concurrent confirmations,
current-revision approval, explicit move refusal, a failed final recheck
with rollback, and direct PostgreSQL rejection when a required move consent
is missing.

Edge exercised the four group shapes through the role workspaces at
320, 390, 768, 1024 and 1440 pixels. It verified private Inbox links,
CSRF and participant denials, optional decisions, a refused move, an
executed move, and physical confirmation through a faculty-approved
booking. The moved group kept its original commitment until the last
required decision. The room workflow rejected an interval that conflicted
with the new commitment and refused to release the linked booking while
the physical group remained confirmed. A read-only PostgreSQL check
confirmed both sets of committed intervals and their notification
recipients.
