"""Exercise the BBB inventory through real PostgreSQL and the existing room engine."""

from datetime import date, datetime, timedelta
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from sqlalchemy import select

from postgres_fixtures import PostgresTestCase, ROOT
from web.academic_eligibility import EligibilityService
from web.account_service import AccountService
from web.allocation_workflow import execute_allocation
from web.appointment_service import AppointmentService
from web.calendar_service import CalendarError
from web.engine_gateway import EngineGateway
from web.persistence.equipment_demo import seed_equipment_demo
from web.persistence.importer import populate_empty_database
from web.persistence.itu_resources import _legacy_spaces, catalog_manifest, replace_legacy_resources
from web.persistence.models import (AcademicPeriod, AllocationRun, ApplicationState, BusySlot, EquipmentUnit,
    LegacyCalendarBinding, LoginAccount, OrganizationUnit, RequestEligibility, Resource, RoomAccess,
    RoomClosure, RoomPolicy)
from web.persistence.repository import PROFILE_FIELDS, Repository
from web.room_request_service import RoomRequestError, RoomRequestService


FACULTY = "Bilgisayar ve Bilişim Fakültesi"
ISTANBUL = ZoneInfo("Europe/Istanbul")
TERM = {
    "name": "Synthetic winter term", "startDate": "2030-01-07", "endDate": "2030-01-21",
    "timezone": ISTANBUL.key, "recessDates": ["2030-01-14"],
}
CLASS = {
    "section": "fixture-101", "courseCode": "DEMO101", "courseTitle": "Synthetic teaching",
    "day": 1, "startMinutes": 600, "endMinutes": 660,
    "buildingCode": "BBB", "roomCode": "Z-17", "sourceUrl": "https://example.invalid/schedule",
}


class ItuResourceDatabaseTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        legacy = _legacy_spaces()
        users = []
        for actor, role in enumerate(("Administrator", "Instructor", "Student"), 1):
            user = dict.fromkeys(PROFILE_FIELDS, "")
            user.update(id=actor, name=f"Fixture {role}", role=role, primaryUnit=FACULTY,
                        assignedRoles=[role], status="active", yearLevel=0)
            users.append(user)
        busy = {"userId": 2, "slot": {"day": 3, "startMinutes": 600, "endMinutes": 660},
                "reason": "Pre-existing personal commitment"}
        populate_empty_database(self.database, {
            "protocolVersion": 1, "runId": "legacy-itu", "strategy": "greedy",
            "users": users, "spaces": legacy, "requests": [], "busySlots": [busy],
        }, {FACULTY: {"type": "Faculty"}})
        accounts = AccountService(self.database)
        for user in users:
            actor = user["id"]
            accounts.provision(actor, f"fixture-{actor}", "Synthetic-integration-password", administrator=actor == 1)
        with self.database.transaction() as session:
            self.faculty_id = session.scalar(select(OrganizationUnit.id).where(OrganizationUnit.name == FACULTY))
            term = AcademicPeriod(name=TERM["name"], start_date=date.fromisoformat(TERM["startDate"]),
                                  end_date=date.fromisoformat(TERM["endDate"]), timezone=ISTANBUL.key,
                                  is_semester=True)
            session.add(term)
            session.flush()
            session.add(LegacyCalendarBinding(period_id=term.id, busy_slot_id=session.scalar(select(BusySlot.id)),
                                              excluded_dates=TERM["recessDates"]))
        self.legacy_ids = {room["id"] for room in legacy}
        self.rooms = RoomRequestService(self.database, EngineGateway(ROOT))
        self.rooms.configure_approver(1, self.faculty_id, 1)
        for room_id in sorted(self.legacy_ids):
            self.rooms.configure_room(1, room_id, self.faculty_id, True,
                                      ["study", "meeting", "lecture", "club", "other"])

        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        inputs = Path(temporary.name)
        copyfile(ROOT / "data" / "itu_demo" / "resources.json", inputs / "resources.json")
        self.manifest = catalog_manifest(inputs, {"academicPeriod": TERM, "sections": [CLASS]})

    def _preserved_rows(self):
        with self.database.transaction(read_only=True) as session:
            return (
                session.execute(select(LoginAccount.user_id, LoginAccount.username, LoginAccount.password_hash)
                                .order_by(LoginAccount.user_id)).all(),
                session.execute(select(AcademicPeriod.id, AcademicPeriod.name, AcademicPeriod.start_date,
                                       AcademicPeriod.end_date)).all(),
                session.execute(select(LegacyCalendarBinding.period_id, LegacyCalendarBinding.busy_slot_id,
                                       LegacyCalendarBinding.excluded_dates)).all(),
                session.execute(select(EquipmentUnit.id, EquipmentUnit.asset_tag, EquipmentUnit.condition)
                                .order_by(EquipmentUnit.id)).all(),
            )

    def _state(self):
        with self.database.transaction(read_only=True) as session:
            state = session.get(ApplicationState, 1)
            return state.input_revision, state.calendar_revision, state.active_run_id

    def _resource_ids(self):
        with self.database.transaction(read_only=True) as session:
            return set(session.scalars(select(Resource.id)))

    def test_replacement_preserves_accounts_and_schedules_and_is_idempotent(self):
        seed_equipment_demo(self.database, 1, seed=42)
        preserved = self._preserved_rows()
        previous = self._state()
        self.assertTrue(replace_legacy_resources(self.database, self.manifest, FACULTY))
        self.assertEqual(self._preserved_rows(), preserved)
        changed = self._state()
        self.assertGreater(changed[0], previous[0])
        self.assertGreater(changed[1], previous[1])
        self.assertIsNone(changed[2])

        with self.database.transaction(read_only=True) as session:
            rooms = {room.name: room for room in session.scalars(select(Resource))}
            self.assertEqual(len(rooms), 36)
            self.assertTrue(self.legacy_ids.isdisjoint(room.id for room in rooms.values()))
            self.assertTrue(all(room.building == "BBB" for room in rooms.values()))
            classroom = rooms["BBB Z-17"].id
            research = rooms["Veri Analitiği Laboratuvarı"].id
            self.assertFalse(rooms["BBB Z-18"].available)
            self.assertFalse(rooms["Yeni Lab"].available)
            self.assertFalse(rooms["Veri Analitiği Laboratuvarı"].available)
            self.assertTrue(session.get(RoomPolicy, research).restricted)
            self.assertIsNone(session.get(RoomAccess, (research, 3)))
            self.assertEqual(len(list(session.scalars(select(RoomClosure)))), 2)

        self.assertFalse(replace_legacy_resources(self.database, self.manifest, FACULTY))
        self.assertEqual(self._state(), changed)
        self.assertEqual(self._preserved_rows(), preserved)
        spaces = {room["id"]: room for room in Repository(self.database).snapshot()["spaces"]}
        self.assertFalse(spaces[research]["available"])

        starts = datetime(2030, 1, 7, 10, tzinfo=ISTANBUL)
        self.assertEqual(self.rooms.availability(3, classroom, starts.date())["busy"],
                         [{"start": starts, "end": starts + timedelta(hours=1)}])
        self.assertEqual(self.rooms.availability(3, classroom, date(2030, 1, 14))["busy"], [])
        values = {"start": starts, "duration": 60, "count": 5, "category": "study",
                  "purpose": "Synthetic study session", "features": []}
        candidates = {room["roomId"] for room in self.rooms.recommend(3, values, [])["candidates"]}
        self.assertTrue(candidates)
        self.assertTrue({classroom, research}.isdisjoint(candidates))
        with self.assertRaises(PermissionError):
            self.rooms.availability(3, research, starts.date())
        with self.assertRaises(RoomRequestError):
            self.rooms.submit(3, values, [], research)

    def test_obs_occupancy_rejects_a_conflicting_academic_publication(self):
        replace_legacy_resources(self.database, self.manifest, FACULTY)
        repository = Repository(self.database)
        gateway = EngineGateway(ROOT)
        with self.database.transaction(read_only=True) as session:
            room_id = session.scalar(select(Resource.id).where(Resource.name == "BBB Z-17"))

        def approved_request(day):
            key = repository.save_request({
                "type": "OneTime", "requesterId": 2, "spaceId": room_id, "participantCount": 12,
                "title": "Synthetic academic review", "purpose": "Exercise OBS conflict publication",
                "slots": [{"day": day, "startMinutes": 600, "endMinutes": 660}],
            })
            with self.database.transaction(read_only=True) as session:
                version = session.get(RequestEligibility, key).version
            EligibilityService(self.database).decide(1, key, 1, version, True, "Reviewed synthetic request")
            first = date.fromisoformat(TERM["startDate"])
            AppointmentService(self.database, gateway).bind_legacy(
                TERM["name"], first, date.fromisoformat(TERM["endDate"]), request_id=key, week_start=first,
            )
            return key

        clear = approved_request(2)
        result = execute_allocation(repository, gateway)
        self.assertEqual([allocation["requestId"] for allocation in result["allocations"]], [clear])
        _, published, active = repository.read_view()
        self.assertIsNotNone(active)

        approved_request(1)
        with self.assertRaisesRegex(CalendarError, "conflicts with a confirmed student room reservation or closure"):
            execute_allocation(repository, gateway)
        _, latest, still_active = repository.read_view()
        self.assertEqual(still_active, active)
        self.assertEqual(latest["result"], published["result"])
        with self.database.transaction(read_only=True) as session:
            status = session.scalar(select(AllocationRun.status).order_by(AllocationRun.id.desc()).limit(1))
            self.assertEqual(status, "failed")


    def test_replacement_does_not_rename_an_old_room_with_request_history(self):
        resource_id = min(self.legacy_ids)
        request_id = Repository(self.database).save_request({
            "type": "OneTime", "requesterId": 2, "spaceId": resource_id, "participantCount": 5,
            "title": "Previous demo request", "purpose": "Preserve its original room",
            "slots": [{"day": 1, "startMinutes": 600, "endMinutes": 660}],
        })
        previous = self._state()
        with self.assertRaises(ValueError):
            replace_legacy_resources(self.database, self.manifest, FACULTY)
        self.assertEqual(self._resource_ids(), self.legacy_ids)
        self.assertEqual(self._state(), previous)
        self.assertEqual(Repository(self.database).read_view()[0]["requests"][0]["id"], request_id)

    def test_replacement_does_not_overwrite_an_edited_room_policy(self):
        self.rooms.configure_room(1, min(self.legacy_ids), self.faculty_id, True, ["study"], True, [3])
        previous = self._state()
        with self.assertRaises(ValueError):
            replace_legacy_resources(self.database, self.manifest, FACULTY)
        self.assertEqual(self._resource_ids(), self.legacy_ids)
        self.assertEqual(self._state(), previous)
        with self.database.transaction(read_only=True) as session:
            self.assertIsNotNone(session.get(RoomAccess, (min(self.legacy_ids), 3)))
