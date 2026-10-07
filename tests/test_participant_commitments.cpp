#include "test_framework.h"
#include "test_helpers.h"
#include "../src/models/CommitteeMeetingRequest.h"
#include "../src/models/Instructor.h"
#include "../src/models/MeetingRoom.h"
#include "../src/services/AllocationService.h"
#include "../src/services/MeetingTimeSuggestionService.h"
#include "../src/services/ResourceAllocationSession.h"
#include "../src/models/Student.h"
#include <chrono>
#include <filesystem>
#include <fstream>

TEST_CASE("All strategies reject overlapping required participants across different rooms") {
    for (const std::string strategy : {"greedy", "priority", "multi_room_exam_greedy",
                                      "multi_room_exam_best_fit", "shared_room_exam_best_fit"}) {
        Instructor professor(2, "Professor X");
        MeetingRoom firstRoom(301, "M301", 20, true, true, false, true, "Main");
        MeetingRoom secondRoom(302, "M302", 20, true, true, false, true, "Main");
        CommitteeMeetingRequest first(1, &professor, &firstRoom, TimeSlot(1, 10, 11), 4);
        CommitteeMeetingRequest second(2, &professor, &secondRoom, TimeSlot(1, 10, 11), 4);
        first.addRequiredParticipant(2, "Supervisor");
        second.addRequiredParticipant(2, "Examiner");
        std::vector<User*> users{&professor};
        std::vector<UserBusySlot> busySlots;
        AllocationService service(strategy, users, busySlots);

        service.processRequests({&first, &second}, {&firstRoom, &secondRoom});

        CHECK(first.getStatus() == RequestStatus::Approved);
        CHECK(second.getStatus() == RequestStatus::Rejected);
        CHECK_EQ(service.getAllocations().size(), static_cast<size_t>(1));
        CHECK_CONTAINS(second.getRejectionReason(), "Professor X");
        CHECK_CONTAINS(second.getRejectionReason(), "Monday 10:00-11:00");
    }
}

TEST_CASE("Committee suggestions exclude another room's approved participant commitment") {
    Instructor professor(2, "Professor X");
    MeetingRoom firstRoom(301, "M301", 20, true, true, false, true, "Main");
    MeetingRoom secondRoom(302, "M302", 20, true, true, false, true, "Main");
    CommitteeMeetingRequest first(1, &professor, &firstRoom, TimeSlot(1, 10, 11), 4);
    CommitteeMeetingRequest second(2, &professor, &secondRoom, TimeSlot(1, 11, 12), 4);
    first.addRequiredParticipant(2, "Supervisor");
    second.addRequiredParticipant(2, "Examiner");
    std::vector<User*> users{&professor};
    std::vector<UserBusySlot> busySlots{UserBusySlot(2, TimeSlot(1, 11, 12), "Lecture")};
    AllocationService service("greedy", users, busySlots);

    service.processRequests({&first, &second}, {&firstRoom, &secondRoom});

    CHECK(first.getStatus() == RequestStatus::Approved);
    CHECK(second.getStatus() == RequestStatus::Rejected);
    CHECK(!historyContains(second, "Monday 10:00-11:00"));
    CHECK(!historyContains(second, "Monday 10:30-11:30"));
    CHECK(historyContains(second, "1) Monday 12:00-13:00"));
}

TEST_CASE("Sequential committee processing retains commitments without borrowing request pointers") {
    Instructor professor(2, "Professor X");
    MeetingRoom firstRoom(301, "M301", 20, true, true, false, true, "Main");
    MeetingRoom secondRoom(302, "M302", 20, true, true, false, true, "Main");
    std::vector<User*> users{&professor};
    std::vector<UserBusySlot> busySlots;
    AllocationService service("greedy", users, busySlots);
    {
        CommitteeMeetingRequest first(1, &professor, &firstRoom, TimeSlot(1, 10, 11), 4);
        first.addRequiredParticipant(2, "Supervisor");
        CHECK(service.processRequest(first));
        first.addRequiredParticipant(3, "Participant");
        CHECK(service.getAllocations()[0].getRequiredParticipantIds() == std::vector<int>{2});
    }
    CommitteeMeetingRequest second(2, &professor, &secondRoom, TimeSlot(1, 10, 11), 4);
    second.addRequiredParticipant(2, "Examiner");
    CHECK(!service.processRequest(second));
    CHECK_EQ(allocationCountForRequest(service.getAllocations(), 2), 0);
    CHECK(historyContains(second, "Suggested least-change alternative times"));
    CHECK(!historyContains(second, "1) Monday 10:00-11:00"));
}

TEST_CASE("Batch suggestions include participant commitments allocated later in the batch") {
    Instructor professor(2, "Professor X");
    MeetingRoom firstRoom(301, "M301", 20, true, true, false, true, "Main");
    MeetingRoom secondRoom(302, "M302", 20, true, true, false, true, "Main");
    std::vector<User*> users{&professor};
    std::vector<UserBusySlot> busySlots{UserBusySlot(2, TimeSlot(1, 9, 10), "Lecture")};
    AllocationService service("greedy", users, busySlots);
    CommitteeMeetingRequest rejected(1, &professor, &firstRoom, TimeSlot(1, 9, 10), 4);
    CommitteeMeetingRequest approved(2, &professor, &secondRoom, TimeSlot(1, 10, 11), 4);
    rejected.addRequiredParticipant(2, "Participant");
    approved.addRequiredParticipant(2, "Participant");
    service.processRequests({&rejected, &approved}, {&firstRoom, &secondRoom});
    CHECK(rejected.getStatus() == RequestStatus::Rejected);
    CHECK(approved.getStatus() == RequestStatus::Approved);
    CHECK(historyContains(rejected, "1) Monday 11:00-12:00"));
    CHECK(!historyContains(rejected, "Monday 10:00-11:00"));
}

TEST_CASE("Required participant commitments use half-open minute intervals") {
    Instructor professor(2, "Professor X");
    MeetingRoom firstRoom(301, "M301", 20, true, true, false, true, "Main");
    MeetingRoom secondRoom(302, "M302", 20, true, true, false, true, "Main");
    std::vector<User*> users{&professor};
    std::vector<UserBusySlot> busySlots;
    AllocationService service("greedy", users, busySlots);
    CommitteeMeetingRequest first(1, &professor, &firstRoom,
                                TimeSlot::fromMinutes(1, 600, 660), 4);
    CommitteeMeetingRequest overlap(2, &professor, &secondRoom,
                                  TimeSlot::fromMinutes(1, 659, 690), 4);
    CommitteeMeetingRequest adjacent(3, &professor, &secondRoom,
                                   TimeSlot::fromMinutes(1, 660, 720), 4);
    for (auto* request : {&first, &overlap, &adjacent}) {
        request->addRequiredParticipant(2, "Participant");
    }
    CHECK(service.processRequest(first));
    CHECK(!service.processRequest(overlap));
    CHECK(service.processRequest(adjacent));
    CHECK_EQ(service.getAllocations().size(), static_cast<size_t>(2));
}

TEST_CASE("Different required participants may meet simultaneously in different rooms") {
    Instructor firstProfessor(2, "Professor X"), secondProfessor(3, "Professor Y");
    MeetingRoom firstRoom(301, "M301", 20, true, true, false, true, "Main");
    MeetingRoom secondRoom(302, "M302", 20, true, true, false, true, "Main");
    std::vector<User*> users{&firstProfessor, &secondProfessor};
    std::vector<UserBusySlot> busySlots;
    AllocationService service("greedy", users, busySlots);
    CommitteeMeetingRequest first(1, &firstProfessor, &firstRoom, TimeSlot(1, 10, 11), 4);
    CommitteeMeetingRequest second(2, &secondProfessor, &secondRoom, TimeSlot(1, 10, 11), 4);
    first.addRequiredParticipant(2, "Supervisor");
    second.addRequiredParticipant(3, "Examiner");
    CHECK(service.processRequest(first));
    CHECK(service.processRequest(second));
    CHECK_EQ(service.getAllocations().size(), static_cast<size_t>(2));
}

TEST_CASE("Participant validation combines loaded busy slots with every required participant") {
    Instructor firstProfessor(2, "Professor X"), secondProfessor(3, "Professor Y");
    MeetingRoom firstRoom(301, "M301", 20, true, true, false, true, "Main");
    MeetingRoom secondRoom(302, "M302", 20, true, true, false, true, "Main");
    std::vector<User*> users{&firstProfessor, &secondProfessor};
    std::vector<UserBusySlot> busySlots{UserBusySlot(3, TimeSlot(1, 12, 13), "Lecture")};
    AllocationService service("greedy", users, busySlots);
    CommitteeMeetingRequest first(1, &firstProfessor, &firstRoom, TimeSlot(1, 10, 11), 4);
    first.addRequiredParticipant(2, "Supervisor");
    CHECK(service.processRequest(first));
    CommitteeMeetingRequest overlap(2, &firstProfessor, &secondRoom, TimeSlot(1, 10, 11), 4);
    overlap.addRequiredParticipant(3, "Supervisor");
    overlap.addRequiredParticipant(2, "Examiner");
    CHECK(!service.processRequest(overlap));
    CHECK_CONTAINS(overlap.getRejectionReason(), "Professor X");
    CommitteeMeetingRequest busy(3, &firstProfessor, &secondRoom, TimeSlot(1, 12, 13), 4);
    busy.addRequiredParticipant(3, "Examiner");
    CHECK(!service.processRequest(busy));
    CHECK_CONTAINS(busy.getRejectionReason(), "Professor Y");
}

TEST_CASE("Rejected meetings do not reserve participants and different days remain available") {
    Instructor professor(2, "Professor X");
    MeetingRoom room(301, "M301", 20, true, true, false, true, "Main");
    std::vector<User*> users{&professor};
    std::vector<UserBusySlot> busySlots;
    AllocationService service("greedy", users, busySlots);
    CommitteeMeetingRequest oversized(1, &professor, &room, TimeSlot(1, 10, 11), 21);
    CommitteeMeetingRequest monday(2, &professor, &room, TimeSlot(1, 10, 11), 4);
    CommitteeMeetingRequest tuesday(3, &professor, &room, TimeSlot(2, 10, 11), 4);
    for (auto* request : {&oversized, &monday, &tuesday}) {
        request->addRequiredParticipant(2, "Participant");
    }
    CHECK(!service.processRequest(oversized));
    CHECK(service.processRequest(monday));
    CHECK(service.processRequest(tuesday));
}

TEST_CASE("Suggestion candidates respect participant and room conflicts without false rejections") {
    Instructor professor(2, "Professor X");
    MeetingRoom room(301, "M301", 20, true, true, false, true, "Main");
    MeetingRoom otherRoom(302, "M302", 20, true, true, false, true, "Main");
    CommitteeMeetingRequest request(4, &professor, &room, TimeSlot(1, 10, 11), 4);
    request.addRequiredParticipant(2, "Participant");
    const std::vector<Allocation> allocations{
        Allocation(1, 1, &otherRoom, TimeSlot(1, 10, 11), 4, {2}),
        Allocation(2, 2, &room, TimeSlot(1, 12, 13), 4),
        Allocation(3, 3, &otherRoom, TimeSlot(1, 11, 12), 4, {3})
    };
    const std::vector<UserBusySlot> busySlots{UserBusySlot(2, TimeSlot(2, 9, 17), "Away")};
    MeetingTimeSuggestionService service;
    const auto suggestions = service.suggestTimes(request, &room, busySlots, allocations, 100);
    CHECK(!suggestions.empty());
    bool hasAdjacent = false;
    for (const auto& suggestion : suggestions) {
        const auto& slot = suggestion.getTimeSlot();
        CHECK(!slot.overlapsWith(allocations[0].getTimeSlot()));
        CHECK(!slot.overlapsWith(allocations[1].getTimeSlot()));
        CHECK(!slot.overlapsWith(busySlots[0].getTimeSlot()));
        if (slot.getDay() == 1 && slot.getStartMinutes() == 660) {
            hasAdjacent = true;
        }
    }
    CHECK(hasAdjacent);
}

TEST_CASE("Priority strategy reserves participants in descending requester priority") {
    Student student(1, "Student");
    Instructor professor(2, "Professor X");
    MeetingRoom firstRoom(301, "M301", 20, true, true, false, true, "Main");
    MeetingRoom secondRoom(302, "M302", 20, true, true, false, true, "Main");
    std::vector<User*> users{&student, &professor};
    std::vector<UserBusySlot> busySlots;
    AllocationService service("priority", users, busySlots);
    CommitteeMeetingRequest low(1, &student, &firstRoom, TimeSlot(1, 10, 11), 4);
    CommitteeMeetingRequest high(2, &professor, &secondRoom, TimeSlot(1, 10, 11), 4);
    low.addRequiredParticipant(2, "Participant");
    high.addRequiredParticipant(2, "Participant");
    service.processRequests({&low, &high}, {&firstRoom, &secondRoom});
    CHECK(high.getStatus() == RequestStatus::Approved);
    CHECK(low.getStatus() == RequestStatus::Rejected);
    CHECK_EQ(service.getAllocations().size(), static_cast<size_t>(1));
    CHECK_EQ(service.getAllocations()[0].getRequestId(), 2);
}

TEST_CASE("Session CSV integration rejects double-booked participants and exports only approval") {
    namespace fs = std::filesystem;
    struct Fixture {
        fs::path directory = fs::temp_directory_path() /
            ("participant-commitments-" + std::to_string(
                std::chrono::steady_clock::now().time_since_epoch().count()));
        Fixture() { fs::create_directory(directory); }
        ~Fixture() { std::error_code error; fs::remove_all(directory, error); }
        std::string path(const std::string& name) const { return (directory / name).string(); }
        void write(const std::string& name, const std::string& text) const {
            std::ofstream file(path(name));
            file << text;
        }
    } fixture;
    fixture.write("users.csv", "userId,name,role\n2,Professor X,Instructor\n");
    fixture.write("spaces.csv",
                  "spaceId,type,name,capacity,hasProjector,hasWhiteboard,hasComputers,isAvailable,building\n"
                  "301,MeetingRoom,M301,20,1,1,0,1,Main\n302,MeetingRoom,M302,20,1,1,0,1,Main\n");
    fixture.write("requests.csv",
                  "requestId,requestType,userId,spaceId,participantCount,requiredFeature,requiredBuilding,timeData,title,purpose\n"
                  "1,CommitteeMeeting,2,301,4,,,1-10-11,First Meeting,Review\n"
                  "2,CommitteeMeeting,2,302,4,,,1-10-11,Second Meeting,Review\n");
    fixture.write("user_busy_slots.csv", "userId,day,startTime,endTime,reason\n");
    fixture.write("request_participants.csv",
                  "requestId,userId,participantRole\n1,2,Supervisor\n2,2,Examiner\n");
    ResourceAllocationSession session;
    CHECK(session.loadSystemData(fixture.path("users.csv"), fixture.path("spaces.csv"),
                                 fixture.path("requests.csv"), fixture.path("user_busy_slots.csv"),
                                 fixture.path("request_participants.csv")));
    CHECK(session.runAllocation());
    CHECK(session.getSystemData().requests[0]->getStatus() == RequestStatus::Approved);
    CHECK(session.getSystemData().requests[1]->getStatus() == RequestStatus::Rejected);
    CHECK_EQ(session.getAllocations().size(), static_cast<size_t>(1));
    CHECK(session.exportResults(fixture.path("allocations.csv"), fixture.path("request_results.csv"),
                                fixture.path("request_summaries.csv"), fixture.path("allocation_summaries.csv")));
    CHECK_FILE_CONTAINS(fixture.path("request_results.csv"), "Professor X is not available");
    CHECK_FILE_CONTAINS(fixture.path("request_results.csv"), "Suggested least-change alternative times");
    std::ifstream file(fixture.path("allocation_summaries.csv"));
    const std::string contents((std::istreambuf_iterator<char>(file)), {});
    CHECK_CONTAINS(contents, "First Meeting");
    CHECK(contents.find("Second Meeting") == std::string::npos);
}
