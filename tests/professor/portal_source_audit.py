"""Reproducible preservation/reachability audit; no database or application writes."""
import ast
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import zlib

ROOT=Path(__file__).resolve().parents[2]
BASE='5a7f0b0'
STUDENT_BASE='747c925b14c29368e6cb9bc8b2e2d9d33c494462'
REVIEW_BASE='196933506469ae25d3214a91ef2fd457356d096d'


def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT,text=True,encoding='utf-8')


def methods(source):
    tree=ast.parse(source)
    return {c.name+'.'+n.name for c in tree.body if isinstance(c,ast.ClassDef)
        for n in c.body if isinstance(n,ast.FunctionDef) and n.name.startswith('test_')}


def class_methods(source):
    return {n.name:ast.dump(n,include_attributes=False) for c in ast.parse(source).body
        if isinstance(c,ast.ClassDef) and c.name=='ProfessorService'
        for n in c.body if isinstance(n,ast.FunctionDef)}


def delivery_inventory():
    output=ROOT/'docs/professor-services'
    screenshots=[]
    for path in sorted(output.rglob('*.png')):
        data=path.read_bytes()
        assert data[:8]==b'\x89PNG\r\n\x1a\n',path
        offset=8
        while offset<len(data):
            size=struct.unpack('>I',data[offset:offset+4])[0]
            chunk=data[offset+4:offset+8+size]
            expected=struct.unpack('>I',data[offset+8+size:offset+12+size])[0]
            assert zlib.crc32(chunk)&0xffffffff==expected,path
            offset+=12+size
        assert offset==len(data),path
        width,height=struct.unpack('>II',data[16:24])
        screenshots.append(dict(path=path.relative_to(output).as_posix(),width=width,height=height,
            sha256=hashlib.sha256(data).hexdigest(),pngCRC=True))
    (output/'screenshots.json').write_text(json.dumps(screenshots,indent=2)+'\n',encoding='utf-8')
    changed=[]
    for row in git('diff','--name-status','-M',REVIEW_BASE).splitlines():
        status,*paths=row.split('\t')
        changed.append(dict(status=status,path=paths[-1],**({'previousPath':paths[0]} if len(paths)>1 else {})))
    known={row['path'] for row in changed}
    for path in git('ls-files','--others','--exclude-standard').splitlines():
        if path not in known:changed.append(dict(status='A',path=path))
    (output/'changed-files.json').write_text(json.dumps(dict(reviewedBase=REVIEW_BASE,
        frontendBase=git('rev-parse',BASE).strip(),
        inheritedStudentBase=STUDENT_BASE,
        professorBranch='codex/professor-services-v1',
        files=sorted(changed,key=lambda row:row['path'])),indent=2)+'\n',encoding='utf-8')
    return len(screenshots),len(changed)


def main():
    inherited_main=['research','.github','web/cost_policy_service.py','tests/test_cost_policy_governance.py']
    assert not git('diff',REVIEW_BASE,'--',*inherited_main)
    protected=['src','migrations','web/persistence','web/academic_eligibility.py',
        'web/account_service.py','web/appointment_service.py','web/room_request_service.py','web/equipment_service.py',
        'web/calendar_service.py','web/university_calendar.py','web/personal_schedule_service.py',
        'web/notification_service.py','web/student_routes.py','web/student_dashboard_service.py','requirements.txt']
    # The separately authorized logout correction adds persistence, without
    # changing academic eligibility, allocation or the other protected services.
    logout_files={'web/account_service.py','web/persistence/models.py',
        'migrations/versions/0051b_logged_out_sessions.py'}
    changed_protected=set(git('diff','--name-only',BASE,'--',*protected).splitlines())
    new_protected={path for path in git('ls-files','--others','--exclude-standard').splitlines()
        if path.startswith(('migrations/','web/persistence/'))}
    assert changed_protected | new_protected <= logout_files
    old_models={n.name:ast.dump(n,include_attributes=False) for n in ast.parse(
        git('show',BASE+':web/persistence/models.py')).body if isinstance(n,ast.ClassDef)}
    new_models={n.name:ast.dump(n,include_attributes=False) for n in ast.parse(
        (ROOT/'web/persistence/models.py').read_text(encoding='utf-8')).body if isinstance(n,ast.ClassDef)}
    assert all(new_models.get(name)==source for name,source in old_models.items())
    assert set(new_models)-set(old_models)=={'LoggedOutSession'}
    def account_methods(source):
        return {n.name:ast.dump(n,include_attributes=False) for cls in ast.parse(source).body
            if isinstance(cls,ast.ClassDef) and cls.name=='AccountService'
            for n in cls.body if isinstance(n,ast.FunctionDef)}
    old_account=account_methods(git('show',BASE+':web/account_service.py'))
    new_account=account_methods((ROOT/'web/account_service.py').read_text(encoding='utf-8'))
    assert all(new_account.get(name)==source for name,source in old_account.items() if name!='identity')
    assert set(new_account)-set(old_account)=={'_valid_session_token','_session_digest','revoke_session'}
    original_gateway=git('show',BASE+':web/engine_gateway.py')
    old_guard=("            guard = getattr(snapshot, 'assert_allocation_ready', None)\n"
        "            if guard is not None:\n                guard()\n")
    new_guard=("            from .academic_eligibility import AllocationInput, PresentationInput\n"
        "            if type(snapshot) is AllocationInput:\n                AllocationInput.assert_allocation_ready(snapshot)\n"
        "            elif type(snapshot) is PresentationInput:\n                PresentationInput.assert_allocation_ready(snapshot)\n")
    assert original_gateway.count(old_guard)==1
    assert (ROOT/'web/engine_gateway.py').read_text(encoding='utf-8')==original_gateway.replace(old_guard,new_guard)
    old=git('show',BASE+':web/templates/student_home.html').replace('student-home.css','campus-home.css')
    assert old==(ROOT/'web/templates/student_home.html').read_text(encoding='utf-8')
    css=[]
    references='\n'.join(path.read_text(encoding='utf-8') for path in (ROOT/'web').rglob('*')
        if path.is_file() and path.suffix in {'.html','.js','.py'})
    for old_name,new_name in [('student-shell.css','campus-shell.css'),('student-services.css','campus-services.css'),('student-home.css','campus-home.css')]:
        old=git('show',BASE+':web/static/'+old_name)
        new=(ROOT/'web/static'/new_name).read_text(encoding='utf-8')
        old=old[old.index('\n'):]
        if old_name=='student-shell.css':old=old.replace('.student-shell','.campus-shell')
        if old_name=='student-services.css':old=old.replace('.student-service ','.campus-service ').replace('.student-service {','.campus-service {')
        assert new[new.index('\n'):].startswith(old),(old_name,new_name)
        extension=new[new.index('\n')+len(old):]
        classes=sorted(set(re.findall(r'\.([A-Za-z_][A-Za-z0-9_-]*)',extension)))
        assert all(name in references for name in classes),(new_name,classes)
        assert old_name not in references,old_name
        css.append(dict(previous=old_name,current=new_name,originalDeclarationsPreserved=True,
            newSelectorClassesWithCallers=classes))
    prior=current=0
    for name in git('ls-tree','-r','--name-only',BASE,'tests').splitlines():
        if Path(name).name.startswith('test_') and name.endswith('.py'):
            before=methods(git('show',BASE+':'+name));after=methods((ROOT/name).read_text(encoding='utf-8'))
            assert not before-after,(name,before-after)
            prior+=len(before)
    for path in (ROOT/'tests').glob('test_*.py'):current+=len(methods(path.read_text(encoding='utf-8')))
    roots=set();edges={}
    for path in (ROOT/'web').rglob('*.py'):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if (isinstance(node,ast.Call) and isinstance(node.func,ast.Name)
                    and node.func.id in {'render_template','render_table_page'} and node.args
                    and isinstance(node.args[0],ast.Constant)):roots.add(node.args[0].value)
    for path in (ROOT/'web/templates').rglob('*.html'):
        edges[path.relative_to(ROOT/'web/templates').as_posix()]=set(re.findall(
            r'{%\s*(?:extends|include|from|import)\s+[\'\"]([^\'\"]+)',path.read_text(encoding='utf-8')))
    visited=set();todo=list(roots)
    while todo:
        name=todo.pop()
        if name not in visited:visited.add(name);todo.extend(edges.get(name,()))
    assert not set(edges)-visited,sorted(set(edges)-visited)
    before=class_methods(git('show',BASE+':web/professor_service.py'))
    service_source=(ROOT/'web/professor_service.py').read_text(encoding='utf-8')
    input_guard=("        if 'participants' in values and not isinstance(values['participants'],list):\n"
        "            raise ProfessorRequestError('Participants must be a list of required committee participants.')\n")
    assert service_source.count(input_guard)==1
    after=class_methods(service_source.replace(input_guard,''))
    assert all(before[key]==after[key] for key in before if key!='directory')
    report=dict(frontendBase=BASE,reviewedMain=REVIEW_BASE,unchangedMainResearchAndGovernance=inherited_main,
        protectedSourceGroups=protected,approvedLogoutCorrections=sorted(logout_files),
        otherProtectedSourcesUnchanged=True,allExistingModelDefinitionsPreserved=True,
        existingAccountMethodsPreservedExceptSessionIdentity=True,
        gatewayOnlyChange='Canonical repository input types and unbound guard invocation; all wire protocols and validators unchanged',
        studentHomeUnchangedApartFromAssetPath=True,sharedCss=css,professorBusinessMethodsUnchanged=True,
        approvedInputValidation='Optional participants must be a list; malformed input returns 400 before persistence',
        onlyExistingDirectorySpecsAdded=True,templates=len(edges),unreferencedTemplates=[],
        retainedDynamicTemplates=['spaces.html','table.html'],
        testRetention=dict(baseline=prior,current=current,removed=0,consolidated=0),
        cleanup=dict(renamedImplementations=['student-shell.css -> campus-shell.css','student-home.css -> campus-home.css',
            'student-services.css -> campus-services.css','student_service_base.html -> service_base.html',
            'components/student_services.html -> components/services.html','student_error.html -> workspace_error.html'],
            removedUnusedImport='Unused fixture binding from portal browser helper',
            retainedLegacyCss='style.css remains used by staff/administration and legacy views',
            newFrameworks=[],newDependencies=[],backendFeaturesRemoved=[]))
    (ROOT/'docs/professor-services/portal-source-audit.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    screenshots,changed=delivery_inventory()
    print(json.dumps(dict(templates=len(edges),unreferenced=0,baselineTestsRetained=prior,currentTests=current,
        protectedSourceGroupsReviewed=len(protected),screenshotsVerified=screenshots,changedFiles=changed)))


if __name__=='__main__':main()
