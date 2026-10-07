#include "SharedRoomExamBestFitStrategy.h"
#include <algorithm>
#include <limits>
#include "../models/InvalidRequest.h"

namespace {
    struct CapacityChunk {
        const Space* space;
        int availableCapacity;
    };

    struct BestFitState {
        bool reachable = false;
        int roomCount = std::numeric_limits<int>::max();
    };

    int nextAllocationId(const std::vector<Allocation>& allocations) {
        return static_cast<int>(allocations.size()) + 1;
    }

    bool matchesRequiredBuilding(const Space* space, const std::string& requiredBuilding) {
        return requiredBuilding.empty() || space->getBuilding() == requiredBuilding;
    }

    void rejectExam(ExamRequest& request, const std::string& reason) {
        request.addHistoryEvent("Shared-room exam best-fit rejected request: " + reason);
        request.markRejected(reason);
    }

    std::unordered_map<int, const Request*> buildRequestMap(const std::vector<Request*>& requests) {
        std::unordered_map<int, const Request*> requestById;

        for (const Request* request : requests) {
            if (request) {
                requestById[request->getId()] = request;
            }
        }

        return requestById;
    }

    int getRemainingSharedExamCapacity(
        const Space* space,
        const TimeSlot& examTimeSlot,
        const std::vector<Allocation>& allocations,
        const std::unordered_map<int, const Request*>& requestById
    ) {
        if (!space) {
            return 0;
        }

        int usedExamCapacity = 0;

        for (const Allocation& allocation : allocations) {
            const Space* allocatedSpace = allocation.getSpace();
            if (!allocatedSpace) {
                continue;
            }

            const bool sameSpace = allocatedSpace->getId() == space->getId();
            const bool overlaps = allocation.getTimeSlot().overlapsWith(examTimeSlot);

            if (!sameSpace || !overlaps) {
                continue;
            }

            const auto requestIt = requestById.find(allocation.getRequestId());
            if (requestIt == requestById.end()) {
                return 0;
            }

            if (!dynamic_cast<const ExamRequest*>(requestIt->second)) {
                return 0;
            }

            usedExamCapacity += allocation.getAssignedParticipants();
            if (usedExamCapacity >= space->getCapacity()) {
                return 0;
            }
        }

        return space->getCapacity() - usedExamCapacity;
    }

    std::vector<CapacityChunk> findCapacityChunks(
        const ExamRequest& request,
        const std::vector<Space*>& spaces,
        const std::vector<Allocation>& allocations,
        const std::unordered_map<int, const Request*>& requestById
    ) {
        std::vector<CapacityChunk> candidates;
        const User* requester = request.getRequester();
        const TimeSlot examTimeSlot = request.getExamTimeSlot();

        for (const Space* space : spaces) {
            if (!space || space->getType() != "Classroom") {
                continue;
            }

            if (!space->getIsAvailable()) {
                continue;
            }

            if (!matchesRequiredBuilding(space, request.getRequiredBuilding())) {
                continue;
            }

            if (!space->hasFeature(request.getRequiredFeature())) {
                continue;
            }

            if (!requester || !requester->canRequestSpaceType(space->getType())) {
                continue;
            }

            const int remainingCapacity = getRemainingSharedExamCapacity(
                space,
                examTimeSlot,
                allocations,
                requestById
            );

            if (remainingCapacity <= 0) {
                continue;
            }

            candidates.push_back({space, remainingCapacity});
        }

        return candidates;
    }

    std::vector<CapacityChunk> selectBestFitChunks(const std::vector<CapacityChunk>& candidates,
                                                   int participantCount) {
        int totalCapacity = 0;
        for (const CapacityChunk& candidate : candidates) {
            totalCapacity += candidate.availableCapacity;
        }

        if (participantCount <= 0 || totalCapacity < participantCount) {
            return {};
        }

        std::vector<BestFitState> dp(totalCapacity + 1);
        // Stage-indexed choices survive later updates to the one-dimensional scores.
        std::vector<std::vector<bool>> takeRoom(
            candidates.size(), std::vector<bool>(totalCapacity + 1, false));
        dp[0].reachable = true;
        dp[0].roomCount = 0;

        for (size_t index = 0; index < candidates.size(); ++index) {
            const int capacityChunk = candidates[index].availableCapacity;

            for (int capacity = totalCapacity - capacityChunk; capacity >= 0; --capacity) {
                if (!dp[capacity].reachable) {
                    continue;
                }

                const int nextCapacity = capacity + capacityChunk;
                const int nextRoomCount = dp[capacity].roomCount + 1;

                if (!dp[nextCapacity].reachable ||
                    nextRoomCount < dp[nextCapacity].roomCount) {
                    dp[nextCapacity].reachable = true;
                    dp[nextCapacity].roomCount = nextRoomCount;
                    takeRoom[index][nextCapacity] = true;
                }
            }
        }

        int bestCapacity = -1;
        for (int capacity = participantCount; capacity <= totalCapacity; ++capacity) {
            if (dp[capacity].reachable) {
                bestCapacity = capacity;
                break;
            }
        }

        if (bestCapacity < 0) {
            return {};
        }

        std::vector<CapacityChunk> selectedChunks;
        int currentCapacity = bestCapacity;
        for (size_t index = candidates.size(); index > 0 && currentCapacity > 0; --index) {
            if (!takeRoom[index - 1][currentCapacity]) {
                continue;
            }

            selectedChunks.push_back(candidates[index - 1]);
            currentCapacity -= candidates[index - 1].availableCapacity;
        }
        if (currentCapacity != 0) {
            return {};
        }

        std::reverse(selectedChunks.begin(), selectedChunks.end());
        return selectedChunks;
    }
}

void SharedRoomExamBestFitStrategy::processRequests(
    const std::vector<Request*>& requests,
    const std::vector<Space*>& spaces,
    std::vector<Allocation>& allocations,
    const RuleEngineFacade& ruleEngineFacade
) const {
    const std::unordered_map<int, const Request*> requestById = buildRequestMap(requests);

    for (Request* request : requests) {
        if (OneTimeRequest* oneTime = dynamic_cast<OneTimeRequest*>(request)) {
            oneTime->addHistoryEvent("Shared-room exam best-fit batch processing started");
            processRequest(*oneTime, allocations, ruleEngineFacade);
        }
        else if (RecurringRequest* recurring = dynamic_cast<RecurringRequest*>(request)) {
            recurring->addHistoryEvent("Shared-room exam best-fit batch processing started");
            processRequest(*recurring, allocations, ruleEngineFacade);
        }
        else if (ExamRequest* exam = dynamic_cast<ExamRequest*>(request)) {
            exam->addHistoryEvent("Shared-room exam best-fit batch processing started");

            if (exam->getCanSplitAcrossRooms()) {
                processSplittableExamRequest(*exam, spaces, allocations, requestById);
            } else {
                processRequest(*exam, allocations, ruleEngineFacade);
            }
        }
        else if (CommitteeMeetingRequest* committee = dynamic_cast<CommitteeMeetingRequest*>(request)) {
            committee->addHistoryEvent("Shared-room exam best-fit batch processing started");
            processRequest(*committee, allocations, ruleEngineFacade);
        }
        else if (InvalidRequest* invalid = dynamic_cast<InvalidRequest*>(request)) {
            invalid->addHistoryEvent("Shared-room exam best-fit skipped invalid request");
        }
    }
}

bool SharedRoomExamBestFitStrategy::processRequest(
    OneTimeRequest& request,
    std::vector<Allocation>& allocations,
    const RuleEngineFacade& ruleEngineFacade
) const {
    return greedyStrategy.processRequest(request, allocations, ruleEngineFacade);
}

bool SharedRoomExamBestFitStrategy::processRequest(
    RecurringRequest& request,
    std::vector<Allocation>& allocations,
    const RuleEngineFacade& ruleEngineFacade
) const {
    return greedyStrategy.processRequest(request, allocations, ruleEngineFacade);
}

bool SharedRoomExamBestFitStrategy::processRequest(
    ExamRequest& request,
    std::vector<Allocation>& allocations,
    const RuleEngineFacade& ruleEngineFacade
) const {
    return greedyStrategy.processRequest(request, allocations, ruleEngineFacade);
}

bool SharedRoomExamBestFitStrategy::processRequest(
    CommitteeMeetingRequest& request,
    std::vector<Allocation>& allocations,
    const RuleEngineFacade& ruleEngineFacade
) const {
    return greedyStrategy.processRequest(request, allocations, ruleEngineFacade);
}

bool SharedRoomExamBestFitStrategy::processSplittableExamRequest(
    ExamRequest& request,
    const std::vector<Space*>& spaces,
    std::vector<Allocation>& allocations,
    const std::unordered_map<int, const Request*>& requestById
) const {
    request.addHistoryEvent("Shared-room exam best-fit started evaluation");
    request.addHistoryEvent("evaluated");

    const User* requester = request.getRequester();
    if (!requester || !requester->canSubmitRequestType(request.getRequestType())) {
        rejectExam(request, "User is not allowed to submit Exam requests");
        return false;
    }

    if (!requester->canRequestSpaceType("Classroom")) {
        rejectExam(request, "User role not authorized for requested space type");
        return false;
    }

    const std::vector<CapacityChunk> candidates =
        findCapacityChunks(request, spaces, allocations, requestById);
    const std::vector<CapacityChunk> selectedChunks =
        selectBestFitChunks(candidates, request.getParticipantCount());

    if (selectedChunks.empty()) {
        rejectExam(request, "Not enough shared classroom capacity for exam");
        return false;
    }

    int selectedCapacity = 0;
    for (const CapacityChunk& chunk : selectedChunks) {
        selectedCapacity += chunk.availableCapacity;
    }

    request.addHistoryEvent("Shared-room exam best-fit approved request across "
                            + std::to_string(selectedChunks.size()) + " room(s) with "
                            + std::to_string(selectedCapacity - request.getParticipantCount())
                            + " unused shared seat(s)");
    request.markApproved();

    int assignedTotal = 0;
    const TimeSlot examTimeSlot = request.getExamTimeSlot();
    for (const CapacityChunk& chunk : selectedChunks) {
        const int remainingParticipants = request.getParticipantCount() - assignedTotal;
        const int assignedParticipants = std::min(chunk.availableCapacity, remainingParticipants);

        Allocation allocation(nextAllocationId(allocations),
                              request.getId(),
                              chunk.space,
                              examTimeSlot,
                              assignedParticipants);
        allocations.push_back(allocation);
        assignedTotal += assignedParticipants;
    }

    return true;
}
