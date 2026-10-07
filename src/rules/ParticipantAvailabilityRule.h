#ifndef PARTICIPANTAVAILABILITYRULE_H
#define PARTICIPANTAVAILABILITYRULE_H

#include <string>
#include <vector>
#include "IRequestRule.h"
#include "../models/User.h"
#include "../models/UserBusySlot.h"
#include "../services/UserAvailabilityService.h"

class ParticipantAvailabilityRule : public IRequestRule {
private:
    const std::vector<User*>* users;
    const std::vector<UserBusySlot>* userBusySlots;
    UserAvailabilityService availabilityService;

    const User* findUserById(int userId) const;
    std::string formatTimeSlot(const TimeSlot& slot) const;

public:
    ParticipantAvailabilityRule();
    ParticipantAvailabilityRule(const std::vector<User*>& users,
                                const std::vector<UserBusySlot>& userBusySlots);

    RuleEvaluationResult evaluate(Request& request) const override;
    RuleEvaluationResult evaluate(Request& request,
                                  const std::vector<Allocation>& allocations) const override;
};

#endif
