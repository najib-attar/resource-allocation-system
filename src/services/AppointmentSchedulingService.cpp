#include "AppointmentSchedulingService.h"
#include <algorithm>
#include <cstdlib>

namespace {
bool contains(const std::vector<int>& ids, int id) {
    return std::find(ids.begin(), ids.end(), id) != ids.end();
}
bool overlaps(DatedInterval a, DatedInterval b) {
    return a.start < b.end && b.start < a.end;
}
bool busy(const AppointmentSchedulingInput& input, int id, DatedInterval slot) {
    const auto found = input.busy.find(id);
    if (found == input.busy.end()) return false;
    for (auto interval : found->second) if (overlaps(interval, slot)) return true;
    return false;
}
std::vector<DatedInterval> merged(std::vector<DatedInterval> values) {
    std::sort(values.begin(), values.end(), [](auto a, auto b) { return a.start < b.start; });
    std::vector<DatedInterval> result;
    for (auto value : values) {
        if (!result.empty() && value.start <= result.back().end)
            result.back().end = std::max(result.back().end, value.end);
        else result.push_back(value);
    }
    return result;
}
}

std::string AppointmentSchedulingService::validate(const AppointmentSchedulingInput& input, DatedInterval slot) {
    if (contains(input.unresolvedIds, input.organizerId)) return "UNRESOLVED_CALENDAR";
    for (int id : input.professorIds)
        if (contains(input.unresolvedIds, id)) return "UNRESOLVED_CALENDAR";
    if (slot.end - slot.start != input.durationMinutes * 60LL || slot.start < input.horizon.start || slot.end > input.horizon.end)
        return "INVALID_INTERVAL";
    for (int id : input.professorIds) {
        const auto found = input.published.find(id);
        bool covered = false;
        if (found != input.published.end())
            for (auto window : merged(found->second))
                if (window.start <= slot.start && window.end >= slot.end) covered = true;
        if (!covered) return "OUTSIDE_PUBLISHED_AVAILABILITY";
        if (busy(input, id, slot)) return "REQUIRED_PARTICIPANT_BUSY";
    }
    if (busy(input, input.organizerId, slot)) return "ORGANIZER_BUSY";
    return "AVAILABLE";
}

AppointmentCandidate AppointmentSchedulingService::describe(const AppointmentSchedulingInput& input, DatedInterval slot) {
    AppointmentCandidate result{slot, {}, {}, {}, input.preferredStart ? std::llabs(slot.start - input.preferredStart) : 0};
    for (int id : input.invitedIds) {
        if (contains(input.unresolvedIds, id)) result.unresolvedInvitees.push_back(id);
        else if (busy(input, id, slot)) result.unavailableInvitees.push_back(id);
        else result.availableInvitees.push_back(id);
    }
    return result;
}

std::vector<AppointmentCandidate> AppointmentSchedulingService::recommend(const AppointmentSchedulingInput& input, int limit) {
    std::vector<AppointmentCandidate> result;
    const auto found = input.published.find(input.professorIds.front());
    if (found == input.published.end()) return result;
    for (auto window : merged(found->second)) {
        auto first = std::max(window.start, input.horizon.start);
        // The grid is anchored to the explicit office-hour window, not the OS timezone.
        first += (900 - (first - window.start) % 900) % 900;
        for (auto start = first; start + input.durationMinutes * 60LL <= std::min(window.end, input.horizon.end); start += 900) {
            DatedInterval slot{start, start + input.durationMinutes * 60LL};
            if (validate(input, slot) == "AVAILABLE") result.push_back(describe(input, slot));
        }
    }
    std::sort(result.begin(), result.end(), [](const auto& a, const auto& b) {
        if (a.availableInvitees.size() != b.availableInvitees.size()) return a.availableInvitees.size() > b.availableInvitees.size();
        if (a.preferenceDistance != b.preferenceDistance) return a.preferenceDistance < b.preferenceDistance;
        return a.interval.start < b.interval.start;
    });
    if (result.size() > static_cast<std::size_t>(limit)) result.resize(limit);
    return result;
}
