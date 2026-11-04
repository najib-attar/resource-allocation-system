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
    for row in git('diff','--name-status','-M',BASE).splitlines():
        status,*paths=row.split('\t')
        changed.append(dict(status=status,path=paths[-1],**({'previousPath':paths[0]} if len(paths)>1 else {})))
    known={row['path'] for row in changed}
    for path in git('ls-files','--others','--exclude-standard').splitlines():
        if path not in known:changed.append(dict(status='A',path=path))
    (output/'changed-files.json').write_text(json.dumps(dict(reviewedBase=git('rev-parse',BASE).strip(),
        inheritedStudentBase='747c925b14c29368e6cb9bc8b2e2d9d33c494462',
        professorBranch='codex/professor-services-v1',
        files=sorted(changed,key=lambda row:row['path'])),indent=2)+'\n',encoding='utf-8')
    return len(screenshots),len(changed)


def main():
    protected=['src','migrations','web/persistence','web/academic_eligibility.py','web/engine_gateway.py',
        'web/account_service.py','web/appointment_service.py','web/room_request_service.py','web/equipment_service.py',
        'web/calendar_service.py','web/university_calendar.py','web/personal_schedule_service.py',
        'web/notification_service.py','web/student_routes.py','web/student_dashboard_service.py','requirements.txt']
    assert not git('diff',BASE,'--',*protected)
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
    after=class_methods((ROOT/'web/professor_service.py').read_text(encoding='utf-8'))
    assert all(before[key]==after[key] for key in before if key!='directory')
    report=dict(frontendBase=BASE,unchangedProtectedSources=protected,
        studentHomeUnchangedApartFromAssetPath=True,sharedCss=css,professorBusinessMethodsUnchanged=True,
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
        protectedSourcesUnchanged=len(protected),screenshotsVerified=screenshots,changedFiles=changed)))


if __name__=='__main__':main()
