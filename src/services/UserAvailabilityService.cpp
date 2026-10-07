#include "UserAvailabilityService.h"
#include <algorithm>

namespace {
    constexpr int Monday = 1;
    constexpr int Friday = 5;
    constexpr int DefaultWorkingDayStartMinutes = 9 * 60;
    constexpr int DefaultWorkingDayEndMinutes = 17 * 60;
}

UserAvailabilityService::UserAvailabilityService()
    : UserAvailabilityService(DefaultWorkingDayStartMinutes, DefaultWorkingDayEndMinutes) {}

UserAvailabilityService::UserAvailabilityService(int workingDayStartMinutes,
                                                 int workingDayEndMinutes)
    : workingDayStartMinutes(workingDayStartMinutes),
      workingDayEndMinutes(workingDayEndMinutes) {}

bool UserAvailabilityService::isWithinWorkingHours(const TimeSlot& slot) const {
    const bool isWeekday = slot.getDay() >= Monday && slot.getDay() <= Friday;
    if (!isWeekday) {
        return false;
    }

    return slot.getStartMinutes() >= workingDayStartMinutes &&
           slot.getEndMinutes() <= workingDayEndMinutes;
}

bool UserAvailabilityService::isUserBusy(
    int userId,
    const TimeSlot& slot,
    const std::vector<UserBusySlot>& busySlots
) const {
    for (const UserBusySlot& busySlot : busySlots) {
        if (busySlot.getUserId() == userId &&
            busySlot.getTimeSlot().overlapsWith(slot)) {
            return true;
        }
    }

    return false;
}

bool UserAvailabilityService::isUserAvailable(
    int userId,
    const TimeSlot& slot,
    const std::vector<UserBusySlot>& busySlots,
    const std::vector<Allocation>& allocations
) const {
    if (!isWithinWorkingHours(slot) || isUserBusy(userId, slot, busySlots)) {
        return false;
    }

    for (const Allocation& allocation : allocations) {
        const auto& participantIds = allocation.getRequiredParticipantIds();
        if (allocation.getTimeSlot().overlapsWith(slot) &&
            std::find(participantIds.begin(), participantIds.end(), userId) != participantIds.end()) {
            return false;
        }
    }
    return true;
}

std::vector<UserBusySlot> UserAvailabilityService::getBusySlotsForUser(
    int userId,
    const std::vector<UserBusySlot>& busySlots
) const {
    std::vector<UserBusySlot> userBusySlots;

    for (const UserBusySlot& busySlot : busySlots) {
        if (busySlot.getUserId() == userId) {
            userBusySlots.push_back(busySlot);
        }
    }

    return userBusySlots;
}
