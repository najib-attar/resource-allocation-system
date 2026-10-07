#include "PriorityAllocationStrategy.h"
#include <algorithm>
#include "../models/InvalidRequest.h"

namespace {
    bool hasSelfConflict(const std::vector<TimeSlot>& slots) {
        for (size_t i = 0; i < slots.size(); i++) {
            for (size_t j = i + 1; j < slots.size(); j++) {
                if (slots[i].overlapsWith(slots[j])) {
                    return true;
                }
            }
        }
        return false;
    }

    int nextAllocationId(const std::vector<Allocation>& allocations) {
        return static_cast<int>(allocations.size()) + 1;
    }
}

void PriorityAllocationStrategy::processRequests(const std::vector<Request*>& requests,
                                                 const std::vector<Space*>& spaces,
                                                 std::vector<Allocation>& allocations,
                                                 const RuleEngineFacade& ruleEngineFacade) const {
    (void)spaces;

    std::vector<Request*> sortedRequests = requests;

    std::stable_sort(sortedRequests.begin(), sortedRequests.end(),
        [](const Request* left, const Request* right) {
            if (!left || !right) {
                return left != nullptr;
            }

            return left->getPriority() > right->getPriority();
        }
    );

    for (Request* request : sortedRequests) {
        if (!request) {
            continue;
        }

        if (OneTimeRequest* oneTime = dynamic_cast<OneTimeRequest*>(request)) {
            oneTime->addHistoryEvent("Priority strategy started batch processing");
            oneTime->addHistoryEvent("Priority strategy processing request with priority "
                                     + std::to_string(oneTime->getPriority()));
            processRequest(*oneTime, allocations, ruleEngineFacade);
        }
        else if (RecurringRequest* recurring = dynamic_cast<RecurringRequest*>(request)) {
            recurring->addHistoryEvent("Priority strategy started batch processing");
            recurring->addHistoryEvent("Priority strategy processing request with priority "
                                       + std::to_string(recurring->getPriority()));
            processRequest(*recurring, allocations, ruleEngineFacade);
        }
        else if (ExamRequest* exam = dynamic_cast<ExamRequest*>(request)) {
            exam->addHistoryEvent("Priority strategy started batch processing");
            exam->addHistoryEvent("Priority strategy processing request with priority "
                                  + std::to_string(exam->getPriority()));
            processRequest(*exam, allocations, ruleEngineFacade);
        }
        else if (CommitteeMeetingRequest* committee = dynamic_cast<CommitteeMeetingRequest*>(request)) {
            committee->addHistoryEvent("Priority strategy started batch processing");
            committee->addHistoryEvent("Priority strategy processing request with priority "
                                       + std::to_string(committee->getPriority()));
            processRequest(*committee, allocations, ruleEngineFacade);
        }
        else if (InvalidRequest* invalid = dynamic_cast<InvalidRequest*>(request)) {
            invalid->addHistoryEvent("Priority strategy skipped invalid request");
        }
    }
}

bool PriorityAllocationStrategy::processRequest(OneTimeRequest& request,
                                                std::vector<Allocation>& allocations,
                                                const RuleEngineFacade& ruleEngineFacade) const {
    request.addHistoryEvent("Priority strategy started evaluation");
    request.addHistoryEvent("evaluated");
    RuleEvaluationResult result = ruleEngineFacade.evaluateRequest(request, allocations);

    if (!result.isPassed()) {
        request.addHistoryEvent("Priority strategy rejected request: " + result.getFailureReason());
        request.markRejected(result.getFailureReason());
        return false;
    }

    request.addHistoryEvent("Priority strategy approved request");
    request.markApproved();

    int allocationId = nextAllocationId(allocations);
    Allocation allocation(allocationId, request.getId(),
                          request.getRequestedSpace(),
                          request.getRequestedTimeSlot(),
                          request.getParticipantCount());
    allocations.push_back(allocation);

    return true;
}

bool PriorityAllocationStrategy::processRequest(RecurringRequest& request,
                                                std::vector<Allocation>& allocations,
                                                const RuleEngineFacade& ruleEngineFacade) const {
    request.addHistoryEvent("Priority strategy started evaluation");
    request.addHistoryEvent("evaluated");

    if (hasSelfConflict(request.getRequestedTimeSlots())) {
        request.addHistoryEvent("Priority strategy rejected request: Self-conflicting recurring request");
        request.markRejected("Self-conflicting recurring request");
        return false;
    }

    RuleEvaluationResult result = ruleEngineFacade.evaluateRequest(request, allocations);

    if (!result.isPassed()) {
        request.addHistoryEvent("Priority strategy rejected request: " + result.getFailureReason());
        request.markRejected(result.getFailureReason());
        return false;
    }

    request.addHistoryEvent("Priority strategy approved request");
    request.markApproved();

    const std::vector<TimeSlot>& slots = request.getRequestedTimeSlots();
    for (const TimeSlot& slot : slots) {
        int allocationId = nextAllocationId(allocations);
        Allocation allocation(allocationId, request.getId(),
                              request.getRequestedSpace(), slot,
                              request.getParticipantCount());
        allocations.push_back(allocation);
    }

    return true;
}

bool PriorityAllocationStrategy::processRequest(ExamRequest& request,
                                                std::vector<Allocation>& allocations,
                                                const RuleEngineFacade& ruleEngineFacade) const {
    request.addHistoryEvent("Priority strategy started evaluation");
    request.addHistoryEvent("evaluated");
    RuleEvaluationResult result = ruleEngineFacade.evaluateRequest(request, allocations);

    if (!result.isPassed()) {
        request.addHistoryEvent("Priority strategy rejected request: " + result.getFailureReason());
        request.markRejected(result.getFailureReason());
        return false;
    }

    request.addHistoryEvent("Priority strategy approved request");
    request.markApproved();

    int allocationId = nextAllocationId(allocations);
    Allocation allocation(allocationId, request.getId(),
                          request.getRequestedSpace(),
                          request.getExamTimeSlot(),
                          request.getParticipantCount());
    allocations.push_back(allocation);

    return true;
}

bool PriorityAllocationStrategy::processRequest(CommitteeMeetingRequest& request,
                                                std::vector<Allocation>& allocations,
                                                const RuleEngineFacade& ruleEngineFacade) const {
    request.addHistoryEvent("Priority strategy started evaluation");
    request.addHistoryEvent("evaluated");
    RuleEvaluationResult result = ruleEngineFacade.evaluateRequest(request, allocations);

    if (!result.isPassed()) {
        request.addHistoryEvent("Priority strategy rejected request: " + result.getFailureReason());
        request.markRejected(result.getFailureReason());
        return false;
    }

    request.addHistoryEvent("Priority strategy approved request");
    request.markApproved();

    int allocationId = nextAllocationId(allocations);
    Allocation allocation(allocationId, request.getId(),
                          request.getRequestedSpace(),
                          request.getPreferredTimeSlot(),
                          request.getParticipantCount(),
                          request.getRequiredParticipantIds());
    allocations.push_back(allocation);

    return true;
}
