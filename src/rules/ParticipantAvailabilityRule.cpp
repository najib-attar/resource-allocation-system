#include "ParticipantAvailabilityRule.h"
#include "../models/CommitteeMeetingRequest.h"

namespace {
    std::string dayToString(int day) {
        switch (day) {
            case 1: return "Monday";
            case 2: return "Tuesday";
            case 3: return "Wednesday";
            case 4: return "Thursday";
            case 5: return "Friday";
            case 6: return "Saturday";
            case 7: return "Sunday";
            default: return "Unknown";
        }
    }
}

ParticipantAvailabilityRule::ParticipantAvailabilityRule()
    : users(nullptr), userBusySlots(nullptr), availabilityService() {}

ParticipantAvailabilityRule::ParticipantAvailabilityRule(
    const std::vector<User*>& users,
    const std::vector<UserBusySlot>& userBusySlots
)
    : users(&users), userBusySlots(&userBusySlots), availabilityService() {}

const User* ParticipantAvailabilityRule::findUserById(int userId) const {
    if (!users) {
        return nullptr;
    }

    for (const User* user : *users) {
        if (user && user->getId() == userId) {
            return user;
        }
    }

    return nullptr;
}

std::string ParticipantAvailabilityRule::formatTimeSlot(const TimeSlot& slot) const {
    return dayToString(slot.getDay()) + " "
        + slot.getStartTimeString() + "-" + slot.getEndTimeString();
}

RuleEvaluationResult ParticipantAvailabilityRule::evaluate(Request& request) const {
    return evaluate(request, {});
}

RuleEvaluationResult ParticipantAvailabilityRule::evaluate(
    Request& request, const std::vector<Allocation>& allocations
) const {
    CommitteeMeetingRequest* committeeRequest =
        dynamic_cast<CommitteeMeetingRequest*>(&request);

    if (!committeeRequest) {
        return RuleEvaluationResult(true, "");
    }

    const std::vector<int>& participantIds =
        committeeRequest->getRequiredParticipantIds();

    if (participantIds.empty()) {
        return RuleEvaluationResult(
            false,
            "Committee meeting has no required participants"
        );
    }

    const std::vector<UserBusySlot> emptyBusySlots;
    const std::vector<UserBusySlot>& busySlots =
        userBusySlots ? *userBusySlots : emptyBusySlots;
    const TimeSlot preferredTimeSlot = committeeRequest->getPreferredTimeSlot();

    for (int participantId : participantIds) {
        const User* participant = findUserById(participantId);

        if (!participant) {
            return RuleEvaluationResult(
                false,
                "Required participant with ID " + std::to_string(participantId)
                + " was not found"
            );
        }

        if (!availabilityService.isUserAvailable(participantId,
                                                 preferredTimeSlot,
                                                 busySlots,
                                                 allocations)) {
            return RuleEvaluationResult(
                false,
                "Required participant " + participant->getName()
                + " is not available at " + formatTimeSlot(preferredTimeSlot)
            );
        }
    }

    return RuleEvaluationResult(true, "");
}
