#ifndef APPOINTMENT_SCHEDULING_SERVICE_H
#define APPOINTMENT_SCHEDULING_SERVICE_H

#include <cstdint>
#include <map>
#include <optional>
#include <string>
#include <vector>

struct DatedInterval {
    std::int64_t start;
    std::int64_t end;
};

struct AppointmentSchedulingInput {
    int organizerId;
    std::vector<int> professorIds;
    std::vector<int> invitedIds;
    std::vector<int> unresolvedIds;
    int durationMinutes;
    DatedInterval horizon;
    std::optional<std::int64_t> preferredStart;
    std::map<int, std::vector<DatedInterval>> published;
    std::map<int, std::vector<DatedInterval>> busy;
};

struct AppointmentCandidate {
    DatedInterval interval;
    std::vector<int> availableInvitees;
    std::vector<int> unavailableInvitees;
    std::vector<int> unresolvedInvitees;
    std::int64_t preferenceDistance;
};

class AppointmentSchedulingService {
public:
    static std::string validate(const AppointmentSchedulingInput& input, DatedInterval proposed);
    static AppointmentCandidate describe(const AppointmentSchedulingInput& input, DatedInterval interval);
    static std::vector<AppointmentCandidate> recommend(const AppointmentSchedulingInput& input, int limit);
};
#endif
