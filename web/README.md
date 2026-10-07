# Resource Allocation Dashboard

This folder contains a small Flask dashboard for the C++ Resource Allocation System.

The web dashboard does not run allocation logic or modify the C++ backend. It displays data files from the project `data/` folder, can update the selected strategy in `config.txt`, can append new request rows to `requests.csv`, and can run the compiled backend executable for demo purposes.

## Install Flask

```bash
pip install flask
```

## Compile The C++ Backend

From PowerShell in the project root:

```powershell
python scripts/build_backend.py
```

The single default backend artifact is:

- Windows: `build/backend/allocation_system.exe`
- Linux: `build/backend/allocation_system`

The script requires `g++` on PATH. A compiler path containing spaces can be passed with `--compiler "C:\path to compiler\g++.exe"`. It also writes an adjacent `.build.json` manifest with the C++ source hash, binary hash, build time, and compiler identity. Flask refuses missing, stale, or mismatched builds and logs the verified build identity when running it. It never falls back to old root, test, or check executables.

For an intentional alternate location, build it explicitly and configure the same path:

```powershell
python scripts/build_backend.py --output "build/custom/engine.exe"
$env:RESOURCE_ALLOCATION_BACKEND = "build/custom/engine.exe"
```

Relative paths are resolved from the project root, not the shell working directory. Absolute paths are also supported. On Linux, use `export RESOURCE_ALLOCATION_BACKEND=/absolute/path/engine` after building with `--output` and keep its manifest beside it. Packaged deployments without `src/` still validate the binary against the manifest. Build before starting workers; this is not a hot-reload or signed-artifact system.

Run the resolution/integration regression tests with:

```powershell
python -m unittest discover -s tests -p test_backend_executable.py -v
```

Build first to include the live C++/Flask smoke test; it reports an explicit skip if the authoritative artifact is unavailable. The live smoke uses temporary input/output files, not the project's generated CSVs.

## Run Flask From The Project Root

```bash
python web/app.py
```

## Run From The Web Folder

```bash
cd web
python app.py
```

## Open The Dashboard

Open this address in a browser:

```text
http://127.0.0.1:5000
```

Click `Run Allocation` on the home page to run the validated C++ backend artifact from the project root, then display the updated `allocations.csv` and `request_results.csv` files. Validation/startup errors are shown instead of executing an arbitrary binary.

## Dashboard Flow

The dashboard is organized around a cleaner demo workflow:

1. Add one or more requests from `Add Request`.
2. Either choose `Save Request Only` for batch entry or `Submit and Run` to immediately process the newly added request.
3. Use `Requests` to search, filter, and open a request detail page.
4. Use `Allocation Summary` as the main result page for approvals, rejections, allocations, committee participants, and least-change suggestions.
5. Use `Schedules` to confirm user busy slots or room allocations after allocation has run.
6. Use `Raw Data` only when you need to inspect CSV files directly.

The Flask app still does not compute allocation, participant availability, or suggestions. It writes CSV rows, runs the compiled C++ executable, and displays backend-generated CSV outputs.

## Recommended Demo Workflow

1. Compile the C++ backend.
2. Run the Flask dashboard.
3. Open the dashboard in the browser.
4. Select `multi_room_exam_best_fit`.
5. Add or review requests.
6. Click `Run Allocation`.
7. Open `Allocation Summary`.
8. Compare with `multi_room_exam_greedy` if needed.

`Allocation Summary` is the best page for demonstrating split exam assignments because it groups each request with its assigned rooms.

## Select A Strategy

On the dashboard home page:

1. Choose a strategy from the dropdown.
2. Click `Save Strategy`.
3. Click `Run Allocation`.

Saving a strategy updates `data/config.txt` with:

```text
allocation_strategy=<selected_strategy>
```

The Flask app does not implement strategy logic. It only updates the config file. The C++ backend reads `config.txt` and uses `AllocationStrategyFactory` when the allocation executable runs.

Supported strategies:

- `greedy`: processes requests in loaded order.
- `priority`: processes requests by request priority.
- `multi_room_exam_greedy`: splits exams across available classrooms in greedy order.
- `multi_room_exam_best_fit`: splits exams using a best-fit room combination to reduce unused capacity.
- `shared_room_exam_best_fit`: allows overlapping exam requests to share classroom capacity while still blocking normal non-exam bookings.

## Add A Request

Use the `Add Request` page from the navigation bar.

The form lets the user choose:

- `OneTime`
- `Recurring`
- `Exam`
- `CommitteeMeeting`

It collects the common request fields first, then asks for the time format needed by the selected type. Exam-specific fields are used only when the selected request type is `Exam`, and committee participant fields are used only when the selected request type is `CommitteeMeeting`.

When submitted, Flask appends one row to `data/requests.csv` using this format:

```text
requestId,requestType,userId,spaceId,participantCount,requiredFeature,requiredBuilding,timeData,title,purpose,courseCode,courseName,examType,canSplitAcrossRooms
```

For `OneTime` rows:

- `requestType` is `OneTime`.
- `timeData` is written as `day-HH:MM-HH:MM`.
- exam-specific fields are empty.
- `canSplitAcrossRooms` is `false`.

For `Recurring` rows:

- `requestType` is `Recurring`.
- `timeData` is entered directly, for example `2-9-10;4-9-10` or `2-09:00-10:30;4-13:15-14:00`.
- exam-specific fields are empty.
- `canSplitAcrossRooms` is `false`.

For `Exam` rows:

- `requestType` is `Exam`.
- `timeData` is written as `day-HH:MM-HH:MM`.
- course code, course name, exam type, and split support are written from the exam fields.

For `CommitteeMeeting` rows:

- `requestType` is `CommitteeMeeting`.
- `timeData` is written as `day-HH:MM-HH:MM`.
- `title` stores the meeting topic.
- `purpose` stores the selected meeting purpose, such as `Presentation`, `Thesis Defense`, `Project Review`, or `Committee Meeting`.
- exam-specific fields are empty.
- `canSplitAcrossRooms` is `false`.

The same request ID is also used to append required participants to `data/request_participants.csv`:

```text
requestId,userId,participantRole
```

The Add Request page shows instructor, teaching assistant, staff, and administrator users as selectable committee participants. Any number of participants can be selected, but at least one is required. Each selected participant can keep the default role `Participant` or use a role such as `Supervisor`, `CommitteeMember`, `Advisor`, or `Examiner`.

The CommitteeMeeting form is designed for the professor demo flow:

1. Open Add Request or use the home page's `Create Committee Meeting` button.
2. Choose `CommitteeMeeting`.
3. Enter the meeting title, requester, preferred room, expected attendee count, preferred day/time, purpose, and required participants.
4. Submit the request.
5. Review the confirmation page.
6. Click `Run Allocation Now` or open Allocation Summary after running allocation.

Flask does not check whether committee participants are free. It only writes `requests.csv` and `request_participants.csv`. After `Run Allocation`, the C++ backend creates the `CommitteeMeetingRequest`, attaches participants, and uses `ParticipantAvailabilityRule` with `user_busy_slots.csv` to approve or reject the request.

When a committee meeting is rejected because the requested time is not workable, the C++ backend may add least-change alternative time suggestions to the request lifecycle history. These suggestions scan Monday-Friday working hours in 30-minute increments, keep the original meeting duration, check required participant availability, check the requested room's existing allocations, and rank valid slots by distance from the originally requested time. The Allocation Summary page displays this exported suggestion text when it is present.

Day numbers use this mapping:

- `1` = Monday
- `2` = Tuesday
- `3` = Wednesday
- `4` = Thursday
- `5` = Friday
- `6` = Saturday
- `7` = Sunday

For example, `5-15:00-17:00` means Friday 15:00-17:00.

Supported time formats include:

- `3-10-12`
- `3-10:30-12:00`
- `2-09:00-10:30;4-13:15-14:00`

The web UI displays these in a more readable form when available.

For all new rows:

- blank feature or building constraints are written as `None`.
- `requestId` is generated as the current maximum numeric request ID plus one.

The form only performs basic input validation, such as valid user ID, valid space ID, positive participant count, title, purpose, and the required time fields. Backend validation, request construction, permissions, rule checking, and allocation still happen in the C++ program.

Adding a request only appends it to `data/requests.csv`. It does not immediately approve or reject the request. Approval, rejection, allocations, and rejection reasons appear only after `Run Allocation` is clicked.

After adding a request with `Save Request Only`, the dashboard shows a confirmation page. The request is saved immediately, but it remains pending until allocation is run. From the confirmation page, the user can:

- add another request,
- view the request detail page,
- view the request queue,
- run allocation immediately.

If `Submit and Run` or `Run Allocation Now` is clicked, Flask runs the compiled C++ backend and redirects to `/request/<requestId>`. The detail page focuses on the newly added request and shows its current status, rejection reason, suggestions, allocations, committee participants, and schedule links when available.

## User Profiles

`data/users.csv` supports optional extended profile columns:

```text
userId,name,role,email,status,primaryUnit,assignedRoles,studentNo,program,yearLevel,title,officeRoom,assistantType,jobTitle,adminLevel
```

The backend remains compatible with the old `userId,name,role` format and still uses the core identity and role values for allocation behavior. The web dashboard displays the optional profile fields on `/users` and supports role filtering for `Student`, `TeachingAssistant`, `Instructor`, `Staff`, and `Administrator`.

## Generated Files

After allocation runs, the backend generates or updates:

- `data/allocations.csv`
- `data/request_results.csv`

If these files are missing, the dashboard shows a friendly message instead of crashing.

## View Allocation Summary

Use the `Allocation Summary` page to see all request types grouped by request ID.

The page reads existing CSV files only:

- `requests.csv` identifies requests.
- `request_results.csv` provides approval or rejection status.
- `allocations.csv` provides room assignments and assigned participants.
- `spaces.csv` provides readable room names, capacity, type, and building.
- `users.csv` provides requester names.

One-time requests show their assigned space when approved. Recurring requests show each allocation occurrence. Exam requests show course details and grouped room assignments, including total assigned participants and unused capacity when room capacities are available.

If allocation outputs are missing, the page shows a friendly message asking the user to run allocation first.

## Request Detail Page

Each request can be opened at:

```text
/request/<requestId>
```

The detail page is useful after `Submit and Run` because it keeps the demo focused on the newly added request instead of forcing the user to search from the top of a long table.

It shows:

- request type, title, purpose, requester, requested room, and readable day/time,
- current backend status from `request_results.csv`,
- rejection reason if rejected,
- committee participants and roles for `CommitteeMeeting`,
- least-change suggestion text exported by the backend,
- approved allocation rows and links to the room schedule.

## View Schedules

Use the `Schedules` page to view user and space availability in a simple weekly table.

- User schedules read `data/user_busy_slots.csv` and show busy/free time for instructors, teaching assistants, staff, and administrators.
- Space schedules read `data/allocations.csv` and show allocated/free time for rooms after allocation has been run.
- Space allocation events link back to `/request/<requestId>` so the user can jump from a scheduled room slot to the request result.
- This page is visualization only. The C++ backend remains responsible for scheduling rules and allocation behavior.

## Raw Data

Use `Raw Data` for technical inspection of CSV files:

- `requests.csv`
- `allocations.csv`
- `request_results.csv`
- `request_participants.csv`
- `user_busy_slots.csv`
- `users.csv`
- `spaces.csv`
- `config.txt`

The main navigation keeps raw technical tables under this section so the demo flow stays focused on Dashboard, Add Request, Requests, Allocation Summary, and Schedules.

## Pages

- `/` shows the selected strategy, run allocation action, quick stats, recent requests, and demo shortcuts.
- `/users` shows `data/users.csv`.
- `/spaces` shows `data/spaces.csv`.
- `/requests` shows a searchable request queue with newest requests first.
- `/request/<requestId>` shows one focused request result/detail page.
- `/add-request` adds a new `OneTime`, `Recurring`, `Exam`, or `CommitteeMeeting` request row to `data/requests.csv`.
- `/allocation-summary` groups all allocation results by request.
- `/schedules` shows user busy slots and space allocation schedules.
- `/raw-data` shows raw CSV/debug data.
- `/add-one-time` redirects to `/add-request?type=OneTime`.
- `/add-exam` redirects to `/add-request?type=Exam`.
- `/exam-summary` redirects to `/allocation-summary`.
- `/allocations` redirects to `/raw-data?file=allocations.csv`.
- `/results` redirects to `/raw-data?file=request_results.csv`.

If `allocations.csv` or `request_results.csv` is missing, the dashboard shows a friendly message instead of crashing.
