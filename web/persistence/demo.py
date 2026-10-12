"""Fictional, deterministic inputs. Allocation decisions always come from C++."""

import random

from .importer import populate_empty_database, validate_snapshot
from .repository import PROFILE_FIELDS


def demo_snapshot(seed=41, size="moderate"):
    if size not in {"moderate", "large"}:
        raise ValueError("Demo size must be moderate or large.")
    scale = 1 if size == "moderate" else 10
    rng = random.Random(seed)
    units = {"Faculty of Applied Sciences": {"type": "Faculty"},
             "Faculty of Social Sciences": {"type": "Faculty"},
             "Computing Department": {"type": "Department", "parent": "Faculty of Applied Sciences"},
             "Engineering Department": {"type": "Department", "parent": "Faculty of Applied Sciences"},
             "Education Department": {"type": "Department", "parent": "Faculty of Social Sciences"},
             "Management Department": {"type": "Department", "parent": "Faculty of Social Sciences"}}
    departments = [name for name, item in units.items() if item["type"] == "Department"]
    users, groups = [], {}
    for role, count in (("Student", 80), ("Instructor", 12), ("TeachingAssistant", 6), ("Staff", 6), ("Administrator", 2)):
        groups[role] = []
        for _ in range(count * scale):
            uid = len(users) + 1
            unit = rng.choice(departments)
            user = {key: "" for key in PROFILE_FIELDS}
            user.update(id=uid, name=f"Demo {rng.choice(('Mira', 'Elio', 'Nora', 'Tessa'))} {rng.choice(('Vale', 'Birch', 'Ashford', 'Reed'))} {uid:04d}",
                        role=role, primaryUnit=unit, assignedRoles=[role], email=f"demo.user{uid}@example.invalid",
                        status="active", yearLevel=rng.randint(1, 4) if role == "Student" else 0)
            if role == "Student":
                user.update(studentNo=f"DEMO-{uid:05d}", program=unit.replace(" Department", ""))
            elif role == "Instructor":
                user.update(title="Associate Professor", officeRoom=f"Office {uid}")
            elif role == "TeachingAssistant":
                user["assistantType"] = "Research and teaching"
            elif role == "Staff":
                user["jobTitle"] = "Academic coordination officer"
            else:
                user["adminLevel"] = "Faculty"
            users.append(user)
            groups[role].append(uid)
    spaces, rooms = [], {}
    for space_type, count in (("Classroom", 12), ("Laboratory", 4), ("MeetingRoom", 4)):
        rooms[space_type] = []
        for number in range(count * scale):
            room = {"id": 1001 + len(spaces), "type": space_type, "name": f"{space_type} {number + 1:03d}",
                    "capacity": (50, 70, 90, 120)[number % 4] if space_type == "Classroom" else 32 if space_type == "Laboratory" else 16,
                    "building": "Science Building" if space_type != "MeetingRoom" else "Administration Building",
                    "features": {"projector": number % 3 != 2, "whiteboard": True, "computers": space_type == "Laboratory"},
                    "available": number != count * scale - 1}
            spaces.append(room)
            rooms[space_type].append(room["id"])
    def slot(day, start, duration=60):
        return {"day": day, "startMinutes": start, "endMinutes": start + duration}
    professor, colleague = groups["Instructor"][:2]
    busy = [{"userId": uid, "reason": "Published teaching commitment (fictional)", "slot": slot(2, 600, 90)}
            for uid in groups["Instructor"]]
    requests = []
    def request(kind, uid, sid, count, slots, title):
        return {"id": len(requests) + 1, "type": kind, "requesterId": uid, "spaceId": sid,
                "participantCount": count, "slots": slots, "title": title, "purpose": "Fictional university demonstration: " + title,
                "requiredFeature": "", "requiredBuilding": ""}
    # Stable scenarios precede randomized requests so demos explain reproducible outcomes.
    requests.append(request("OneTime", groups["Student"][0], rooms["Classroom"][0], 20, [slot(1, 540)], "Student study workshop"))
    requests.append(request("Recurring", professor, rooms["Laboratory"][0], 24, [slot(3, 540), slot(5, 540)], "Weekly programming laboratory"))
    for count, title in ((240, "Multi-room algorithms examination"), (30, "Compatible small examination")):
        item = request("Exam", professor, rooms["Classroom"][1], count, [slot(4, 600, 120)], title)
        item["exam"] = {"courseCode": "DEMO-CS401", "courseName": "Advanced Algorithms", "examType": "Final", "canSplitAcrossRooms": True}
        requests.append(item)
    for room, day, title in ((rooms["MeetingRoom"][0], 1, "Curriculum committee"),
                             (rooms["MeetingRoom"][1], 1, "Conflicting committee invitation"),
                             (rooms["MeetingRoom"][0], 2, "Teaching commitment conflict")):
        item = request("CommitteeMeeting", professor, room, 5, [slot(day, 600)], title)
        item["participants"] = [{"userId": professor, "role": "Chair"}, {"userId": colleague, "role": "Reviewer"}]
        requests.append(item)
    while len(requests) < 120 * scale:
        kind = ("OneTime", "Recurring", "Exam", "CommitteeMeeting")[len(requests) % 4]
        uid = rng.choice(groups["Instructor"] if kind in {"Exam", "Recurring", "CommitteeMeeting"} else groups["Student"])
        room_type = "MeetingRoom" if kind == "CommitteeMeeting" else "Laboratory" if kind == "Recurring" else "Classroom"
        day, start = rng.randint(1, 5), rng.randrange(540, 960, 30)
        item = request(kind, uid, rng.choice(rooms[room_type]), rng.randint(5, 150) if kind == "Exam" else rng.randint(5, 28),
                       [slot(day, start)], f"{kind} academic activity {len(requests) + 1:04d}")
        if kind == "Recurring":
            item["slots"].append(slot((day % 5) + 1, start))
            item["requiredFeature"] = "computers"
        if kind == "Exam":
            item["exam"] = {"courseCode": f"DEMO-{len(requests) + 1}", "courseName": "University assessment",
                            "examType": "Midterm", "canSplitAcrossRooms": True}
        if kind == "CommitteeMeeting":
            item["participantCount"] = 5
            item["participants"] = [{"userId": pid, "role": "CommitteeMember"} for pid in rng.sample(groups["Instructor"], 3)]
        if len(requests) % 9 == 0:
            item["requiredFeature"] = "projector"
        if len(requests) % 11 == 0:
            item["requiredBuilding"] = "Science Building"
        requests.append(item)
    snapshot = {"protocolVersion": 1, "runId": f"demo-seed-{seed}", "strategy": "shared_room_exam_best_fit",
                "users": users, "spaces": spaces, "requests": requests, "busySlots": busy}
    validate_snapshot(snapshot)
    return snapshot, units


def seed_demo_database(database, seed=41, size="moderate"):
    snapshot, units = demo_snapshot(seed, size)
    populate_empty_database(database, snapshot, units, event_kind="seeded")
    return {"seed": seed, "size": size, "counts": {key: len(snapshot[key]) for key in ("users", "spaces", "requests", "busySlots")}}
