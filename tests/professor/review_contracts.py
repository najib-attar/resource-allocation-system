"""Reproduce reviewed contract gaps and source/Git evidence, without changing policy."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'tests'),str(ROOT)]
from test_professor_services import ProfessorFixture
from web.persistence.models import ApplicationState, Notification, ResourceRequest


def git(directory, *args):
    return subprocess.check_output(['git',*args],cwd=directory,text=True,encoding='utf-8').strip()


def main():
    output = ROOT/'docs/professor-services'
    output.mkdir(parents=True,exist_ok=True)
    fixture = ProfessorFixture()
    try:
        fixture.setUp()
        key = fixture.academic_request()
        pending = fixture.professors.detail(2,key)['item']['status']
        run_id,snapshot = fixture.repository.start_run()
        included = key in {row['id'] for row in snapshot['requests']}
        fixture.repository.fail_run(run_id,'Review-only snapshot proof; engine deliberately not invoked.')
        with fixture.database.transaction(read_only=True) as session:
            active = session.get(ApplicationState,1).active_run_id
        report = dict(requestStatus=pending,includedInAdministrativeEngineSnapshot=included,
            activePublication=active,engineInvoked=False,
            resourceRequestColumns=list(ResourceRequest.__table__.columns.keys()),
            notificationSourceColumns=[c for c in Notification.__table__.columns.keys() if c.endswith('_event_id')],
            conclusion='No administrative eligibility gate; professor intake must remain disabled.',
            unchangedSourceHash=hashlib.sha256((ROOT/'web/persistence/repository.py').read_bytes()).hexdigest())
        assert pending=='Pending' and included and active is None
        (output/'approval-gate-evidence.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    finally:
        if not fixture.doCleanups():
            raise RuntimeError('Contract fixture cleanup failed.')
    # Only the newly introduced Python code; valid existing tests/code are retained.
    sources = [ROOT/'web/professor_routes.py',ROOT/'web/professor_service.py',
               ROOT/'tests/test_professor_services.py',ROOT/'tests/test_professor_existing_workflows.py',
               *sorted((ROOT/'tests/professor').glob('*.py'))]
    python = []
    for path in sources:
        source = path.read_text(encoding='utf-8')
        tree = ast.parse(source)
        names = {n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}
        imported = {a.asname or a.name.split('.')[0] for n in ast.walk(tree)
                    if isinstance(n,(ast.Import,ast.ImportFrom)) for a in n.names}
        unused = sorted(imported-names)
        assert not unused,(str(path),unused)
        python.append(dict(path=path.relative_to(ROOT).as_posix(),parsed=True,unusedImports=unused))
    methods = {n.name for path in (ROOT/'tests').glob('test_*.py')
               for n in ast.walk(ast.parse(path.read_text(encoding='utf-8'))) if isinstance(n,ast.FunctionDef)}
    import re
    references = set(re.findall(r'`(test_[A-Za-z0-9_]+)`',(output/'traceability.md').read_text(encoding='utf-8')))
    missing = sorted(r for r in references if r not in methods and not (ROOT/'tests'/(r+'.py')).exists())
    assert not missing,missing
    student = Path('C:/Users/najee/Desktop/resource-allocation-frontend')
    base = '747c925b14c29368e6cb9bc8b2e2d9d33c494462'
    assert git(student,'rev-parse','HEAD')==base and not git(student,'status','--porcelain')
    assert git(ROOT,'branch','--show-current')=='codex/professor-services-v1'
    assert not git(ROOT,'diff',base,'--','src','web/persistence','web/appointment_service.py',
                   'web/room_request_service.py','web/account_service.py','web/university_calendar.py')
    archive = Path('C:/Users/najee/Downloads/professor_use_cases_handoff.zip')
    integrity = []
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            if member.is_dir():
                continue
            path = ROOT/member.filename
            content = package.read(member)
            assert path.read_bytes()==content,member.filename
            integrity.append(dict(path=member.filename,sha256=hashlib.sha256(content).hexdigest()))
    (output/'source-review.json').write_text(json.dumps(dict(python=python,
        referencedRegressionMethodsValidated=len(references),missingTestReferences=missing,
        preservedStudentHead=base,studentClean=True,professorBranch='codex/professor-services-v1',
        unchangedProtectedSources=True,handoffIntegrity=integrity),indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(approvalGate='missing; intake blocked',pythonSources=len(python),
                         testReferences=len(references),handoffFiles=len(integrity))))


if __name__=='__main__':
    main()
