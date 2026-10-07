#ifndef USERAVAILABILITYSERVICE_H
#define USERAVAILABILITYSERVICE_H

#include <vector>
#include "../models/TimeSlot.h"
#include "../models/UserBusySlot.h"
#include "../models/Allocation.h"

class UserAvailabilityService {
private:
    int workingDayStartMinutes;
    int workingDayEndMinutes;

public:
    UserAvailabilityService();
    UserAvailabilityService(int workingDayStartMinutes, int workingDayEndMinutes);

    bool isWithinWorkingHours(const TimeSlot& slot) const;
    bool isUserBusy(int userId,
                    const TimeSlot& slot,
                    const std::vector<UserBusySlot>& busySlots) const;
    bool isUserAvailable(int userId,
                         const TimeSlot& slot,
                         const std::vector<UserBusySlot>& busySlots,
                         const std::vector<Allocation>& allocations = {}) const;
    std::vector<UserBusySlot> getBusySlotsForUser(
        int userId,
        const std::vector<UserBusySlot>& busySlots
    ) const;
};

#endif
