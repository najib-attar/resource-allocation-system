#ifndef ALLOCATIONSERVICE_H
#define ALLOCATIONSERVICE_H

#include <string>
#include <vector>
#include <map>
#include "../models/Allocation.h"
#include "../models/Request.h"
#include "../models/Space.h"
#include "../models/User.h"
#include "../models/UserBusySlot.h"
#include "../models/OneTimeRequest.h"
#include "../models/RecurringRequest.h"
#include "../models/ExamRequest.h"
#include "../models/CommitteeMeetingRequest.h"
#include "MeetingTimeSuggestionService.h"
#include "../rules/RuleEngineFacade.h"
#include "../strategies/IAllocationStrategy.h"

class AllocationService {
private:
    std::vector<Allocation> allocations;
    std::vector<UserBusySlot> userBusySlots;
    MeetingTimeSuggestionService meetingTimeSuggestionService;
    RuleEngineFacade ruleEngineFacade;
    const IAllocationStrategy* allocationStrategy;
    std::map<int, std::vector<MeetingTimeSuggestion>> meetingSuggestions;

    void appendMeetingTimeSuggestions(CommitteeMeetingRequest& request);
    void appendMeetingTimeSuggestionsForRejectedCommitteeRequests(
        const std::vector<Request*>& requests
    );

public:
    AllocationService();
    explicit AllocationService(const std::string& strategyName);
    AllocationService(const std::string& strategyName,
                      const std::vector<User*>& users,
                      const std::vector<UserBusySlot>& userBusySlots);
    const std::vector<Allocation>& getAllocations() const;
    const std::map<int, std::vector<MeetingTimeSuggestion>>& getMeetingSuggestions() const;
    void addExistingAllocation(const Allocation& allocation);
    void processRequests(const std::vector<Request*>& requests);
    void processRequests(const std::vector<Request*>& requests,
                         const std::vector<Space*>& spaces);
    bool processRequest(OneTimeRequest& request);
    bool processRequest(RecurringRequest& request);
    bool processRequest(ExamRequest& request);
    bool processRequest(CommitteeMeetingRequest& request);
    void printAllocations() const;
};

#endif
