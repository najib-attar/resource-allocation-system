from pathlib import Path
from unittest import TestCase

from scripts.generate_database_diagrams import artifacts
from web.persistence.models import Base

ROOT = Path(__file__).resolve().parent.parent


class DatabaseDiagramTests(TestCase):
    def test_diagram_sources_and_catalog_match_all_actual_tables(self):
        for name, expected in artifacts().items():
            self.assertEqual((ROOT / "docs/architecture" / name).read_text(encoding="utf-8"), expected)
        physical = artifacts()["database-er-physical.mmd"]
        self.assertIn("    alembic_version {", physical)
        self.assertEqual(len(Base.metadata.tables), 37)
        for table in Base.metadata.tables.values():
            self.assertIn("    " + table.name + " {", physical)
            self.assertTrue(all(column.name in physical for column in table.columns))
