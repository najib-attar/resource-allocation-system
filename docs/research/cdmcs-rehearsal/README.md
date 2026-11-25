# CDMCS meeting rehearsal

The Campus Space **Meeting rehearsal** demonstrates native CDMCS rankings
over one required participant set. The organizer stays accountable for
the search, co-hosts and required attendees share the same hard checks, and
optional invitees do not block a time. The rehearsal supports one-to-one,
one-to-many, many-to-one, and many-to-many searches under fictional Student,
Instructor, Research Assistant and Staff identities. A fictional Administrator
can inspect the rehearsal under the same membership rules.

The [weight evaluation](weight-analysis.md) compares all 18 configurations
on common metrics. Use rates 1/2/4, gap weight 1, a 120-minute hard cutoff,
delay 10 per local day, and relocation costs of 25 fixed plus 50 per affected
participant. The weight comparison is provisional and applies to the
rehearsal. [Raw comparison data](weight-observations.csv) ·
[Machine-readable summary](weight-summary.json)

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
`fictional-logins.json` privately. Sign in and choose **Account menu →
Meeting rehearsal**. Press Ctrl+C in the launcher terminal to stop the
rehearsal and its database process.

The default fixture includes a protected class, a confirmed advising
appointment, a lab block, published instructor hours, and synthetic private
preference revisions. An optional `--course-archive` argument accepts the
reviewed İTÜ Fall 2026–27 JSON and mirrors one published BBB teaching interval
on day two or three in the existing course entities. Only the public slot and
its source metadata are mirrored. The instructor and enrollment in the
rehearsal are fictional. The option reports when there is no usable session
inside the archived term.

Select the fictional student Aylin as the signed-in user and instructor Cem as
a required attendee to see a case with both direct times and proposals to
move one fictional flexible meeting. The **Request a standard appointment**
form on that result posts the selected direct time to the existing booking
route. The instructor can approve the same revision from Appointments.
Check the date in each participant's Calendar after approval.

## Integration stages and boundaries

| Stage | Behavior |
| --- | --- |
| Read | The rehearsal requires the dedicated startup path, current authenticated session, exact fictional roster and local request origin. It reads the same teaching, appointment, room-organizer, and personal commitments used by the appointment calendar service. |
| Rank | The existing D1 compiler consumes scoped preference revisions or clearly defined fixture defaults. The existing coefficient contract validates the rehearsal-only policy. The isolated runner verifies the native executable and caps its runtime and output. The response contains dates and explanations, with opaque identities and individual preference scores confined to the server. |
| Relocation | The known fictional blocker can be considered for one move when all its attendees are in the required set. All persisted commitments stay protected. The separate list gives the proposed replacement time and consent condition. A result is discarded if the calendar or preference revisions change during the search. |
| Book | A direct eligible student–instructor selection can enter the existing appointment flow and inherits its time validation, revision approval and atomic calendar writes. Other combinations remain recommendations in the rehearsal. |

The existing appointment aggregate enforces Student organizer, Instructor
approver and Student invitee roles in PostgreSQL. Extending durable group
bookings needs the approved initiation, approval and visibility matrix and
an additive aggregate design. Executing a relocation needs explicit
revision-bound consent from affected participants, resource authority where
applicable, and an atomic revalidation and commit. Required-room appointment
booking and institution-wide activation remain outside this rehearsal.

## Verification commands

~~~powershell
$env:CDMCS_REHEARSAL_TEST_ENGINE = $cdmcs
& $python -B -m unittest discover -s tests -p test_cdmcs_rehearsal.py -v
$env:PLAYWRIGHT_NODE_MODULE = 'C:\path\to\node_modules\playwright-core'
node tests/cdmcs_rehearsal_browser.cjs 'C:\path\to\fictional-logins.json' 'C:\path\to\evidence'
~~~

Run the browser check against a fresh rehearsal. It creates one synthetic
appointment, approves it and checks both calendars. It captures desktop and
mobile screenshots from the running Flask server.

## Executed verification

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
