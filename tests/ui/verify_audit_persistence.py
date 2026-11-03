"""Independently verify committed UI-10 POST transcripts, without browser claims.

The live review process records a separate read transaction before every POST
(before CSRF/auth guards) and after its response. This verifier checks domain
rows, notification persistence and cross-record invariants. It never connects
to a database, changes fixtures or infers success from an HTTP status alone.
"""
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'docs/ui/student-portal/UI-10'
REQUIRED = ['lifecycles', 'UI-03', 'UI-04', 'UI-05', 'UI-06', 'UI-07', 'UI-08', 'browser', 'authorization', 'loading', 'equipment-lifecycles']
ENRICHED = {'feedbackEvents', 'series', 'occurrences', 'notificationReadStates', 'roomInvitations'}
NOTIFICATIONS = {'notifications', 'notificationReadStates'}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def one(rows, key, value):
    matches = [row for row in rows if row[key] == value]
    require(len(matches) == 1, f'Expected one {key}={value}, found {len(matches)}.')
    return matches[0]


def selected(state, table, key, value):
    return [row for row in state[table] if row[key] == value]


def additions(before, after):
    return [row for row in after if row not in before]


def total_notifications(state):
    return sum(row['total'] for row in state['notifications'])


def invariant(state):
    """Validate real fixture states, including pending/confirmed distinctions."""
    for appointment in state['appointments']:
        key, status = appointment['id'], appointment['status']
        professors = selected(state, 'professors', 'appointment_id', key)
        commitments = selected(state, 'commitments', 'appointment_id', key)
        invited = {row['user_id'] for row in selected(state, 'invitations', 'appointment_id', key)}
        require(professors, f'Appointment {key} has no required professor.')
        require(all(row['revision'] == appointment['revision'] for row in professors),
                f'Appointment {key} professor revision mismatch.')
        if status == 'Confirmed':
            require(all(row['decision'] == 'Approved' for row in professors),
                    f'Appointment {key} confirmed without unanimous approval.')
            mandatory = {row['user_id'] for row in commitments}
            require(len(mandatory) == len(professors) + 1, f'Appointment {key} missing mandatory commitment.')
            require({row['user_id'] for row in professors} <= mandatory, f'Appointment {key} professor not reserved.')
            if 'organizer_id' in appointment:
                require(mandatory == {appointment['organizer_id']} | {row['user_id'] for row in professors},
                        f'Appointment {key} reserves a user outside its mandatory participants.')
            require(not mandatory & invited, f'Appointment {key} optional invitee incorrectly reserved.')
        else:
            require(not commitments, f'Appointment {key} has commitments while {status}.')
    for row in state['roomReservations']:
        room = one(state['rooms'], 'id', row['request_id'])
        require(room['status'] == 'Confirmed', f'Room request {room["id"]} holds reservation while {room["status"]}.')
        if row['occurrence_id'] is not None:
            require(one(state['occurrences'], 'id', row['occurrence_id'])['status'] == 'Reserved',
                    'Room reservation references an unreserved occurrence.')
    for room in state['rooms']:
        reservations = selected(state, 'roomReservations', 'request_id', room['id'])
        require(bool(reservations) == (room['status'] == 'Confirmed'),
                f'Room request {room["id"]}: confirmed/reservation mismatch.')
        if room['status'] == 'Confirmed':
            require(room['approved_revision'] == room['revision'] and room['approved_by'] is not None,
                    f'Room request {room["id"]} lacks matching faculty approval.')
    for invitation in state['roomInvitations']:
        require(invitation['revision'] == one(state['rooms'],'id',invitation['request_id'])['revision'],
                'Room invitation/registered-participant revision differs from its request.')
    for asset in state['assets']:
        if asset['returned_at'] is not None:
            require(asset['handed_at'] is not None, 'Returned asset was never handed over.')
            require(datetime.fromisoformat(asset['returned_at']) >= datetime.fromisoformat(asset['handed_at']),
                    'Asset return precedes collection.')
            require(asset['released'], 'Physically returned asset remains reserved.')
        if asset['handed_at'] is not None and asset['returned_at'] is None:
            require(not asset['released'], 'Outstanding physical loan incorrectly released.')
    recurring = {row['borrow_request_id'] for row in state['series'] if row['borrow_request_id'] is not None}
    for request in state['equipment']:
        if request['id'] in recurring:
            continue  # A series can contain collected, returned and future dates.
        assets = selected(state, 'assets', 'request_id', request['id'])
        if request['status'] == 'Borrowed':
            require(assets and all(a['handed_at'] and not a['returned_at'] for a in assets),
                    f'Borrowed request {request["id"]} has incorrect physical state.')
        elif request['status'] == 'Partially Returned':
            require(any(a['returned_at'] for a in assets) and any(a['handed_at'] and not a['returned_at'] for a in assets),
                    f'Partial-return request {request["id"]} is not partially returned.')
        elif request['status'] == 'Returned':
            require(assets and all(a['returned_at'] for a in assets), 'Returned request has outstanding units.')
        elif request['status'] == 'Pending Approval':
            require(not assets, 'Pending equipment request holds inventory.')
        elif request['status'] == 'Cancelled':
            require(all(a['released'] and a['handed_at'] is None for a in assets),
                    'Cancelled uncollected request holds inventory or lost a physical loan.')
    for queue in state['waiting']:
        if queue['status'] in {'Pending Review', 'Preapproved'}:
            if queue['room_request_id'] is not None:
                require(not selected(state, 'roomReservations', 'request_id', queue['room_request_id']),
                        'Preapproved room queue incorrectly holds a reservation.')
            else:
                require(not selected(state, 'assets', 'request_id', queue['borrow_request_id']),
                        'Preapproved equipment queue incorrectly holds inventory.')
        elif queue['status'] == 'Assigned':
            if queue['room_request_id'] is not None:
                require(one(state['rooms'], 'id', queue['room_request_id'])['status'] in {'Confirmed','Cancelled'},
                        'Recorded room assignment has an unexpected parent state.')
            else:
                require(one(state['equipment'], 'id', queue['borrow_request_id'])['status'] in {'Approved','Borrowed','Partially Returned','Returned','Cancelled'},
                        'Recorded equipment assignment has an unexpected parent state.')
    for report in state['feedback']:
        events = selected(state, 'feedbackEvents', 'report_id', report['id'])
        require([row['revision'] for row in events] == list(range(1, report['revision'] + 1)),
                f'Feedback {report["id"]} has incomplete persisted history.')
    counts = Counter(row['recipient_id'] for row in state['notificationReadStates'])
    read = Counter(row['recipient_id'] for row in state['notificationReadStates'] if row['read_at'] is not None)
    require({row['recipient_id']:row['total'] for row in state['notifications']} == dict(counts),
            'Notification total does not match persisted per-ID records.')
    require(all(row['read'] == read[row['recipient_id']] for row in state['notifications']),
            'Notification read count differs from persisted read_at records.')


def check_post(record):
    path, status = record['path'], record['status']
    before, after = record['before'], record['persisted']
    changed = {key for key in before if before[key] != after[key]}
    for state in (before, after):
        invariant(state)
    if status >= 400:
        require(status in {400,401,403,404,409,503}, f'Unexpected HTTP error {status} at {path}.')
        require(status != 401 or path == '/login', f'Unexpected HTTP 401 outside login: {path}.')
        require(not changed, f'Rejected POST {path} committed changes: {sorted(changed)}.')
        return 'rejected: no captured domain or notification changes'
    require(200 <= status < 400, f'Unexpected POST HTTP status {status}.')
    if path in {'/login','/logout','/appointments/times','/rooms/candidates'} or (path == '/equipment/catalog' and status == 200):
        require(not changed, f'Read-only/session POST {path} changed domain rows: {sorted(changed)}.')
        return 'session action or recommendations: domain rows unchanged'
    allowed = set(NOTIFICATIONS)
    target = re.fullmatch(r'/appointments/(\d+)/(decision|reschedule|cancel|decline-invitation)', path)
    if path == '/appointments/new':
        allowed |= {'appointments','professors','invitations'}
        new = [row for row in after['appointments'] if row['id'] not in {r['id'] for r in before['appointments']}]
        require(len(new) == 1 and new[0]['status'] == 'Pending Approval' and new[0]['revision'] == 1,
                'Appointment submission did not create exactly one pending revision.')
        require(not selected(after,'commitments','appointment_id',new[0]['id']), 'Submission prematurely reserves an appointment.')
    elif target:
        key, action = int(target[1]), target[2]
        old, new = one(before['appointments'],'id',key), one(after['appointments'],'id',key)
        allowed |= {'appointments','professors','commitments'} if action != 'decline-invitation' else {'invitations'}
        if action == 'decision':
            previous = selected(before,'professors','appointment_id',key)
            decisions = selected(after,'professors','appointment_id',key)
            require(len(additions(previous,decisions)) == 1, 'Professor decision did not persist exactly one decision.')
            require(old['revision'] == new['revision'], 'Professor decision changed material revision.')
            require(new['status'] in {'Pending Approval','Confirmed','Declined'}, 'Unexpected professor decision outcome.')
        elif action == 'reschedule':
            require(new['status'] == 'Pending Approval' and new['revision'] == old['revision'] + 1,
                    'Reschedule did not create a pending revision.')
            require(new['start_at'] != old['start_at'] and new['end_at'] != old['end_at'], 'Reschedule failed to persist a changed interval.')
            require(all(row['decision'] == 'Pending' and row['revision'] == new['revision']
                        for row in selected(after,'professors','appointment_id',key)), 'Reschedule retained approvals.')
            require(not selected(after,'commitments','appointment_id',key), 'Reschedule retained old commitments.')
        elif action == 'cancel':
            require(new['status'] == 'Cancelled' and new['revision'] == old['revision'], 'Cancellation state did not persist.')
            require(not selected(after,'commitments','appointment_id',key), 'Cancelled appointment retained commitments.')
        else:
            require(new == old and before['commitments'] == after['commitments'], 'Optional decline changed mandatory booking.')
            additions_ = additions(before['invitations'],after['invitations'])
            require(len(additions_) == 1 and additions_[0]['appointment_id'] == key and additions_[0]['status'] == 'Declined',
                    'Optional invitation decline did not persist.')
    elif path == '/rooms/new':
        allowed |= {'rooms','waiting','series','occurrences','roomInvitations'}
        new = [row for row in after['rooms'] if row['id'] not in {r['id'] for r in before['rooms']}]
        require(len(new) == 1 and new[0]['status'] == 'Pending Faculty Approval', 'Room submission did not persist a pending request.')
        require(not selected(after,'roomReservations','request_id',new[0]['id']), 'Room submission prematurely reserves a room.')
    elif (match := re.fullmatch(r'/rooms/(\d+)/(revise|cancel|decision)',path)):
        key, action = int(match[1]), match[2]
        old, new = one(before['rooms'],'id',key), one(after['rooms'],'id',key)
        allowed |= {'rooms','roomReservations','waiting','occurrences','roomInvitations'}
        if action == 'revise':
            require(new['revision'] == old['revision'] + 1 and new['status'] == 'Pending Faculty Approval', 'Room revision did not reset approval.')
            require(new['approved_revision'] is None and new['approved_by'] is None, 'Revised room request retains approval.')
        elif action == 'cancel':
            require(new['status'] == 'Cancelled', 'Room cancellation did not persist.')
            require(not selected(after,'roomReservations','request_id',key), 'Cancelled room retains reservations.')
        else:
            require(new['status'] in {'Confirmed','Rejected','Needs Revision'}, 'Room decision did not persist.')
    elif (match := re.fullmatch(r'/rooms/(\d+)/invitation',path)):
        key = int(match[1])
        allowed |= {'roomInvitations'}
        edited = additions(before['roomInvitations'],after['roomInvitations'])
        require(len(edited) == 1 and edited[0]['request_id'] == key and edited[0]['status'] in {'Accepted','Declined'},
                'Room professor invitation response did not persist.')
        require(one(before['rooms'],'id',key) == one(after['rooms'],'id',key), 'Optional response changed the room approval.')
    elif (match := re.fullmatch(r'/rooms/(\d+)/occurrences/(\d+)/cancel',path)):
        key, occurrence = int(match[1]), int(match[2])
        allowed |= {'rooms','roomReservations','waiting','occurrences'}
        require(one(after['occurrences'],'id',occurrence)['status'] == 'Cancelled', 'Occurrence cancellation did not persist.')
        require(not selected(after,'roomReservations','occurrence_id',occurrence), 'Cancelled occurrence retains a reservation.')
        series = one(after['series'],'id',one(after['occurrences'],'id',occurrence)['series_id'])
        require(series['room_request_id'] == key, 'Cancelled occurrence belongs to another room request.')
    elif path == '/equipment/catalog':
        allowed |= {'equipment','waiting','series','occurrences'}
        new = [row for row in after['equipment'] if row['id'] not in {r['id'] for r in before['equipment']}]
        require(len(new) == 1 and new[0]['status'] == 'Pending Approval', 'Equipment submission failed to create one pending request.')
        require(not selected(after,'assets','request_id',new[0]['id']), 'Pending equipment submission reserves assets.')
    elif (match := re.fullmatch(r'/equipment/(\d+)/([\w-]+)',path)):
        key, action = int(match[1]), match[2]
        old, new = one(before['equipment'],'id',key), one(after['equipment'],'id',key)
        prior_assets = selected(before,'assets','request_id',key)
        assets = selected(after,'assets','request_id',key)
        allowed |= {'equipment','assets','extensions','occurrences','waiting'}
        if action in {'cancel','cancel-occurrence'}:
            require(new['status'] == 'Cancelled' or 'occurrences' in changed, 'Equipment cancellation did not persist.')
            require(all(not row['handed_at'] or not row['released'] or row['returned_at'] for row in assets),
                    'Cancellation incorrectly released collected equipment.')
        elif action == 'handover':
            handed = [row for row in assets if row['handed_at'] and not one(prior_assets,'id',row['id'])['handed_at']]
            require(handed and new['status'] in {'Borrowed','Partially Returned'}, 'Physical handover did not persist collection.')
            require(all(row['returned_at'] is None and not row['released'] for row in handed), 'Handover incorrectly released assets.')
        elif action == 'intend-return':
            require(old == new and prior_assets == assets, 'Return intent changed physical inventory or due/status.')
        elif action == 'return':
            returned = [row for row in assets if row['returned_at'] and not one(prior_assets,'id',row['id'])['returned_at']]
            require(returned and all(row['released'] for row in returned), 'Tested usable inspection did not persist physical return.')
            require(new['status'] in {'Partially Returned','Returned'}, 'Return status did not reflect returned units.')
        elif action == 'extension':
            added = additions(before['extensions'],after['extensions'])
            require(len(added) == 1 and added[0]['request_id'] == key and added[0]['status'] == 'Pending', 'Extension request did not persist.')
            require(new == old and prior_assets == assets, 'Extension request prematurely changed the due date or inventory.')
        elif action in {'approve-extension','reject-extension'}:
            edited = additions(before['extensions'],after['extensions'])
            require(len(edited) == 1 and edited[0]['request_id'] == key, 'Extension decision did not persist.')
            require(edited[0]['status'] == ('Approved' if action == 'approve-extension' else 'Rejected'), 'Wrong extension decision saved.')
            if action == 'approve-extension':
                outstanding = [row for row in assets if row['handed_at'] and not row['returned_at']]
                require(outstanding and all(row['due_at'] == edited[0]['due_at'] for row in outstanding), 'Approved extension failed to update outstanding assets.')
                if not any(row['borrow_request_id'] == key for row in after['series']):
                    require(new['due_at'] == edited[0]['due_at'], 'Approved extension failed to update parent due date.')
            else:
                require(new == old and prior_assets == assets, 'Rejected extension changed the loan.')
        elif action in {'approve','reject','decision'}:
            require(new['status'] in {'Approved','Rejected'}, 'Custodian decision did not persist.')
        else:
            raise AssertionError('Unverified equipment operation: '+action)
    elif (match := re.fullmatch(r'/waiting-lists/(\d+)/(review|cancel)',path)):
        key, action = int(match[1]), match[2]
        new = one(after['waiting'],'id',key)
        allowed |= {'waiting','rooms','equipment','roomReservations','assets','occurrences'}
        if action == 'cancel':
            require(new['status'] == 'Cancelled', 'Queue withdrawal did not persist.')
            parent = one(after['rooms'] if new['room_request_id'] else after['equipment'],'id',new['room_request_id'] or new['borrow_request_id'])
            require(parent['status'] == 'Cancelled', 'Queue withdrawal did not cancel its pending parent.')
        else:
            require(new['status'] in {'Preapproved','Assigned','Rejected'}, 'Queue review did not persist.')
            if new['status'] in {'Preapproved','Assigned'}:
                require(new['approved_by'] is not None, 'Queue preapproval lacks reviewer.')
    elif path == '/waiting-lists/refresh':
        allowed |= {'waiting','rooms','equipment','roomReservations','assets','occurrences'}
    elif re.fullmatch(r'/feedback/new/(room|equipment)/\d+',path):
        allowed |= {'feedback','feedbackEvents'}
        added = [row for row in after['feedback'] if row['id'] not in {r['id'] for r in before['feedback']}]
        require(len(added) == 1 and added[0]['status'] == 'Submitted' and added[0]['revision'] == 1, 'Feedback submission did not persist.')
    elif (match := re.fullmatch(r'/feedback/(\d+)/update',path)):
        allowed |= {'feedback','feedbackEvents'}
        key = int(match[1])
        old, new = one(before['feedback'],'id',key), one(after['feedback'],'id',key)
        require(new['revision'] == old['revision'] + 1 and new['description'] == old['description'], 'Feedback update changed original report or lost revision.')
        events = additions(before['feedbackEvents'],after['feedbackEvents'])
        require(len(events) == 1 and events[0]['report_id'] == key and events[0]['revision'] == new['revision'], 'Feedback update lacks persisted history.')
        if events[0]['message'].startswith('Reporter clarification: '):
            require(new['status'] == old['status'] and new['response'] == old['response'], 'Clarification changed staff response/status.')
        else:
            require(new['response'] and new['status'] in {'Under Review','Resolved','Closed'}, 'Staff response did not persist.')
    elif path == '/appointments/calendar':
        allowed |= {'blocks'}
        added, removed = additions(before['blocks'],after['blocks']), additions(after['blocks'],before['blocks'])
        require((len(added),len(removed)) in {(1,0),(0,1)}, 'Personal block action did not persist exactly one add/removal.')
    elif path == '/notifications/read':
        for old in before['notificationReadStates']:
            new = one(after['notificationReadStates'],'id',old['id'])
            require(new['recipient_id'] == old['recipient_id'] and (old['read_at'] is None or old['read_at'] == new['read_at']),
                    'Read operation changed ownership or rewrote an existing read timestamp.')
        require(len(before['notificationReadStates']) == len(after['notificationReadStates']), 'Read operation created/deleted notifications.')
    else:
        raise AssertionError('Unverified successful POST endpoint: '+path)
    require(changed <= allowed, f'{path} changed unrelated captured tables: {sorted(changed-allowed)}.')
    if path not in {'/notifications/read','/waiting-lists/refresh','/appointments/calendar'}:
        require(total_notifications(after) > total_notifications(before), f'{path} did not persist its expected notification.')
    return 'expected committed mutation: '+', '.join(sorted(changed))


def verify_lifecycles(records, final):
    for n, professors, invitees in [(0,{2},set()),(1,{2,3},set()),(2,{2},{4,5}),(3,{2,3},{4,5})]:
        row = one(final['appointments'],'purpose',f'UI10 participant combination {n}')
        key = row['id']
        require(row['status'] == 'Cancelled' and row['revision'] == 2, 'Combination did not finish cancelled after reschedule.')
        require({r['user_id'] for r in selected(final,'professors','appointment_id',key)} == professors, 'Wrong required-professor combination persisted.')
        require({r['user_id'] for r in selected(final,'invitations','appointment_id',key)} == invitees, 'Wrong optional-student combination persisted.')
        confirmed = [r['persisted'] for r in records
                     if any(a['id'] == key and a['status'] == 'Confirmed' for a in r['persisted']['appointments'])]
        require(confirmed, f'Combination {n} never committed confirmation.')
        for state in confirmed:
            require({r['user_id'] for r in selected(state,'commitments','appointment_id',key)} == {1}|professors,
                    f'Combination {n} did not reserve exactly mandatory participants.')
        require(any(r['path'] == f'/appointments/{key}/reschedule' and r['status'] == 302 for r in records), 'Missing real reschedule POST.')
        if invitees:
            require(one(selected(final,'invitations','appointment_id',key),'user_id',4)['status'] == 'Declined', 'Invited student decline did not persist.')
    rejected = one(final['appointments'],'purpose','UI10 participant combination 4')
    require(rejected['status'] == 'Declined' and not selected(final,'commitments','appointment_id',rejected['id']), 'Professor rejection did not remain unreserved.')
    loan = one(final['equipment'],'purpose','Fictional UI10 physical collection')
    key = loan['id']
    require(loan['status'] == 'Returned', 'Physical loan did not finish returned.')
    assets = selected(final,'assets','request_id',key)
    require(len(assets) == 2 and all(row['handed_at'] and row['returned_at'] and row['released'] for row in assets), 'Both physically collected units were not returned/released.')
    require(any(row['request_id'] == key and row['status'] == 'Approved' for row in final['extensions']), 'Physical loan extension was not approved.')
    stages = {one(r['persisted']['equipment'],'id',key)['status'] for r in records}
    require({'Approved','Borrowed','Partially Returned','Returned'} <= stages, 'Physical lifecycle missed collection/partial/full return stage.')
    room = one(final['rooms'],'purpose','UI10 approved room with participants')
    require(room['status'] == 'Cancelled', 'Approved participant room did not finish cancelled.')
    invitations = selected(final,'roomInvitations','request_id',room['id'])
    require({(r['user_id'],r['status']) for r in invitations} == {(4,'Accepted'),(2,'Accepted')},
            'Registered student participant or accepted professor response missing from database.')
    require(any(any(r['id'] == room['id'] and r['status'] == 'Confirmed' for r in p['persisted']['rooms']) for p in records),
            'Participant room never committed faculty confirmation.')
    for mode in ('partial','all'):
        room = one(final['rooms'],'purpose','UI10 recurring room '+mode)
        series = one(final['series'],'room_request_id',room['id'])
        require(series['approval_mode'] == mode, 'Recurring approval consent mode changed.')
        occurrences = selected(final,'occurrences','series_id',series['id'])
        expected = ['Cancelled','Rejected'] if mode == 'partial' else ['Cancelled','Cancelled']
        require(sorted(o['status'] for o in occurrences) == expected, 'Recurring room decisions/cancellation did not persist per date.')
        successful = [p for p in records if p['path'] == f'/rooms/{room["id"]}/decision' and p['status'] == 302]
        require(len(successful) == (2 if mode == 'partial' else 1), 'Recurring room approval/rejection POSTs incomplete.')
        approved = selected(successful[0]['persisted'],'occurrences','series_id',series['id'])
        require(sum(o['status'] == 'Reserved' for o in approved) == (1 if mode == 'partial' else 2),
                'Partial/all date approval reserved the wrong number of occurrences.')


def verify_workflow_completion(name, pair, records):
    """A valid partial run must not satisfy the intended full workflow gate."""
    before, final = pair['before'], pair['after']
    def posted(pattern, status=None):
        return sum(bool(re.fullmatch(pattern,row['path'])) and (status is None or row['status'] == status) for row in records)
    if name == 'lifecycles':
        verify_lifecycles(records,final)
    elif name == 'UI-03':
        created = one(final['appointments'],'purpose','Fictional browser appointment acceptance')
        require(created['status'] == 'Cancelled' and created['revision'] == 2, 'Appointment workflow did not finish cancel after revision.')
        require(posted(r'/appointments/\d+/reschedule',302) >= 2 and posted(r'/appointments/\d+/decline-invitation',302) >= 1,
                'Appointment workflow missed reset of existing approval or optional decline.')
        require(posted('/appointments/new',409) >= 1, 'Appointment workflow missed invalid-time rejection.')
    elif name == 'UI-04':
        created = one(final['rooms'],'purpose','Fictional browser room revised')
        require(created['status'] == 'Cancelled' and created['revision'] == 2, 'Room workflow did not finish revised cancellation.')
        require({(r['user_id'],r['status'],r['revision']) for r in selected(final,'roomInvitations','request_id',created['id'])}
                == {(4,'Accepted',2),(2,'Invited',2)}, 'Room revision lost its registered student or optional professor.')
        require(posted(r'/rooms/\d+/occurrences/\d+/cancel',302) == 1, 'Room workflow missed its individual recurring cancellation.')
        require(any(o['status'] == 'Cancelled' for o in final['occurrences']) and any(o['status'] == 'Reserved' for o in final['occurrences']),
                'Occurrence action failed to retain other reserved dates.')
    elif name == 'UI-05':
        created = [row for row in final['equipment'] if row['id'] not in {r['id'] for r in before['equipment']}]
        require(len(created) == 2 and all(row['status'] == 'Cancelled' for row in created), 'Equipment workflow did not submit/cancel both one-time and recurring requests.')
        require(posted(r'/equipment/\d+/handover',403) == 1 and posted(r'/equipment/\d+/return',403) == 1,
                'Equipment workflow missed custody permission negatives.')
        require(posted(r'/equipment/\d+/intend-return',302) == 1 and any(e['status'] == 'Pending' for e in final['extensions']),
                'Equipment workflow missed return intent or pending extension.')
    elif name == 'UI-06':
        require(any(row['status'] == 'Cancelled' for row in final['waiting']), 'Waiting workflow did not withdraw its original queue.')
        assigned = [row for row in final['waiting'] if row['id'] not in {r['id'] for r in before['waiting']}]
        require(len(assigned) == 1 and assigned[0]['status'] == 'Assigned', 'Waiting workflow did not persist its new assignment.')
        require(one(final['rooms'],'id',assigned[0]['room_request_id'])['status'] == 'Confirmed', 'New queue assignment did not confirm the actual room.')
        require(posted('/waiting-lists/refresh',302) == 1 and posted(r'/waiting-lists/\d+/review',403) == 1,
                'Waiting workflow missed recheck or unauthorized review.')
    elif name == 'UI-07':
        created = [row for row in final['feedback'] if row['id'] not in {r['id'] for r in before['feedback']}]
        require(len(created) == 1 and created[0]['status'] == 'Resolved' and created[0]['revision'] == 4,
                'Feedback workflow did not persist submission, clarification, staff review and resolution.')
        events = selected(final,'feedbackEvents','report_id',created[0]['id'])
        require(any(e['message'].startswith('Reporter clarification: ') for e in events), 'Reporter clarification is missing from database history.')
        require(posted(r'/feedback/\d+/update',403) == 1, 'Feedback workflow missed rejected reporter staff action.')
    elif name == 'UI-08':
        require(before['blocks'] == final['blocks'] and posted('/appointments/calendar',302) == 2,
                'Personal block workflow did not create and remove its block while preserving existing blocks.')
        require(posted('/appointments/calendar',409) >= 1 and posted('/notifications/read',403) >= 1,
                'Calendar/inbox workflow missed conflict or private-read rejection.')
        owner = one(final['notifications'],'recipient_id',1)
        require(owner['read'] == owner['total'] and posted('/notifications/read') >= 3, 'Individual/all notification reads did not persist.')
        for record in records:
            if record['path'] == '/notifications/read' and record['status'] < 400:
                changed_reads = additions(record['before']['notificationReadStates'],record['persisted']['notificationReadStates'])
                require(changed_reads and all(row['recipient_id'] == 1 for row in changed_reads),
                        'Student read action did not affect only that student\'s actual notifications.')
    elif name == 'authorization':
        require(posted('/login',401) == 1 and posted('/login',400) >= 1, 'Authentication negatives are missing.')
        require(sum(row['status'] == 403 for row in records) >= 30 and sum(row['status'] == 409 for row in records) >= 3,
                'Cross-user/role/stale-state negative coverage is incomplete.')
        require(all(row['path'] in {'/login','/logout'} for row in records if row['status'] < 400),
                'Authorization-negative run unexpectedly succeeded at a resource action.')
        require(before == final, 'Authorization-negative run changed captured domain or notification rows.')
    elif name == 'loading':
        require(posted('/appointments/times',200) >= 1 and posted('/rooms/candidates',200) >= 1,
                'Loading audit did not execute both actual recommendation endpoints.')
        require(before == final, 'Loading/recommendation audit changed captured domain state.')
    elif name == 'browser':
        require(sum(row['status'] == 400 for row in records) >= 20, 'Browser sweep did not execute expected CSRF-negative forms.')
    elif name == 'equipment-lifecycles':
        approved = one(final['equipment'],'purpose','UI10 equipment approval then cancellation')
        require(approved['status'] == 'Cancelled', 'Approved one-time equipment request was not cancelled.')
        assets = selected(final,'assets','request_id',approved['id'])
        require(len(assets) == 1 and assets[0]['released'] and assets[0]['handed_at'] is None,
                'Approved then cancelled request did not release its uncollected asset.')
        require(any(any(r['id'] == approved['id'] and r['status'] == 'Approved' for r in p['persisted']['equipment']) for p in records),
                'One-time equipment request never committed custodian approval.')
        rejected = one(final['equipment'],'purpose','UI10 equipment rejection')
        require(rejected['status'] == 'Rejected' and not selected(final,'assets','request_id',rejected['id']),
                'Rejected equipment request retained inventory or lacks rejection.')
        recurring = one(final['equipment'],'purpose','UI10 recurring equipment partial decisions')
        series = one(final['series'],'borrow_request_id',recurring['id'])
        occurrences = selected(final,'occurrences','series_id',series['id'])
        require(series['approval_mode'] == 'partial' and sorted(o['status'] for o in occurrences) == ['Cancelled','Rejected'],
                'Recurring equipment partial decisions/cancellation did not persist by date.')
        decisions = [p for p in records if p['path'] == f'/equipment/{recurring["id"]}/decision' and p['status'] == 302]
        require(len(decisions) == 2, 'Recurring equipment approval/rejection POST coverage incomplete.')
        require(sorted(o['status'] for o in selected(decisions[0]['persisted'],'occurrences','series_id',series['id'])) == ['Proposed','Reserved'],
                'Selected equipment approval reserved the wrong dates.')
        require(sorted(o['status'] for o in selected(decisions[1]['persisted'],'occurrences','series_id',series['id'])) == ['Rejected','Reserved'],
                'Selected equipment rejection changed the already approved date.')
        blocker = one(final['equipment'],'purpose','UI10 equipment waiting blocker')
        require(blocker['status'] == 'Cancelled', 'Equipment shortage blocker was not cancelled.')
        reserved = selected(final,'assets','request_id',blocker['id'])
        require(len(reserved) == 3 and all(a['released'] and not a['handed_at'] for a in reserved),
                'Blocking complete quantity was not reserved and subsequently released.')
        assigned = one(final['equipment'],'purpose','UI10 equipment queue assignment')
        queue = one(final['waiting'],'borrow_request_id',assigned['id'])
        require(queue['status'] == 'Assigned' and queue['approved_by'] == 7 and assigned['status'] == 'Approved',
                'Equipment queue did not commit preapproved complete assignment.')
        assigned_assets = selected(final,'assets','request_id',assigned['id'])
        require(len(assigned_assets) == 1 and not assigned_assets[0]['released'] and assigned_assets[0]['handed_at'] is None,
                'Assigned equipment does not await physical collection with its reserved asset.')
        overdue_units = {a['unit_id'] for a in before['assets'] if a['handed_at'] and not a['returned_at']}
        require(assigned_assets[0]['unit_id'] not in overdue_units, 'Queue assignment reused an outstanding physically borrowed asset.')
        preapproved = [p['persisted'] for p in records
                       if any(q['id'] == queue['id'] and q['status'] == 'Preapproved' for q in p['persisted']['waiting'])]
        require(preapproved and all(not selected(p,'assets','request_id',assigned['id']) for p in preapproved),
                'Equipment queue preapproval incorrectly reserved inventory or was never committed.')


def verify_directory(directory):
    inputs = {name:(directory/name).read_bytes() for name in ('persistence.json','post-states.json')}
    pair = json.loads(inputs['persistence.json'])
    records = json.loads(inputs['post-states.json'])
    require(records, 'No actual POST evidence.')
    require(ENRICHED <= set(pair['before']) and all(isinstance(row.get('before'),dict) for row in records),
            'Stale projection: rerun with enriched snapshots and per-POST before state.')
    invariant(pair['before']); invariant(pair['after'])
    operations=[]
    for index, record in enumerate(records):
        try:
            detail = check_post(record)
        except AssertionError as error:
            raise AssertionError(f'POST {index} {record["path"]} HTTP {record["status"]}: {error}') from error
        operations.append(dict(index=index,path=record['path'],status=record['status'],verification=detail))
    # A subsequent GET may refresh queue/overdue notifications. Domain mutations
    # remain checked by each POST's immediate before/after transaction pair.
    final_get_changes=sorted(k for k in pair['after'] if pair['after'][k] != records[-1]['persisted'][k])
    verify_workflow_completion(directory.name,pair,records)
    return dict(posts=len(records),successful=sum(r['status']<400 for r in records),
                rejected=sum(r['status']>=400 for r in records),operations=operations,
                inputSha256={name:hashlib.sha256(data).hexdigest() for name,data in inputs.items()},
                changesAfterLastPost=final_get_changes)


def main():
    requested = REQUIRED
    reports, missing, failures = {}, [], []
    for name in requested:
        directory = OUTPUT/name
        if not all((directory/file).is_file() for file in ('persistence.json','post-states.json')):
            missing.append(name)
            continue
        try:
            reports[name] = verify_directory(directory)
        except (AssertionError,KeyError,ValueError) as error:
            failures.append(dict(group=name,error=str(error)))
    report = dict(status='PASS' if not missing and not failures else 'CHANGES REQUIRED' if failures else 'INCOMPLETE',
        required=requested,missing=missing,failures=failures,groups=reports,
        posts=sum(r['posts'] for r in reports.values()),successful=sum(r['successful'] for r in reports.values()),
        rejected=sum(r['rejected'] for r in reports.values()),
        scope='Captured committed domain rows and notifications; authentication internals, exact participant authorization and calendar display are covered separately by live browser and service regressions.')
    if not missing:
        (OUTPUT/'persistence-verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='groups'},indent=2))
    return 1 if failures else 2 if missing else 0


if __name__ == '__main__':
    sys.exit(main())
