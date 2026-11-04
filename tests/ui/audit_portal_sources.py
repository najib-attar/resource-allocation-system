"""Reproducible UI-10 source inventory; findings require human reachability review."""
import ast
import csv
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from jinja2 import Environment, nodes

OUT = ROOT / 'docs/ui/student-portal/UI-10'


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True, encoding='utf-8').strip()


class Controls(HTMLParser):
    def __init__(self, source, filename):
        super().__init__()
        self.filename, self.forms, self.rows = filename, [], []
        self.feed(source)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == 'form':
            self.forms.append(dict(method=attrs.get('method', 'get'), action=attrs.get('action', 'current endpoint')))
        if tag in {'a', 'button', 'input', 'select', 'textarea', 'summary'}:
            self.rows.append(dict(template=self.filename, line=self.getpos()[0], tag=tag,
                name=attrs.get('name',''), type=attrs.get('type',''), id=attrs.get('id',''),
                value=attrs.get('value',''), href=attrs.get('href',''),
                form=json.dumps(self.forms[-1] if self.forms else {}),
                attributes=json.dumps({k:v for k,v in attrs.items() if k.startswith(('data-','aria-')) or k in {'disabled','hidden','required'}})))

    def handle_endtag(self, tag):
        if tag == 'form' and self.forms:
            self.forms.pop()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    templates = ROOT / 'web/templates'
    env = Environment()
    graph, dynamic, controls = {}, [], []
    for file in sorted(templates.rglob('*.html')):
        source = file.read_text(encoding='utf-8')
        name = file.relative_to(templates).as_posix()
        tree = env.parse(source)
        references = []
        for kind in (nodes.Extends,nodes.Include,nodes.Import,nodes.FromImport):
            for node in tree.find_all(kind):
                if isinstance(node.template,nodes.Const):
                    references.append(node.template.value)
                else:
                    dynamic.append(dict(template=name,line=node.lineno,kind=kind.__name__))
        graph[name] = sorted(set(references))
        controls.extend(Controls(source,name).rows)
    python_renders = []
    for file in sorted((ROOT/'web').rglob('*.py')):
        tree = ast.parse(file.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in {'render_template','render_table_page'}:
                value = node.args[0] if node.args else None
                if isinstance(value,ast.Constant):
                    python_renders.append(dict(file=file.relative_to(ROOT).as_posix(),line=node.lineno,template=value.value))
                else:
                    dynamic.append(dict(file=str(file.relative_to(ROOT)),line=node.lineno,kind='render_template'))
    reached = {row['template'] for row in python_renders}
    while True:
        expanded = reached | {child for name in reached for child in graph.get(name,[])}
        if reached == expanded:
            break
        reached = expanded
    runtime = '\n'.join(p.read_text(encoding='utf-8') for p in (ROOT/'web').rglob('*')
                        if p.is_file() and p.suffix in {'.py','.js','.html'})
    css_candidates = {}
    for file in sorted((ROOT/'web/static').glob('*.css')):
        classes = sorted(set(re.findall(r'\.([a-zA-Z_][\w-]*)',file.read_text(encoding='utf-8'))))
        css_candidates[file.name] = [c for c in classes if not re.search(r'(?<![\w-])'+re.escape(c)+r'(?![\w-])',runtime)]
    files = git('diff','--name-only','610c104..998d54d').splitlines()
    artifact_inventory=[]
    for name in files:
        file = ROOT/name
        if file.is_file():
            artifact_inventory.append(dict(file=name,bytes=file.stat().st_size,sha256=hashlib.sha256(file.read_bytes()).hexdigest()))
    report = dict(baselineHead='998d54dc60207c2fea5434cda0fe68235a566187', branch=git('branch','--show-current'),
        inventoryState='Current UI-10 working-tree file contents for paths changed by UI-01 through UI-09; not baseline content hashes.',
        commits=git('log','--format=%H %s','610c104..998d54d').splitlines(),
        templateReferences=graph, routeTemplates=python_renders, dynamicReferences=dynamic,
        unreachableTemplates=sorted(set(graph)-reached), unusedCssClassCandidates=css_candidates,
        note='Candidates alone are not deletion proof. Dynamic JS classes, all roles, inherited states and browser coverage must be reviewed.',
        changedFileInventory=artifact_inventory)
    (OUT/'source-audit.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    with (OUT/'source-controls.csv').open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(controls[0]));writer.writeheader();writer.writerows(controls)
    print(json.dumps(dict(templates=len(graph),controls=len(controls),changedFiles=len(artifact_inventory),
        unreachable=report['unreachableTemplates'],dynamic=dynamic,prototypeCandidates=css_candidates.get('prototype.css')),indent=2))


if __name__ == '__main__':
    main()
