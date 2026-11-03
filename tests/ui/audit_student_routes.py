"""Inventory every route and preserve the original student form contracts."""
import csv
import io
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from web.app import app

PHASES = {
    'student.home':'UI-01', 'login':'UI-02', 'logout':'UI-02', 'index':'UI-01 / role redirect',
    **dict.fromkeys(['appointments.'+x for x in ['index','new','times','detail','decision','cancel','reschedule','decline']], 'UI-03'),
    **dict.fromkeys(['rooms.'+x for x in ['index','availability','new','candidates','detail','revise','decision','cancel','cancel_occurrence','invitation','configuration']], 'UI-04'),
    **dict.fromkeys(['equipment.'+x for x in ['index','catalog','detail','transition','inventory','custodians']], 'UI-05'),
    **dict.fromkeys(['waiting.'+x for x in ['index','policy','detail','review','cancel','refresh','priority','configuration']], 'UI-06'),
    **dict.fromkeys(['feedback.'+x for x in ['index','new','detail','update']], 'UI-07'),
    **dict.fromkeys(['calendar.'+x for x in ['index','academic','publications']], 'UI-08'),
    **dict.fromkeys(['notifications.'+x for x in ['index','feed','read']], 'UI-08'),
    'appointments.calendar':'UI-08', 'appointments.availability':'Future student browsing / professor management only',
    'appointments.bindings':'Administration only',
}
RESTRICTED = {
    'appointments.decision':'Required professor only',
    'appointments.availability':'Professor office-hours management; student denied',
    'appointments.bindings':'Administration only',
    'rooms.decision':'Assigned faculty approver only',
    'rooms.invitation':'Invited professor response only',
    'rooms.configuration':'Authorized resource management only',
    'equipment.inventory':'Current owning-faculty custodian only',
    'equipment.custodians':'Administration only',
    'waiting.review':'Current responsible faculty/custodian only',
    'waiting.priority':'Authorized current resource responsibility only',
    'waiting.configuration':'Administration only',
    'calendar.publications':'Administration only',
}


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, check=True).stdout.decode('utf-8')


def main():
    output = ROOT / 'docs/ui/student-portal/UI-09'
    output.mkdir(parents=True, exist_ok=True)
    routes = []
    prefixes = ('student.','appointments.','rooms.','equipment.','waiting.','feedback.','calendar.','notifications.')
    for rule in sorted(app.url_map.iter_rules(), key=lambda r:r.rule):
        if rule.endpoint.startswith(prefixes) and rule.endpoint not in PHASES:
            raise RuntimeError('Unaccounted service route: '+rule.endpoint)
        routes.append(dict(route=rule.rule, methods=','.join(sorted(rule.methods-{'HEAD','OPTIONS'})),
            endpoint=rule.endpoint, phase=PHASES.get(rule.endpoint, 'Existing administration / static asset'),
            audience=RESTRICTED.get(rule.endpoint, 'Session-scoped student capability; service guards remain authoritative'
                if rule.endpoint in PHASES else 'Existing administration / static asset')))
    assert not any(r['route'] in {'/activity','/my-activity'} for r in routes), 'Unsupported aggregate route'
    with (output/'routes.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=routes[0].keys())
        writer.writeheader(); writer.writerows(routes)
    changed = git('diff','--name-only','e01eba6','--','web/templates').splitlines()
    fields = []
    for name in changed:
        original = subprocess.run(['git','show','e01eba6:'+name], cwd=ROOT, capture_output=True)
        if original.returncode:
            continue
        pattern = r'<(?:input|select|textarea|button)\b[^>]*\bname="([^"]+)"'
        before = set(re.findall(pattern, original.stdout.decode('utf-8')))
        after = set(re.findall(pattern, (ROOT/name).read_text(encoding='utf-8')))
        missing = sorted(before-after)
        fields.append(dict(template=name, originalFieldNames=sorted(before), missingFieldNames=missing))
        if missing:
            raise RuntimeError(name+' lost fields: '+str(missing))
    protected = ['src','research/cdmcs','migrations','web/security.py','web/appointment_service.py',
        'web/room_request_service.py','web/equipment_service.py','web/waiting_list_service.py',
        'web/feedback_service.py','web/university_calendar.py','web/personal_schedule_service.py',
        'web/notification_service.py','web/persistence']
    untouched = not git('diff','--name-only','e01eba6','--',*protected).strip()
    if not untouched:
        raise RuntimeError('Protected backend/research paths changed')
    report = dict(totalRoutes=len(routes), accountedServiceRules=sum(r['endpoint'].startswith(prefixes) for r in routes),
                  originalFormContractsPreserved=True, templates=fields, protectedBackendAndResearchUnchanged=untouched)
    (output/'contracts.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    table = ['# Complete route inventory', '',
        'Generated from the running Flask route map. Service methods continue to enforce ownership, role, state and revision checks.', '',
        '| Route | Methods | Endpoint | Phase | Access |','|---|---|---|---|---|']
    table += ['| '+ ' | '.join(row[key] for key in ['route','methods','endpoint','phase','audience'])+' |' for row in routes]
    (output/'routes.md').write_text('\n'.join(table)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k != 'templates'}, indent=2))


if __name__ == '__main__':
    main()
