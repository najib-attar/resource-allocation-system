#include "ResourceAllocationSession.h"
#include "../data/SummaryWriter.h"
#include <iostream>

namespace {
    const std::vector<Allocation>& emptyAllocations() {
        static const std::vector<Allocation> allocations;
        return allocations;
    }
}

ResourceAllocationSession::ResourceAllocationSession()
    : strategyName("greedy"),
      allocationService(nullptr),
      loaded(false),
      allocationProcessed(false) {}

ResourceAllocationSession::~ResourceAllocationSession() {
    cleanup();
}

void ResourceAllocationSession::rebuildAllocationService() {
    allocationService = std::make_unique<AllocationService>(
        strategyName,
        systemData.users,
        systemData.userBusySlots
    );
    allocationProcessed = false;
}

std::string ResourceAllocationSession::loadStrategyName(const std::string& configFile) {
    strategyName = dataController.loadAllocationStrategyName(configFile);

    if (loaded) {
        rebuildAllocationService();
    }

    return strategyName;
}

bool ResourceAllocationSession::loadSystemData(
    const std::string& usersFile,
    const std::string& spacesFile,
    const std::string& requestsFile,
    const std::string& userBusySlotsFile,
    const std::string& requestParticipantsFile
) {
    cleanup();

    systemData = dataController.loadAllData(
        usersFile,
        spacesFile,
        requestsFile,
        userBusySlotsFile,
        requestParticipantsFile
    );

    loaded = !systemData.users.empty() &&
             !systemData.spaces.empty() &&
             !systemData.requests.empty();

    if (loaded) {
        rebuildAllocationService();
    }

    return loaded;
}

bool ResourceAllocationSession::runAllocation() {
    if (!loaded || !allocationService) {
        return false;
    }

    allocationService->processRequests(systemData.requests, systemData.spaces);
    allocationProcessed = true;
    return true;
}

void ResourceAllocationSession::initialize(SystemData&& data, const std::string& strategy) {
    cleanup();
    systemData = std::move(data);
    strategyName = strategy;
    loaded = true;
    rebuildAllocationService();
}

const std::map<int, std::vector<MeetingTimeSuggestion>>& ResourceAllocationSession::getMeetingSuggestions() const {
    static const std::map<int, std::vector<MeetingTimeSuggestion>> empty;
    return allocationService ? allocationService->getMeetingSuggestions() : empty;
}

void ResourceAllocationSession::addExistingAllocation(const Allocation& allocation) {
    if (allocationService) {
        allocationService->addExistingAllocation(allocation);
    }
}

bool ResourceAllocationSession::exportResults(
    const std::string& allocationsFile,
    const std::string& requestResultsFile
) const {
    return exportResults(
        allocationsFile,
        requestResultsFile,
        "data/request_summaries.csv",
        "data/allocation_summaries.csv"
    );
}

bool ResourceAllocationSession::exportResults(
    const std::string& allocationsFile,
    const std::string& requestResultsFile,
    const std::string& requestSummariesFile,
    const std::string& allocationSummariesFile
) const {
    const bool allocationsExported =
        dataController.exportAllocations(allocationsFile, getAllocations());
    const bool requestResultsExported =
        dataController.exportRequestResults(requestResultsFile, systemData.requests);
    const bool requestSummariesExported = SummaryWriter::writeRequestSummaries(
        requestSummariesFile,
        systemData.requests,
        getAllocations()
    );
    const bool allocationSummariesExported = SummaryWriter::writeAllocationSummaries(
        allocationSummariesFile,
        systemData.requests,
        getAllocations()
    );

    const bool allExportsSucceeded =
        allocationsExported &&
        requestResultsExported &&
        requestSummariesExported &&
        allocationSummariesExported;

    if (!allExportsSucceeded) {
        std::cerr << "Error: One or more export files could not be written.\n";
    }

    return allExportsSucceeded;
}

void ResourceAllocationSession::printAllocations() const {
    if (allocationService) {
        allocationService->printAllocations();
    }
}

void ResourceAllocationSession::cleanup() {
    allocationService.reset();
    dataController.cleanupData(systemData);
    systemData.userBusySlots.clear();
    systemData.requestParticipants.clear();
    loaded = false;
    allocationProcessed = false;
}

const std::vector<Allocation>& ResourceAllocationSession::getAllocations() const {
    if (!allocationService) {
        return emptyAllocations();
    }

    return allocationService->getAllocations();
}

SystemData& ResourceAllocationSession::getSystemData() {
    return systemData;
}

const SystemData& ResourceAllocationSession::getSystemData() const {
    return systemData;
}

std::string ResourceAllocationSession::getStrategyName() const {
    return strategyName;
}

bool ResourceAllocationSession::isDataLoaded() const {
    return loaded;
}

bool ResourceAllocationSession::hasRunAllocation() const {
    return allocationProcessed;
}
