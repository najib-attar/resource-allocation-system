import ast
from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parent.parent


class PersistenceBoundaryTests(TestCase):
    def test_runtime_import_tree_contains_no_archived_file_coordinator(self):
        self.assertFalse((ROOT / "web/shared_file_state.py").exists())
        for path in (ROOT / "web").rglob("*.py"):
            imports = [node.module or "" for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))) if isinstance(node, ast.ImportFrom)]
            imports += [alias.name for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))) if isinstance(node, ast.Import) for alias in node.names]
            with self.subTest(file=path.name):
                self.assertFalse(any("shared_file_state" in name or "legacy_result_adapter" in name for name in imports))
