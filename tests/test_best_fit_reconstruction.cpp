#include "test_framework.h"
#include "../src/models/Classroom.h"
#include "../src/models/ExamRequest.h"
#include "../src/models/Instructor.h"
#include "../src/services/AllocationService.h"

#include <memory>
#include <limits>
#include <map>
#include <set>
#include <string>
#include <vector>

namespace {
    const std::vector<std::string> bestFitStrategies{
        "multi_room_exam_best_fit", "shared_room_exam_best_fit"
    };

    void verifyBestFit(const std::string& strategy,
                      const std::vector<int>& capacities,
                      int demand,
                      int expectedCapacity,
                      int expectedRoomCount,
                      const std::vector<int>& expectedIndices = {}) {
        Instructor instructor(2, "Best-fit examiner");
        std::vector<std::unique_ptr<Classroom>> ownedRooms;
        std::vector<Space*> spaces;
        for (size_t index = 0; index < capacities.size(); ++index) {
            ownedRooms.push_back(std::make_unique<Classroom>(
                100 + static_cast<int>(index), "Room" + std::to_string(index), capacities[index],
                false, true, false, true, "ExamBuilding"));
            spaces.push_back(ownedRooms.back().get());
        }
        ExamRequest exam(90, &instructor, spaces.front(), TimeSlot(5, 10, 12), demand,
                         "Best-fit regression", "Exam", "Whiteboard", "ExamBuilding",
                         "CS101", "Algorithms", "Final", true);
        AllocationService service(strategy);
        service.processRequests({&exam}, spaces);
        const auto& allocations = service.getAllocations();
        if (expectedRoomCount == 0) {
            CHECK(exam.getStatus() == RequestStatus::Rejected);
            CHECK(allocations.empty());
            return;
        }
        CHECK(exam.getStatus() == RequestStatus::Approved);
        int assignedTotal = 0;
        int selectedCapacity = 0;
        std::set<int> uniqueRooms;
        std::vector<int> selectedIndices;
        for (const auto& allocation : allocations) {
            REQUIRE(allocation.getSpace());
            CHECK_EQ(allocation.getRequestId(), exam.getId());
            CHECK(allocation.getAssignedParticipants() > 0);
            CHECK(allocation.getAssignedParticipants() <= allocation.getSpace()->getCapacity());
            assignedTotal += allocation.getAssignedParticipants();
            selectedCapacity += allocation.getSpace()->getCapacity();
            uniqueRooms.insert(allocation.getSpace()->getId());
            selectedIndices.push_back(allocation.getSpace()->getId() - 100);
        }
        CHECK_EQ(uniqueRooms.size(), allocations.size());
        CHECK_EQ(assignedTotal, demand);
        CHECK_EQ(selectedCapacity, expectedCapacity);
        CHECK_EQ(allocations.size(), static_cast<size_t>(expectedRoomCount));
        if (!expectedIndices.empty()) {
            CHECK(selectedIndices == expectedIndices);
        }
    }
}

TEST_CASE("Multi-room best-fit reconstructs 10 10 20 demand 40 without reusing a room") {
    verifyBestFit(bestFitStrategies[0], {10, 10, 20}, 40, 40, 3, {0, 1, 2});
}

TEST_CASE("Shared-room best-fit reconstructs 10 10 20 demand 40 without reusing a room") {
    verifyBestFit(bestFitStrategies[1], {10, 10, 20}, 40, 40, 3, {0, 1, 2});
}

TEST_CASE("Multi-room best-fit chooses fewer rooms for the same exact capacity") {
    verifyBestFit(bestFitStrategies[0], {10, 15, 25}, 25, 25, 1, {2});
}

TEST_CASE("Shared-room best-fit chooses fewer rooms for the same exact capacity") {
    verifyBestFit(bestFitStrategies[1], {10, 15, 25}, 25, 25, 1, {2});
}

TEST_CASE("Multi-room best-fit rejects infeasible demand without allocations") {
    verifyBestFit(bestFitStrategies[0], {10, 10, 20}, 41, 0, 0);
}

TEST_CASE("Shared-room best-fit rejects infeasible demand without allocations") {
    verifyBestFit(bestFitStrategies[1], {10, 10, 20}, 41, 0, 0);
}

TEST_CASE("Multi-room best-fit minimizes capacity among multiple feasible combinations") {
    verifyBestFit(bestFitStrategies[0], {10, 20, 25}, 30, 30, 2, {0, 1});
    verifyBestFit(bestFitStrategies[0], {10, 20, 25}, 31, 35, 2, {0, 2});
}

TEST_CASE("Shared-room best-fit minimizes capacity among multiple feasible combinations") {
    verifyBestFit(bestFitStrategies[1], {10, 20, 25}, 30, 30, 2, {0, 1});
    verifyBestFit(bestFitStrategies[1], {10, 20, 25}, 31, 35, 2, {0, 2});
}

TEST_CASE("Multi-room best-fit accepts equal capacities from different physical rooms") {
    verifyBestFit(bestFitStrategies[0], {10, 10, 30}, 20, 20, 2, {0, 1});
}

TEST_CASE("Shared-room best-fit accepts equal capacities from different physical rooms") {
    verifyBestFit(bestFitStrategies[1], {10, 10, 30}, 20, 20, 2, {0, 1});
}

TEST_CASE("Multi-room best-fit keeps first-discovered rooms for equal-score ties") {
    verifyBestFit(bestFitStrategies[0], {20, 20, 20}, 40, 40, 2, {0, 1});
}

TEST_CASE("Shared-room best-fit keeps first-discovered rooms for equal-score ties") {
    verifyBestFit(bestFitStrategies[1], {20, 20, 20}, 40, 40, 2, {0, 1});
}

TEST_CASE("Shared-room best-fit reconstructs distinct remaining-capacity chunks") {
    Instructor instructor(2, "Shared examiner");
    Classroom roomA(100, "A", 20, false, true, false, true, "ExamBuilding");
    Classroom roomB(101, "B", 20, false, true, false, true, "ExamBuilding");
    Classroom roomC(102, "C", 30, false, true, false, true, "ExamBuilding");
    std::vector<Space*> spaces{&roomA, &roomB, &roomC};
    const TimeSlot slot(5, 10, 12);
    std::vector<std::unique_ptr<ExamRequest>> existingExams;
    std::vector<Request*> requests;
    for (int index = 0; index < 3; ++index) {
        existingExams.push_back(std::make_unique<ExamRequest>(
            index + 1, &instructor, spaces[index], slot, 10, "Existing exam", "Exam",
            "Whiteboard", "ExamBuilding", "CS101", "Algorithms", "Final", false));
        requests.push_back(existingExams.back().get());
    }
    ExamRequest exam(4, &instructor, &roomA, slot, 40, "Remaining capacity exam", "Exam",
                     "Whiteboard", "ExamBuilding", "CS102", "Algorithms II", "Final", true);
    requests.push_back(&exam);
    AllocationService service(bestFitStrategies[1]);
    service.processRequests(requests, spaces);
    for (Request* request : requests) {
        CHECK(request->getStatus() == RequestStatus::Approved);
    }
    std::map<int, int> assignedPerRoom;
    std::map<int, int> assignedForNewExam;
    std::set<int> selectedRooms;
    int newExamTotal = 0;
    for (const auto& allocation : service.getAllocations()) {
        const int roomId = allocation.getSpace()->getId();
        assignedPerRoom[roomId] += allocation.getAssignedParticipants();
        if (allocation.getRequestId() == 4) {
            CHECK(selectedRooms.insert(roomId).second);
            assignedForNewExam[roomId] += allocation.getAssignedParticipants();
            newExamTotal += allocation.getAssignedParticipants();
        }
    }
    CHECK_EQ(newExamTotal, 40);
    CHECK_EQ(selectedRooms.size(), static_cast<size_t>(3));
    CHECK_EQ(assignedForNewExam[100], 10);
    CHECK_EQ(assignedForNewExam[101], 10);
    CHECK_EQ(assignedForNewExam[102], 20);
    for (Space* space : spaces) {
        CHECK_EQ(assignedPerRoom[space->getId()], space->getCapacity());
    }
}

namespace {
    void verifyAgainstSubsetOracle(const std::string& strategy) {
        // Exhaustive small instances independently verify both best-fit objectives.
        for (int a : {5, 10, 20}) {
            for (int b : {5, 10, 20}) {
                for (int c : {5, 10, 20}) {
                    for (int d : {5, 10, 20}) {
                        const std::vector<int> capacities{a, b, c, d};
                        for (int demand = 1; demand <= a + b + c + d + 1; ++demand) {
                            int bestCapacity = std::numeric_limits<int>::max();
                            int bestRoomCount = std::numeric_limits<int>::max();
                            for (unsigned mask = 1; mask < 16; ++mask) {
                                int capacity = 0;
                                int roomCount = 0;
                                for (unsigned index = 0; index < 4; ++index) {
                                    if (mask & (1u << index)) {
                                        capacity += capacities[index];
                                        ++roomCount;
                                    }
                                }
                                if (capacity >= demand &&
                                    (capacity < bestCapacity ||
                                     (capacity == bestCapacity && roomCount < bestRoomCount))) {
                                    bestCapacity = capacity;
                                    bestRoomCount = roomCount;
                                }
                            }
                            if (bestCapacity == std::numeric_limits<int>::max()) {
                                verifyBestFit(strategy, capacities, demand, 0, 0);
                            } else {
                                verifyBestFit(strategy, capacities, demand, bestCapacity, bestRoomCount);
                            }
                        }
                    }
                }
            }
        }
    }
}

TEST_CASE("Multi-room best-fit matches an exhaustive four-room subset oracle") {
    verifyAgainstSubsetOracle(bestFitStrategies[0]);
}

TEST_CASE("Shared-room best-fit matches an exhaustive four-room subset oracle") {
    verifyAgainstSubsetOracle(bestFitStrategies[1]);
}
