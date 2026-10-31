"""Explicit optimizer calls on an owned, fictional PostgreSQL fixture only."""

from dataclasses import asdict
from datetime import timedelta
import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tests"))
from research.cdmcs.i3b.tests import test_readonly_projection as fixture
from research.cdmcs.i3a.adapter import normalize, production_request
from research.cdmcs.i3a.snapshot import Preference
from research.cdmcs.i3c.admission import synthetic_projection
from research.cdmcs.i3c.runner import ShadowRunner


@unittest.skipUnless(os.environ.get("CDMCS_I3A_BINARY") and os.environ.get("CDMCS_I3A_SHA256"),
                     "Explicit native engine path and SHA-256 required")
class ProjectionShadowTests(unittest.TestCase):
    def setUp(self):
        # Compose the existing owned fixture without inheriting/rerunning its tests.
        owner = fixture.ReadonlyProjectionTests()
        self.addCleanup(owner.doCleanups)
        owner.setUp()
        self.database, self.projection = owner.database, owner.projection
        self.context, self.selection = owner.context, owner.selection
        self.block, self.appointment = owner.block, owner.appointment
        self.fingerprint = owner.fingerprint

    def run_projection(self, projection, prepared=True):
        preferences = tuple((p.id, Preference(1, (), 0, 0, 0, "synthetic-fixture-explicit-rate"))
                            for p in projection.internal_snapshot().participants) if prepared else ()
        runner = ShadowRunner(os.environ["CDMCS_I3A_BINARY"], os.environ["CDMCS_I3A_SHA256"],
            production_path=os.environ.get("CDMCS_I3A_PRODUCTION"), enabled=True)
        return runner.run(synthetic_projection(projection, disposable_fixture=True, preferences=preferences))

    def test_student_selection_end_to_end_never_mutates_database(self):
        self.block(5)
        before = self.fingerprint()
        with self.context():
            with mock.patch("subprocess.Popen", side_effect=AssertionError("Projection may not launch processes")):
                projection = self.selection(professors=(2, 3), invitees=(5,))
        # Explicit test-only call after the read transaction/request has ended.
        with self.assertNoLogs():
            result = self.run_projection(projection)
        self.assertEqual(result.status, "match", result)
        self.assertTrue(result.complete)
        self.assertGreater(result.cdmcs_feasible, 0)
        self.assertEqual(self.fingerprint(), before)
        raw = json.dumps(asdict(result))
        for marker in ("Fictional", "projection-fixture", "person-", "start_at", "rate_prefix"):
            self.assertNotIn(marker, raw)

    def test_missing_preferences_do_not_run_optimizer_or_invent_costs(self):
        with self.context():
            projection = self.selection()
        with mock.patch("research.cdmcs.i3c.runner.execute") as execute:
            self.assertEqual(self.run_projection(projection, prepared=False).status, "unsupported")
            execute.assert_not_called()

    def test_existing_review_stays_exact_singleton_for_organizer_and_professor(self):
        key = self.appointment(organizer=1, professors=(2, 3), invitees=(5,))
        for actor in (1, 2, 3):
            with self.context(actor):
                projection = self.projection.for_appointment(key)
            result = self.run_projection(projection)
            self.assertEqual(result.status, "match", result)
            self.assertEqual((result.candidates, result.evaluated), (1, 1))
        self.assertEqual(projection.internal_snapshot().origin, "authorized_calendar")
        with self.assertRaises(ValueError):
            production_request(normalize(projection.internal_snapshot()))

    def test_invited_and_unrelated_identities_cannot_reach_shadow_execution(self):
        key = self.appointment(organizer=1, invitees=(5,))
        with mock.patch("research.cdmcs.i3c.runner.execute") as execute:
            for actor in (5, 6, 7):
                with self.context(actor), self.assertRaises(PermissionError):
                    self.projection.for_appointment(key)
            execute.assert_not_called()

    def test_organizer_busy_is_infeasible_not_unsupported(self):
        self.block(1, end=fixture.START + timedelta(hours=3))
        with self.context():
            projection = self.selection()
        result = self.run_projection(projection)
        self.assertEqual(result.status, "match", result)
        self.assertEqual((result.cdmcs_feasible, result.production_feasible), (0, 0))
        self.assertTrue(result.complete)


if __name__ == "__main__":
    unittest.main()
