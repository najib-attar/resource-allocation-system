#include "MultiRoomExamBestFitStrategy.h"
#include <algorithm>
#include "../models/InvalidRequest.h"
#include "../utils/BestFitSelection.h"

namespace {
    struct CandidateRoom {
        const Space* space;
        int capacity;
    };

    int nextAllocationId(const std::vector<Allocation>& allocations) {
        return static_cast<int>(allocations.size()) + 1;
    }

    bool isSpaceAvailableAt(const Space* space,
                            const TimeSlot& timeSlot,
                            const std::vector<Allocation>& allocations) {
        if (!space) {
            return false;
        }

        for (const Allocation& allocation : allocations) {
            const Space* allocatedSpace = allocation.getSpace();
            if (!allocatedSpace) {
                continue;
            }

            const bool sameSpace = allocatedSpace->getId() == space->getId();
            const bool overlaps = allocation.getTimeSlot().overlapsWith(timeSlot);

            if (sameSpace && overlaps) {
                return false;
            }
        }

        return true;
    }

    bool matchesRequiredBuilding(const Space* space, const std::string& requiredBuilding) {
        return requiredBuilding.empty() || space->getBuilding() == requiredBuilding;
    }

    void rejectExam(ExamRequest& request, const std::string& reason) {
        request.addHistoryEvent("Multi-room exam best-fit rejected request: " + reason);
        request.markRejected(reason);
    }

    std::vector<CandidateRoom> findCandidateRooms(const ExamRequest& request,
                                                  const std::vector<Space*>& spaces,
                                                  const std::vector<Allocation>& allocations) {
        std::vector<CandidateRoom> candidates;
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

            if (!isSpaceAvailableAt(space, examTimeSlot, allocations)) {
                continue;
            }

            if (!requester || !requester->canRequestSpaceType(space->getType())) {
                continue;
            }

            if (space->getCapacity() <= 0) {
                continue;
            }

            candidates.push_back({space, space->getCapacity()});
        }

        return candidates;
    }

    std::vector<const Space*> selectBestFitRooms(const std::vector<CandidateRoom>& candidates,
                                                 int participantCount) {
        std::vector<int> capacities;
        for (const CandidateRoom& candidate : candidates) {
            capacities.push_back(candidate.capacity);
        }
        std::vector<const Space*> selectedRooms;
        for (std::size_t index : best_fit::selectCapacityIndices(capacities, participantCount)) {
            selectedRooms.push_back(candidates[index].space);
        }
        return selectedRooms;
    }
}

void MultiRoomExamBestFitStrategy::processRequests(const std::vector<Request*>& requests,
                                                   const std::vector<Space*>& spaces,
                                                   std::vector<Allocation>& allocations,
                                                   const RuleEngineFacade& ruleEngineFacade) const {
    for (Request* request : requests) {
        if (OneTimeRequest* oneTime = dynamic_cast<OneTimeRequest*>(request)) {
            oneTime->addHistoryEvent("Multi-room exam best-fit batch processing started");
            processRequest(*oneTime, allocations, ruleEngineFacade);
        }
        else if (RecurringRequest* recurring = dynamic_cast<RecurringRequest*>(request)) {
            recurring->addHistoryEvent("Multi-room exam best-fit batch processing started");
            processRequest(*recurring, allocations, ruleEngineFacade);
        }
        else if (ExamRequest* exam = dynamic_cast<ExamRequest*>(request)) {
            exam->addHistoryEvent("Multi-room exam best-fit batch processing started");

            if (exam->getCanSplitAcrossRooms()) {
                processSplittableExamRequest(*exam, spaces, allocations);
            } else {
                processRequest(*exam, allocations, ruleEngineFacade);
            }
        }
        else if (CommitteeMeetingRequest* committee = dynamic_cast<CommitteeMeetingRequest*>(request)) {
            committee->addHistoryEvent("Multi-room exam best-fit batch processing started");
            processRequest(*committee, allocations, ruleEngineFacade);
        }
        else if (InvalidRequest* invalid = dynamic_cast<InvalidRequest*>(request)) {
            invalid->addHistoryEvent("Multi-room exam best-fit skipped invalid request");
        }
    }
}

bool MultiRoomExamBestFitStrategy::processRequest(OneTimeRequest& request,
                                                  std::vector<Allocation>& allocations,
                                                  const RuleEngineFacade& ruleEngineFacade) const {
    return greedyStrategy.processRequest(request, allocations, ruleEngineFacade);
}

bool MultiRoomExamBestFitStrategy::processRequest(RecurringRequest& request,
                                                  std::vector<Allocation>& allocations,
                                                  const RuleEngineFacade& ruleEngineFacade) const {
    return greedyStrategy.processRequest(request, allocations, ruleEngineFacade);
}

bool MultiRoomExamBestFitStrategy::processRequest(ExamRequest& request,
                                                  std::vector<Allocation>& allocations,
                                                  const RuleEngineFacade& ruleEngineFacade) const {
    return greedyStrategy.processRequest(request, allocations, ruleEngineFacade);
}

bool MultiRoomExamBestFitStrategy::processRequest(CommitteeMeetingRequest& request,
                                                  std::vector<Allocation>& allocations,
                                                  const RuleEngineFacade& ruleEngineFacade) const {
    return greedyStrategy.processRequest(request, allocations, ruleEngineFacade);
}

bool MultiRoomExamBestFitStrategy::processSplittableExamRequest(ExamRequest& request,
                                                                const std::vector<Space*>& spaces,
                                                                std::vector<Allocation>& allocations) const {
    request.addHistoryEvent("Multi-room exam best-fit started evaluation");
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

    const std::vector<CandidateRoom> candidates = findCandidateRooms(request, spaces, allocations);
    const std::vector<const Space*> selectedRooms =
        selectBestFitRooms(candidates, request.getParticipantCount());

    if (selectedRooms.empty()) {
        rejectExam(request, "Not enough available classroom capacity for exam");
        return false;
    }

    int selectedCapacity = 0;
    for (const Space* room : selectedRooms) {
        selectedCapacity += room->getCapacity();
    }

    request.addHistoryEvent("Multi-room exam best-fit approved request across "
                            + std::to_string(selectedRooms.size()) + " room(s) with "
                            + std::to_string(selectedCapacity - request.getParticipantCount())
                            + " unused seat(s)");
    request.markApproved();

    int assignedTotal = 0;
    const TimeSlot examTimeSlot = request.getExamTimeSlot();
    for (const Space* room : selectedRooms) {
        const int remainingParticipants = request.getParticipantCount() - assignedTotal;
        const int assignedParticipants = std::min(room->getCapacity(), remainingParticipants);

        Allocation allocation(nextAllocationId(allocations),
                              request.getId(),
                              room,
                              examTimeSlot,
                              assignedParticipants);
        allocations.push_back(allocation);
        assignedTotal += assignedParticipants;
    }

    return true;
}
