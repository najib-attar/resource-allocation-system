"""In-memory presentation columns, independent of persistence and file readers."""

INPUT_HEADERS = {
    "users": "userId,name,role,email,status,primaryUnit,assignedRoles,studentNo,program,yearLevel,title,officeRoom,assistantType,jobTitle,adminLevel",
    "spaces": "spaceId,type,name,capacity,hasProjector,hasWhiteboard,hasComputers,isAvailable,building",
    "requests": "requestId,requestType,userId,spaceId,participantCount,requiredFeature,requiredBuilding,timeData,title,purpose,courseCode,courseName,examType,canSplitAcrossRooms",
    "request_participants": "requestId,userId,participantRole",
    "user_busy_slots": "userId,day,startTime,endTime,reason",
}


OUTPUT_HEADERS = {
    "allocations": "allocationId,requestId,spaceId,spaceName,spaceType,building,day,startHour,endHour,assignedParticipants",
    "request_results": "requestId,requestType,title,purpose,courseCode,courseName,examType,canSplitAcrossRooms,committeeParticipants,requesterName,requesterRole,priority,spaceName,spaceType,spaceBuilding,requiredBuilding,requiredFeature,participants,status,rejectionReason,timeInfo,lifecycleHistory",
    "request_summaries": "requestId,requestType,title,purpose,requesterName,requesterRole,priority,status,rejectionReason,requiredParticipants,assignedParticipants,allocationCount,allocatedSpaces,requiredFeature,requiredBuilding,summaryText",
    "allocation_summaries": "allocationId,requestId,requestTitle,requestPurpose,requestType,spaceName,spaceType,building,day,startTime,endTime,assignedParticipants,spaceCapacity",
}


def table_view(headers, rows, *, exists=True, message=""):
    """Project records consistently into the existing template column contract."""
    columns = headers.split(",")
    def scalar(value):
        return str(value).lower() if type(value) is bool else str(value)
    return {"exists": exists, "headers": columns, "message": message,
            "rows": [{key: scalar(row.get(key, "")) for key in columns} for row in rows]}


# Keep bookmarked Raw Data selectors; these aliases never resolve filesystem paths.
RAW_TABLE_ALIASES = {name + ".csv": name for name in (*INPUT_HEADERS, *OUTPUT_HEADERS)}
