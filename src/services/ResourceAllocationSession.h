#ifndef RESOURCEALLOCATIONSESSION_H
#define RESOURCEALLOCATIONSESSION_H

#include <memory>
#include <string>
#include <vector>
#include "../data/DataController.h"
#include "../models/Allocation.h"
#include "AllocationService.h"

class ResourceAllocationSession {
private:
    DataController dataController;
    SystemData systemData;
    std::string strategyName;
    std::unique_ptr<AllocationService> allocationService;
    bool loaded;
    bool allocationProcessed;

    void rebuildAllocationService();

public:
    ResourceAllocationSession();
    ~ResourceAllocationSession();

    ResourceAllocationSession(const ResourceAllocationSession&) = delete;
    ResourceAllocationSession& operator=(const ResourceAllocationSession&) = delete;

    std::string loadStrategyName(const std::string& configFile);
    bool loadSystemData(const std::string& usersFile,
                        const std::string& spacesFile,
                        const std::string& requestsFile,
                        const std::string& userBusySlotsFile = "data/user_busy_slots.csv",
                        const std::string& requestParticipantsFile = "data/request_participants.csv");

    bool runAllocation();
    // Takes ownership of domain objects; CSV loading remains a separate entry point.
    void initialize(SystemData&& data, const std::string& strategy);
    const std::map<int, std::vector<MeetingTimeSuggestion>>& getMeetingSuggestions() const;
    void addExistingAllocation(const Allocation& allocation);
    bool exportResults(const std::string& allocationsFile,
                       const std::string& requestResultsFile) const;
    bool exportResults(const std::string& allocationsFile,
                       const std::string& requestResultsFile,
                       const std::string& requestSummariesFile,
                       const std::string& allocationSummariesFile) const;
    void printAllocations() const;
    void cleanup();

    const std::vector<Allocation>& getAllocations() const;
    SystemData& getSystemData();
    const SystemData& getSystemData() const;
    std::string getStrategyName() const;
    bool isDataLoaded() const;
    bool hasRunAllocation() const;
};

#endif
