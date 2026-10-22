#include "RoomSelectionService.h"
#include <algorithm>
#include <tuple>
#include <set>

namespace {
bool overlaps(DatedInterval a, DatedInterval b) { return a.start < b.end && b.start < a.end; }
template<class T> bool has(const std::vector<T>& values, const T& value) {
    return std::find(values.begin(), values.end(), value) != values.end();
}
bool facility(const Space& space, const std::string& key) {
    const std::string name = key == "projector" ? "Projector" : key == "whiteboard" ? "Whiteboard" : "Computers";
    return space.hasFeature(name);
}
}

std::string RoomSelectionService::organizerReason(const RoomSelectionInput& input, DatedInterval slot) {
    if (!input.organizerResolved) return "UNRESOLVED_CALENDAR";
    for (auto busy : input.organizerBusy) if (overlaps(busy, slot)) return "ORGANIZER_BUSY";
    return "AVAILABLE";
}

std::string RoomSelectionService::roomReason(const RoomSelectionInput& input, const StudentRoomOption& room, DatedInterval slot) {
    if (!room.space || !room.enabled || !room.space->getIsAvailable()) return "ROOM_DISABLED";
    if (!room.facultyId || !room.approverId) return "NO_APPROVER";
    if (!has(room.categories, input.category) || (room.restricted && !has(room.allowedUserIds, input.organizerId))) return "ACCESS_RESTRICTED";
    if (room.space->getCapacity() < input.attendeeCount) return "INSUFFICIENT_CAPACITY";
    for (const auto& feature : input.requiredFeatures) if (!facility(*room.space, feature)) return "MISSING_FACILITY";
    if (!room.calendarResolved) return "UNRESOLVED_CALENDAR";
    for (auto busy : room.busy) if (overlaps(busy, slot)) return "ROOM_BUSY";
    return "AVAILABLE";
}

std::vector<StudentRoomCandidate> RoomSelectionService::rank(const RoomSelectionInput& input, DatedInterval slot) {
    std::vector<StudentRoomCandidate> result;
    if (organizerReason(input, slot) != "AVAILABLE") return result;
    for (const auto& room : input.rooms) {
        if (roomReason(input, room, slot) != "AVAILABLE") continue;
        int extras = 0;
        for (const std::string feature : {"projector", "whiteboard", "computers"})
            if (facility(*room.space, feature) && !has(input.requiredFeatures, feature)) ++extras;
        int penalty = (input.preferredFacultyId && input.preferredFacultyId != room.facultyId ? 1 : 0)
                    + (!input.preferredBuilding.empty() && input.preferredBuilding != room.space->getBuilding() ? 1 : 0);
        int spare = room.space->getCapacity() - input.attendeeCount;
        result.push_back({room.space->getId(), room.facultyId, room.space->getCapacity(), spare, extras, penalty, slot,
            "Eligible single room; " + std::to_string(spare) + " spare seats, all required facilities present; "
            + std::to_string(penalty) + " unmatched preferences. Owning faculty approval is required."});
    }
    std::stable_sort(result.begin(), result.end(), [&](const auto& a, const auto& b) {
        if (input.strategy == "greedy") return a.preferencePenalty < b.preferencePenalty;
        return std::tie(a.preferencePenalty, a.spareSeats, a.extraFacilities, a.roomId)
             < std::tie(b.preferencePenalty, b.spareSeats, b.extraFacilities, b.roomId);
    });
    return result;
}

std::vector<StudentRoomCandidate> RoomSelectionService::rankSeries(const RoomSelectionInput& input, const std::vector<DatedInterval>& slots) {
    if (slots.empty()) return {};
    auto result = rank(input, slots.front());
    for (std::size_t i = 1; i < slots.size() && !result.empty(); ++i) {
        std::set<int> eligible;
        for (const auto& row : rank(input, slots[i])) eligible.insert(row.roomId);
        result.erase(std::remove_if(result.begin(), result.end(), [&](const auto& row) {
            return !eligible.count(row.roomId);
        }), result.end());
    }
    return result;
}
