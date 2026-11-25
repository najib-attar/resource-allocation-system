"""Catalog and published classroom occupancy for the isolated ITU demo."""

from collections import defaultdict
from datetime import date, datetime, time, timedelta
import json
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select

from ..calendar_service import expand_weekly
from .models import (ROOM_CATEGORIES, AcademicPeriod, AllocationRun, FacultyRoomApprover,
                     OrganizationUnit, Resource, ResourceRequest, RoomAccess, RoomClosure,
                     RoomPolicy, StudentRoomRequest)
from .repository import advance_identity, state_row
from .validation import validate_slot


RESOURCE_TYPES = {
    "classroom": "Classroom", "conference": "Classroom", "research_lab": "Laboratory",
    "teaching_pc_lab": "Laboratory", "teaching_hardware_lab": "Laboratory", "meeting_room": "MeetingRoom",
}
FEATURES = ("projector", "whiteboard", "computers")
OCCUPANCY_REASON = "Published İTÜ OBS teaching"


def catalog_manifest(directory, schedule):
    catalog = json.loads((directory / "resources.json").read_text(encoding="utf-8"))
    records = catalog["resources"]
    codes = {record["roomCode"]: record["id"] for record in records if record.get("roomCode")}
    if len(codes) != sum(bool(record.get("roomCode")) for record in records):
        raise ValueError("Duplicate OBS room code in the ITU resource catalog.")

    meetings = list(schedule["sections"])
    supplemental = directory / "room_schedule.json"
    if supplemental.exists():
        published = json.loads(supplemental.read_text(encoding="utf-8-sig"))
        period = schedule["academicPeriod"]
        if published["academicPeriod"] != period:
            raise ValueError("The supplemental OBS room schedule is from a different academic period.")
        meetings.extend(published["sections"])
        catalog["additionalScheduleSources"] = published.get("sources", {})
        catalog["excludedSupplementalMeetings"] = published.get("excludedMeetings", [])
    catalog["academicPeriod"] = schedule["academicPeriod"]
    occupancy, unmapped, seen = [], [], set()
    for row in meetings:
        record = {key: row.get(key) for key in ("section", "courseCode", "courseTitle",
            "day", "startMinutes", "endMinutes", "buildingCode", "roomCode", "sourceUrl")}
        validate_slot(record)
        if "validUntil" in row:
            last = date.fromisoformat(row["validUntil"])
            period = catalog["academicPeriod"]
            if not date.fromisoformat(period["startDate"]) <= last <= date.fromisoformat(period["endDate"]):
                raise ValueError("An OBS room meeting ends outside the academic period.")
            record["validUntil"] = last.isoformat()
        key = tuple(record[field] for field in ("section", "day", "startMinutes", "endMinutes",
                                               "buildingCode", "roomCode")) + (record.get("validUntil"),)
        if key in seen:
            continue
        seen.add(key)
        building, code = record["buildingCode"], record["roomCode"]
        if building == catalog["buildingCode"] and code in codes:
            occupancy.append(dict(record, resourceId=codes[code]))
        else:
            unmapped.append(record)
    catalog["weeklyOccupancy"] = occupancy
    catalog["unmappedMeetings"] = unmapped
    return catalog


def resource_spaces(manifest):
    return [dict(id=row["id"], name=row["name"], type=RESOURCE_TYPES[row["kind"]],
                 capacity=row["capacity"], building=manifest["buildingCode"],
                 available=row["status"] == "enabled",
                 features={key: key in row["programFeatures"] for key in FEATURES})
            for row in manifest["resources"]]


def install_resource_policies(session, manifest, faculty_id):
    for row in manifest["resources"]:
        status = row["status"]
        session.add(RoomPolicy(resource_id=row["id"], faculty_id=faculty_id, enabled=status != "provisional",
            restricted=status == "restricted", categories=list(ROOM_CATEGORIES)))

    period = manifest["academicPeriod"]
    first, last = date.fromisoformat(period["startDate"]), date.fromisoformat(period["endDate"])
    zone = ZoneInfo(period["timezone"])
    horizon = (datetime.combine(first, time(), zone), datetime.combine(last + timedelta(days=1), time(), zone))
    weekly = {(row["resourceId"], row["day"], row["startMinutes"], row["endMinutes"], row.get("validUntil"))
              for row in manifest["weeklyOccupancy"]}
    occupied = defaultdict(set)
    for resource_id, day, start, end, valid_until in weekly:
        until = date.fromisoformat(valid_until) if valid_until else last
        occupied[resource_id].update(expand_weekly(day, start, end, first, until, zone.key, *horizon, period["recessDates"]))
    count = 0
    for resource_id, slots in sorted(occupied.items()):
        blocks = []
        for start, end in sorted(slots):
            if blocks and start < blocks[-1][1]:
                blocks[-1] = (blocks[-1][0], max(end, blocks[-1][1]))
            else:
                blocks.append((start, end))
        for start, end in blocks:
            session.add(RoomClosure(resource_id=resource_id, start_at=start, end_at=end, reason=OCCUPANCY_REASON))
        count += len(blocks)
    return count


def _legacy_spaces():
    return [dict(id=1001 + i, name=f"Simulated BBF {kind} {i+1:02d}", type=kind, capacity=capacity,
                 building="BBF Demo Facilities", available=True,
                 features=dict(projector=True, whiteboard=True, computers=kind == "Laboratory"))
            for i, (kind, capacity) in enumerate([("Classroom", 60)] * 6 +
                [("Laboratory", 28)] * 3 + [("MeetingRoom", 12)] * 3)]


def _same_catalog(existing, expected):
    def identity(row):
        return row.id, row.name, row.type, row.building

    return [identity(row) for row in existing] == [
        (row["id"], row["name"], row["type"], row["building"]) for row in expected]


def replace_legacy_resources(database, manifest, faculty_name):
    """Replace only the unmodified pre-inventory demo seed, atomically."""
    expected = resource_spaces(manifest)
    with database.transaction() as session:
        state = state_row(session, lock=True)
        existing = list(session.scalars(select(Resource).order_by(Resource.source_order).with_for_update()))
        if _same_catalog(existing, expected):
            manifest["datedOccupancyBlocks"] = session.scalar(select(func.count()).select_from(RoomClosure)
                .where(RoomClosure.reason == OCCUPANCY_REASON))
            return False
        legacy = _legacy_spaces()
        if not _same_catalog(existing, legacy) or any(
            saved.source_order != order or saved.capacity != old["capacity"] or saved.available != old["available"]
            or any(getattr(saved, key) != value for key, value in old["features"].items())
            for order, (saved, old) in enumerate(zip(existing, legacy), 1)
        ):
            raise ValueError("The room inventory is customized. Existing resources were preserved.")
        ids = [row.id for row in existing]
        faculty = session.scalar(select(OrganizationUnit.id).where(OrganizationUnit.name == faculty_name,
                                 OrganizationUnit.unit_type == "Faculty"))
        period = manifest["academicPeriod"]
        matching_period = session.scalar(select(AcademicPeriod.id).where(
            AcademicPeriod.name == period["name"], AcademicPeriod.start_date == date.fromisoformat(period["startDate"]),
            AcademicPeriod.end_date == date.fromisoformat(period["endDate"]), AcademicPeriod.timezone == period["timezone"],
            AcademicPeriod.is_semester.is_(True)))
        if faculty is None or matching_period is None or session.get(FacultyRoomApprover, faculty) is None:
            raise ValueError("The ITU faculty, semester, or room approver does not match the existing profile.")
        policies = list(session.scalars(select(RoomPolicy).order_by(RoomPolicy.resource_id)))
        if [row.resource_id for row in policies] != ids or any(
            row.faculty_id != faculty or not row.enabled or row.restricted or row.categories != list(ROOM_CATEGORIES)
            for row in policies
        ):
            raise ValueError("A legacy room policy was changed. Existing resources were preserved.")
        # Academic publications and room-request history can also retain room identities in JSON snapshots.
        if state.active_run_id is not None or any(session.scalar(select(model).limit(1)) is not None for model in
            (AllocationRun, ResourceRequest, StudentRoomRequest, RoomClosure, RoomAccess)):
            raise ValueError("Legacy rooms are referenced by requests, policies, or history. Existing resources were preserved.")
        session.execute(delete(RoomPolicy).where(RoomPolicy.resource_id.in_(ids)))
        session.execute(delete(Resource).where(Resource.id.in_(ids)))
        for order, row in enumerate(expected, 1):
            session.add(Resource(id=row["id"], source_order=order, type=row["type"], name=row["name"],
                capacity=row["capacity"], building=row["building"], available=row["available"], **row["features"]))
        session.flush()
        count = install_resource_policies(session, manifest, faculty)
        advance_identity(session, Resource)
        state.input_revision += 1
        state.calendar_revision += 1
    manifest["datedOccupancyBlocks"] = count
    return True
