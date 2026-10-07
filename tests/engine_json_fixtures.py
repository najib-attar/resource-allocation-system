"""Protocol mocks are deliberately separate from real C++ behavioral tests."""

def fake_result(snapshot, marker="new"):
    return {"protocolVersion": 1, "engineVersion": "test-engine", "runId": snapshot["runId"],
            "strategy": snapshot["strategy"], "status": "success", "allocations": [], "suggestions": [], "errors": [],
            "requestResults": [{"requestId": item["id"], "requestType": item["type"], "title": item.get("title", ""),
                                "purpose": item.get("purpose", ""), "requesterName": "Professor", "requesterRole": "Instructor",
                                "priority": 4, "status": "Rejected", "reasonCode": "REQUEST_REJECTED",
                                "rejectionReason": marker, "history": [], "requesterId": item["requesterId"],
                                "participantCount": item["participantCount"], "requestedSpaceId": item["spaceId"],
                                "slots": item["slots"], "requiredFeature": item.get("requiredFeature", ""),
                                "requiredBuilding": item.get("requiredBuilding", ""), "assignedParticipants": 0,
                                "allocationCount": 0, "allocationIds": [], "allocatedSpaceIds": [],
                                "participants": item.get("participants", []), "exam": item.get("exam", {})}
                               for item in snapshot["requests"]]}
