#ifndef ALLOCATION_H
#define ALLOCATION_H

#include "Space.h"
#include "TimeSlot.h"
#include "Status.h"
#include <vector>

class Allocation {
private:
    int id;
    int requestId;
    const Space* space;
    TimeSlot timeSlot;
    int assignedParticipants;
    // Committee commitments survive changes to, or destruction of, the source request.
    std::vector<int> requiredParticipantIds;
    AllocationStatus status;

public:
    Allocation(int id, int requestId, const Space* space, const TimeSlot& timeSlot,
               int assignedParticipants,
               const std::vector<int>& requiredParticipantIds = {});

    int getId() const;
    int getRequestId() const;
    const Space* getSpace() const;
    const TimeSlot& getTimeSlot() const;
    int getAssignedParticipants() const;
    const std::vector<int>& getRequiredParticipantIds() const;
    AllocationStatus getStatus() const;
};

#endif
