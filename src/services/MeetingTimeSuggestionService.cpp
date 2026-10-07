#include "MeetingTimeSuggestionService.h"

#include <algorithm>
#include <cstdlib>

namespace {
    constexpr int Monday = 1;
    constexpr int Friday = 5;
    constexpr int WorkingDayStartMinutes = 9 * 60;
    constexpr int WorkingDayEndMinutes = 17 * 60;
    constexpr int ScanStepMinutes = 30;
    constexpr int MinutesPerDay = 24 * 60;
}

bool MeetingTimeSuggestionService::areParticipantsAvailable(
    const CommitteeMeetingRequest& request,
    const TimeSlot& candidateSlot,
    const std::vector<UserBusySlot>& userBusySlots,
    const std::vector<Allocation>& allocations
) const {
    const std::vector<int>& participantIds = request.getRequiredParticipantIds();

    if (participantIds.empty()) {
        return false;
    }

    for (int participantId : participantIds) {
        if (!userAvailabilityService.isUserAvailable(participantId,
                                                     candidateSlot,
                                                     userBusySlots,
                                                     allocations)) {
            return false;
        }
    }

    return true;
}

bool MeetingTimeSuggestionService::isRequestedSpaceAvailable(
    const Space* requestedSpace,
    const TimeSlot& candidateSlot,
    const std::vector<Allocation>& allocations
) const {
    if (!requestedSpace) {
        return false;
    }

    for (const Allocation& allocation : allocations) {
        const Space* allocatedSpace = allocation.getSpace();
        if (allocatedSpace &&
            allocatedSpace->getId() == requestedSpace->getId() &&
            allocation.getTimeSlot().overlapsWith(candidateSlot)) {
            return false;
        }
    }

    return true;
}

MeetingTimeSuggestion MeetingTimeSuggestionService::buildSuggestion(
    const CommitteeMeetingRequest& request,
    const TimeSlot& candidateSlot,
    const Space* requestedSpace
) const {
    const TimeSlot requestedSlot = request.getPreferredTimeSlot();
    const int requestedStart =
        requestedSlot.getDay() * MinutesPerDay + requestedSlot.getStartMinutes();
    const int candidateStart =
        candidateSlot.getDay() * MinutesPerDay + candidateSlot.getStartMinutes();
    const int timeDistanceMinutes = std::abs(candidateStart - requestedStart);
    const int dayDistance = std::abs(candidateSlot.getDay() - requestedSlot.getDay());

    return MeetingTimeSuggestion(
        candidateSlot,
        requestedSpace->getId(),
        "Least-change valid slot",
        timeDistanceMinutes,
        timeDistanceMinutes,
        dayDistance,
        0
    );
}

std::vector<MeetingTimeSuggestion> MeetingTimeSuggestionService::suggestTimes(
    const CommitteeMeetingRequest& request,
    Space* requestedSpace,
    const std::vector<UserBusySlot>& userBusySlots,
    const std::vector<Allocation>& allocations,
    int maxSuggestions
) const {
    std::vector<MeetingTimeSuggestion> suggestions;

    if (!requestedSpace || maxSuggestions <= 0) {
        return suggestions;
    }

    const int durationMinutes = request.getDurationMinutes();
    if (durationMinutes <= 0 ||
        durationMinutes > WorkingDayEndMinutes - WorkingDayStartMinutes) {
        return suggestions;
    }

    const TimeSlot requestedSlot = request.getPreferredTimeSlot();

    for (int day = Monday; day <= Friday; ++day) {
        for (int startMinutes = WorkingDayStartMinutes;
             startMinutes + durationMinutes <= WorkingDayEndMinutes;
             startMinutes += ScanStepMinutes) {
            const int endMinutes = startMinutes + durationMinutes;
            TimeSlot candidateSlot =
                TimeSlot::fromMinutes(day, startMinutes, endMinutes);

            if (!areParticipantsAvailable(request, candidateSlot, userBusySlots, allocations)) {
                continue;
            }

            if (!isRequestedSpaceAvailable(requestedSpace, candidateSlot, allocations)) {
                continue;
            }

            suggestions.push_back(buildSuggestion(request, candidateSlot, requestedSpace));
        }
    }

    std::sort(
        suggestions.begin(),
        suggestions.end(),
        [&requestedSlot](const MeetingTimeSuggestion& left,
                         const MeetingTimeSuggestion& right) {
            if (left.getScore() != right.getScore()) {
                return left.getScore() < right.getScore();
            }

            const TimeSlot leftSlot = left.getTimeSlot();
            const TimeSlot rightSlot = right.getTimeSlot();
            const bool leftSameDay = leftSlot.getDay() == requestedSlot.getDay();
            const bool rightSameDay = rightSlot.getDay() == requestedSlot.getDay();

            if (leftSameDay != rightSameDay) {
                return leftSameDay;
            }

            if (leftSlot.getDay() != rightSlot.getDay()) {
                return leftSlot.getDay() < rightSlot.getDay();
            }

            if (leftSlot.getStartMinutes() != rightSlot.getStartMinutes()) {
                return leftSlot.getStartMinutes() < rightSlot.getStartMinutes();
            }

            return left.getSpaceId() < right.getSpaceId();
        }
    );

    if (static_cast<int>(suggestions.size()) > maxSuggestions) {
        suggestions.erase(suggestions.begin() + maxSuggestions, suggestions.end());
    }

    return suggestions;
}
