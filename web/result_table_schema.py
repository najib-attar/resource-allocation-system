"""Presentation column names and offline CSV contract; no persistence operations."""

INPUT_FILES = ("users.csv", "spaces.csv", "requests.csv", "user_busy_slots.csv",
               "request_participants.csv", "config.txt")
OUTPUT_HEADERS = {
    "allocations.csv": "allocationId,requestId,spaceId,spaceName,spaceType,building,day,startHour,endHour,assignedParticipants",
    "request_results.csv": "requestId,requestType,title,purpose,courseCode,courseName,examType,canSplitAcrossRooms,committeeParticipants,requesterName,requesterRole,priority,spaceName,spaceType,spaceBuilding,requiredBuilding,requiredFeature,participants,status,rejectionReason,timeInfo,lifecycleHistory",
    "request_summaries.csv": "requestId,requestType,title,purpose,requesterName,requesterRole,priority,status,rejectionReason,requiredParticipants,assignedParticipants,allocationCount,allocatedSpaces,requiredFeature,requiredBuilding,summaryText",
    "allocation_summaries.csv": "allocationId,requestId,requestTitle,requestPurpose,requestType,spaceName,spaceType,building,day,startTime,endTime,assignedParticipants,spaceCapacity",
}
