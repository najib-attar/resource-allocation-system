"""In-memory form and database seeds, independent of CSV persistence."""

from web.persistence.importer import populate_empty_database


def form(title, action="save"):
    return {"requestType": "CommitteeMeeting", "userId": "2", "spaceId": "301",
            "participantCount": "5", "day": "1", "startTime": "10:00", "endTime": "11:00",
            "title": title, "purpose": "Meeting", "requiredFeature": "None",
            "requiredBuilding": "Main", "submitAction": action,
            "requiredParticipantIds": ["2"], "participantRole_2": title}


def seed_web_database(database, *, with_request=True):
    snapshot = {"protocolVersion": 1, "runId": "web-seed", "strategy": "greedy",
                "users": [{"id": 2, "name": "Professor Ada", "role": "Instructor", "assignedRoles": [],
                           "primaryUnit": "", "email": "", "status": "active", "studentNo": "", "program": "",
                           "yearLevel": 0, "title": "", "officeRoom": "", "assistantType": "", "jobTitle": "", "adminLevel": ""}],
                "spaces": [{"id": 301, "type": "MeetingRoom", "name": "M301", "capacity": 20,
                            "building": "Main", "available": True,
                            "features": {"projector": False, "whiteboard": False, "computers": False}}],
                "requests": [], "busySlots": []}
    if with_request:
        snapshot["requests"].append({"id": 1, "type": "OneTime", "requesterId": 2, "spaceId": 301,
                                     "participantCount": 5, "title": "Original request", "purpose": "Meeting",
                                     "slots": [{"day": 1, "startMinutes": 540, "endMinutes": 600}]})
    populate_empty_database(database, snapshot)
