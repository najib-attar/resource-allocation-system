#ifndef MEETINGTIMESUGGESTIONSERVICE_H
#define MEETINGTIMESUGGESTIONSERVICE_H

#include <vector>
#include "../models/Allocation.h"
#include "../models/CommitteeMeetingRequest.h"
#include "../models/MeetingTimeSuggestion.h"
#include "../models/Space.h"
#include "../models/UserBusySlot.h"
#include "UserAvailabilityService.h"

class MeetingTimeSuggestionService {
private:
    UserAvailabilityService userAvailabilityService;

    bool areParticipantsAvailable(
        const CommitteeMeetingRequest& request,
        const TimeSlot& candidateSlot,
        const std::vector<UserBusySlot>& userBusySlots,
        const std::vector<Allocation>& allocations
    ) const;

    bool isRequestedSpaceAvailable(
        const Space* requestedSpace,
        const TimeSlot& candidateSlot,
        const std::vector<Allocation>& allocations
    ) const;

    MeetingTimeSuggestion buildSuggestion(
        const CommitteeMeetingRequest& request,
        const TimeSlot& candidateSlot,
        const Space* requestedSpace
    ) const;

public:
    std::vector<MeetingTimeSuggestion> suggestTimes(
        const CommitteeMeetingRequest& request,
        Space* requestedSpace,
        const std::vector<UserBusySlot>& userBusySlots,
        const std::vector<Allocation>& allocations,
        int maxSuggestions = 3
    ) const;
};

#endif
