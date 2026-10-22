#ifndef ROOM_SELECTION_SERVICE_H
#define ROOM_SELECTION_SERVICE_H

#include "AppointmentSchedulingService.h"
#include "../models/Space.h"
#include <memory>

struct StudentRoomOption {
    std::shared_ptr<Space> space;
    int facultyId = 0;
    int approverId = 0;
    bool enabled = false;
    bool restricted = false;
    bool calendarResolved = true;
    std::vector<int> allowedUserIds;
    std::vector<std::string> categories;
    std::vector<DatedInterval> busy;
};

struct RoomSelectionInput {
    int organizerId;
    int attendeeCount;
    std::string category;
    std::string strategy;
    std::vector<std::string> requiredFeatures;
    int preferredFacultyId = 0;
    std::string preferredBuilding;
    bool organizerResolved = true;
    std::vector<DatedInterval> organizerBusy;
    DatedInterval proposed;
    DatedInterval horizon;
    std::vector<StudentRoomOption> rooms;
};

struct StudentRoomCandidate {
    int roomId;
    int facultyId;
    int capacity;
    int spareSeats;
    int extraFacilities;
    int preferencePenalty;
    DatedInterval interval;
    std::string reason;
};

class RoomSelectionService {
public:
    static std::string organizerReason(const RoomSelectionInput& input, DatedInterval slot);
    static std::string roomReason(const RoomSelectionInput& input, const StudentRoomOption& room, DatedInterval slot);
    static std::vector<StudentRoomCandidate> rank(const RoomSelectionInput& input, DatedInterval slot);
    static std::vector<StudentRoomCandidate> rankSeries(const RoomSelectionInput& input, const std::vector<DatedInterval>& slots);
};
#endif
