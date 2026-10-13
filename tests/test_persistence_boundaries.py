import ast
from pathlib import Path
from unittest import TestCase

from runtime_file_guard import forbid_runtime_files


ROOT = Path(__file__).resolve().parent.parent


class PersistenceBoundaryTests(TestCase):
    def test_runtime_import_tree_contains_no_archived_file_coordinator(self):
        self.assertFalse((ROOT / "web/shared_file_state.py").exists())
        for path in (ROOT / "web").rglob("*.py"):
            imports = [node.module or "" for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))) if isinstance(node, ast.ImportFrom)]
            imports += [alias.name for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))) if isinstance(node, ast.Import) for alias in node.names]
            with self.subTest(file=path.name):
                self.assertFalse(any("shared_file_state" in name or "legacy_result_adapter" in name for name in imports))

    def test_presentation_and_gateway_have_no_file_or_csv_persistence_interfaces(self):
        from web.backend_result_adapter import BackendResultAdapter
        from web.database_result_adapter import DatabaseResultAdapter
        from web import engine_gateway
        for adapter in (BackendResultAdapter, DatabaseResultAdapter):
            for method in ("read_csv_table", "read_text_file", "pin"):
                self.assertFalse(hasattr(adapter, method))
        self.assertFalse(hasattr(engine_gateway, "execution_snapshot"))
        for name in ("app.py", "backend_result_adapter.py", "database_result_adapter.py",
                     "engine_result_projection.py", "engine_gateway.py"):
            tree = ast.parse((ROOT / "web" / name).read_text(encoding="utf-8"))
            imports = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
            self.assertNotIn("csv", imports, name)

    def test_io_guard_detects_both_file_opens_and_csv_writers(self):
        import csv
        from io import StringIO
        with forbid_runtime_files():
            for name in ("requests.csv", "config.txt", ".runtime/engine-result.json", "shared.lock"):
                with self.subTest(name=name), self.assertRaisesRegex(AssertionError, "Retired operational"):
                    (ROOT / "data" / name).open()
            with self.assertRaisesRegex(AssertionError, "Runtime CSV"):
                csv.writer(StringIO())
