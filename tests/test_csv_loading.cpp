#include "test_framework.h"
#include "../src/data/DataController.h"
#include "../src/models/CommitteeMeetingRequest.h"
#include "../src/models/ExamRequest.h"
#include "../src/models/InvalidRequest.h"
#include "../src/services/AllocationService.h"
#include <chrono>
#include <filesystem>
#include <fstream>

namespace {
    struct CsvFixture {
        std::filesystem::path directory = std::filesystem::temp_directory_path() /
            ("csv-contract-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
        DataController controller;
        SystemData data;

        CsvFixture() {
            std::filesystem::create_directory(directory);
            write("users.csv", "userId,name,role\n2,Professor,Instructor\n");
            write("spaces.csv",
                  "spaceId,type,name,capacity,hasProjector,hasWhiteboard,hasComputers,isAvailable,building\n"
                  "101,Classroom,C101,50,1,1,0,1,Main\n");
            write("user_busy_slots.csv", "userId,day,startTime,endTime,reason\n");
            write("request_participants.csv", "requestId,userId,participantRole\n");
        }
        ~CsvFixture() {
            controller.cleanupData(data);
            std::error_code error;
            std::filesystem::remove_all(directory, error);
        }
        std::string path(const std::string& name) const { return (directory / name).string(); }
        void write(const std::string& name, const std::string& text) const {
            std::ofstream file(path(name), std::ios::binary);
            file << text;
        }
        void load() {
            data = controller.loadAllData(path("users.csv"), path("spaces.csv"), path("requests.csv"),
                                          path("user_busy_slots.csv"), path("request_participants.csv"));
        }
    };
    const std::string requestHeader =
        "requestId,requestType,userId,spaceId,participantCount,requiredFeature,requiredBuilding,timeData,"
        "title,purpose,courseCode,courseName,examType,canSplitAcrossRooms\n";
}

TEST_CASE("CSV request loading preserves quoted metadata exam fields and multiline purpose") {
    CsvFixture fixture;
    fixture.write("requests.csv", requestHeader +
                  "1,OneTime,2,101,4,,,1-10-11,\"Advanced Algorithms, Part II\","
                  "\"Discuss \"\"proofs\"\"\nand examples\",,,,false\n"
                  "2,Exam,2,101,4,,,2-10-11,Exam,Review,\"CS,301\","
                  "\"Algorithms, \"\"Part II\"\"\",Final,true\n");
    fixture.load();
    CHECK_EQ(fixture.data.requests.size(), static_cast<size_t>(2));
    CHECK_EQ(fixture.data.requests[0]->getTitle(), std::string("Advanced Algorithms, Part II"));
    CHECK_EQ(fixture.data.requests[0]->getPurpose(), std::string("Discuss \"proofs\"\nand examples"));
    const auto* exam = dynamic_cast<ExamRequest*>(fixture.data.requests[1]);
    REQUIRE(exam);
    CHECK_EQ(exam->getCourseCode(), std::string("CS,301"));
    CHECK_EQ(exam->getCourseName(), std::string("Algorithms, \"Part II\""));
    CHECK(exam->getCanSplitAcrossRooms());
    AllocationService service("greedy", fixture.data.users, fixture.data.userBusySlots);
    service.processRequests(fixture.data.requests, fixture.data.spaces);
    CHECK_EQ(service.getAllocations().size(), static_cast<size_t>(2));
}

TEST_CASE("CSV input loaders accept quoted names buildings reasons roles and UTF-8") {
    CsvFixture fixture;
    fixture.write("users.csv", "\xEF\xBB\xBF\"userId\",\"name\",\"role\",\"email\"\r\n"
                  "\"2\",\"Professor Jos\xC3\xA9, \"\"Ada\"\"\",\"Instructor\",\"ada@example.edu\"\r\n");
    fixture.write("spaces.csv",
                  "\"spaceId\",\"type\",\"name\",\"capacity\",\"hasProjector\",\"hasWhiteboard\","
                  "\"hasComputers\",\"isAvailable\",\"building\"\r\n"
                  "\"101\",\"Classroom\",\"C,\"\"101\"\"\",\"50\",\"1\",\"1\",\"0\",\"1\",\"Main, North\"\r\n");
    fixture.write("user_busy_slots.csv", "userId,day,startTime,endTime,reason\r\n"
                  "2,2,10:00,11:00,\"Lecture, \"\"Part I\"\"\"\r\n2,3,10:00,11:00,\r\n");
    fixture.write("request_participants.csv", "\"requestId\",\"userId\",\"participantRole\"\n"
                  "\"1\",\"2\",\"Supervisor, \"\"Lead\"\"\"\n");
    fixture.write("requests.csv", requestHeader +
                  "1,CommitteeMeeting,2,101,4,,\"Main, North\",1-10-11,Review,Meeting,,,,false\n");
    fixture.load();
    REQUIRE(fixture.data.users.size() == 1);
    REQUIRE(fixture.data.spaces.size() == 1);
    CHECK_EQ(fixture.data.users[0]->getName(), std::string("Professor Jos\xC3\xA9, \"Ada\""));
    CHECK_EQ(fixture.data.users[0]->getEmail(), std::string("ada@example.edu"));
    CHECK_EQ(fixture.data.spaces[0]->getName(), std::string("C,\"101\""));
    CHECK_EQ(fixture.data.spaces[0]->getBuilding(), std::string("Main, North"));
    CHECK_EQ(fixture.data.spaces[0]->getCapacity(), 50);
    CHECK(fixture.data.spaces[0]->getHasProjector());
    CHECK(fixture.data.spaces[0]->getHasWhiteboard());
    CHECK(!fixture.data.spaces[0]->getHasComputers());
    CHECK(fixture.data.spaces[0]->getIsAvailable());
    REQUIRE(fixture.data.userBusySlots.size() == 2);
    CHECK_EQ(fixture.data.userBusySlots[0].getReason(), std::string("Lecture, \"Part I\""));
    CHECK(fixture.data.userBusySlots[1].getReason().empty());
    REQUIRE(fixture.data.requests.size() == 1);
    const auto* meeting = dynamic_cast<CommitteeMeetingRequest*>(fixture.data.requests[0]);
    REQUIRE(meeting);
    CHECK_EQ(meeting->getParticipantRoles()[0], std::string("Supervisor, \"Lead\""));
    AllocationService service("greedy", fixture.data.users, fixture.data.userBusySlots);
    service.processRequests(fixture.data.requests, fixture.data.spaces);
    CHECK(meeting->getStatus() == RequestStatus::Approved);
}

TEST_CASE("CSV loaders skip malformed quoted auxiliary records without shifting following rows") {
    CsvFixture fixture;
    fixture.write("users.csv", "userId,name,role\n9,\"bad\"oops,Instructor\n2,Professor,Instructor\n");
    fixture.write("spaces.csv",
                  "spaceId,type,name,capacity,hasProjector,hasWhiteboard,hasComputers,isAvailable,building\n"
                  "999,Classroom,un\"quoted,50,1,1,0,1,Main\n"
                  "101,Classroom,C101,50,1,1,0,1,Main\n");
    fixture.write("user_busy_slots.csv", "userId,day,startTime,endTime,reason\n"
                  "2,1,10:00,11:00,\"bad\"oops\n2,2,10:00,11:00,Valid\n");
    fixture.write("request_participants.csv", "requestId,userId,participantRole\n"
                  "1,2,\"bad\"oops\n1,2,Participant\n");
    fixture.write("requests.csv", requestHeader + "1,CommitteeMeeting,2,101,4,,,1-10-11,Valid,Meeting,,,,false\n");
    fixture.load();
    CHECK_EQ(fixture.data.users.size(), static_cast<size_t>(1));
    CHECK_EQ(fixture.data.spaces.size(), static_cast<size_t>(1));
    CHECK_EQ(fixture.data.userBusySlots.size(), static_cast<size_t>(1));
    CHECK_EQ(fixture.data.requestParticipants.size(), static_cast<size_t>(1));
    CHECK_EQ(fixture.data.requests.size(), static_cast<size_t>(1));
    CHECK_EQ(fixture.data.spaces[0]->getId(), 101);
    CHECK_EQ(fixture.data.userBusySlots[0].getTimeSlot().getDay(), 2);
}

TEST_CASE("Malformed request quoting produces InvalidRequest and leaves valid following request intact") {
    CsvFixture fixture;
    fixture.write("requests.csv", requestHeader +
                  "1,OneTime,2,101,4,,,1-10-11,\"bad\"oops,Meeting,,,,false\n"
                  "2,OneTime,2,101,4,,,1-11-12,Valid,Meeting,,,,false\n"
                  "3,OneTime,2,101,4,,,1-12-13,\"unterminated\n");
    fixture.load();
    CHECK_EQ(fixture.data.requests.size(), static_cast<size_t>(3));
    CHECK(dynamic_cast<InvalidRequest*>(fixture.data.requests[0]));
    CHECK_CONTAINS(fixture.data.requests[0]->getRejectionReason(), "Malformed CSV");
    CHECK_EQ(fixture.data.requests[0]->getId(), 1);
    CHECK(!dynamic_cast<InvalidRequest*>(fixture.data.requests[1]));
    CHECK_EQ(fixture.data.requests[1]->getTitle(), std::string("Valid"));
    CHECK(dynamic_cast<InvalidRequest*>(fixture.data.requests[2]));
    CHECK_CONTAINS(fixture.data.requests[2]->getRejectionReason(), "Unterminated quoted field");
    AllocationService service("greedy", fixture.data.users, fixture.data.userBusySlots);
    service.processRequests(fixture.data.requests, fixture.data.spaces);
    CHECK_EQ(service.getAllocations().size(), static_cast<size_t>(1));
    CHECK_EQ(service.getAllocations()[0].getRequestId(), 2);
}

TEST_CASE("Quoted duplicate IDs retain duplicate validation and correctly parsed metadata") {
    CsvFixture fixture;
    fixture.write("users.csv", "userId,name,role\n\"2\",\"First, Professor\",Instructor\n"
                  "\"2\",\"Duplicate, Professor\",Instructor\n");
    fixture.write("spaces.csv",
                  "spaceId,type,name,capacity,hasProjector,hasWhiteboard,hasComputers,isAvailable,building\n"
                  "\"101\",Classroom,\"First, Room\",50,1,1,0,1,Main\n"
                  "\"101\",Classroom,\"Duplicate, Room\",50,1,1,0,1,Main\n");
    fixture.write("requests.csv", requestHeader +
                  "\"1\",OneTime,2,101,4,,,1-10-11,\"First, Request\",Meeting,,,,false\n"
                  "\"1\",OneTime,2,101,4,,,1-11-12,\"Duplicate, Request\",Meeting,,,,false\n");
    fixture.load();
    REQUIRE(fixture.data.users.size() == 1);
    REQUIRE(fixture.data.spaces.size() == 1);
    REQUIRE(fixture.data.requests.size() == 2);
    CHECK_EQ(fixture.data.users[0]->getName(), std::string("First, Professor"));
    CHECK_EQ(fixture.data.spaces[0]->getName(), std::string("First, Room"));
    CHECK_EQ(fixture.data.requests[1]->getRejectionReason(), std::string("Duplicate request ID"));
    CHECK_EQ(fixture.data.requests[1]->getTitle(), std::string("Duplicate, Request"));
}

TEST_CASE("Malformed CSV request records do not allow reuse of an already readable request ID") {
    CsvFixture fixture;
    fixture.write("requests.csv", requestHeader +
                  "7,OneTime,2,101,4,,,1-10-11,\"bad\"oops,Meeting,,,,false\n"
                  "7,OneTime,2,101,4,,,1-11-12,Duplicate,Meeting,,,,false\n"
                  "8abc,OneTime,2,101,4,,,1-12-13,\"bad\"oops,Meeting,,,,false\n"
                  "8,OneTime,2,101,4,,,1-12-13,Valid,Meeting,,,,false\n");
    fixture.load();
    REQUIRE(fixture.data.requests.size() == 4);
    CHECK_CONTAINS(fixture.data.requests[0]->getRejectionReason(), "Malformed CSV");
    CHECK_EQ(fixture.data.requests[1]->getRejectionReason(), std::string("Duplicate request ID"));
    CHECK_EQ(fixture.data.requests[2]->getId(), -1);
    CHECK(!dynamic_cast<InvalidRequest*>(fixture.data.requests[3]));
    AllocationService service("greedy", fixture.data.users, fixture.data.userBusySlots);
    service.processRequests(fixture.data.requests, fixture.data.spaces);
    CHECK_EQ(service.getAllocations().size(), static_cast<size_t>(1));
    CHECK_EQ(service.getAllocations()[0].getRequestId(), 8);
}

TEST_CASE("CSV loading preserves headerless legacy rows defaults and extra columns") {
    CsvFixture fixture;
    fixture.write("users.csv", "\"2\",\"Professor, Ada\",\"Instructor\"\n");
    fixture.write("spaces.csv", "\"101\",Classroom,C101,50,1,1,0,1,Main\n");
    fixture.write("requests.csv", "\"1\",OneTime,2,101,4,,,1-10-11\n"
                  "2,OneTime,2,101,4,,,1-11-12,\"Extra, Metadata\",,,,,false,ignored\n");
    fixture.load();
    REQUIRE(fixture.data.requests.size() == 2);
    CHECK_EQ(fixture.data.requests[0]->getTitle(), std::string("Untitled Request"));
    CHECK_EQ(fixture.data.requests[0]->getPurpose(), std::string("General"));
    CHECK_EQ(fixture.data.requests[1]->getTitle(), std::string("Extra, Metadata"));
    CHECK_EQ(fixture.data.requests[1]->getPurpose(), std::string("General"));
    CHECK(!dynamic_cast<InvalidRequest*>(fixture.data.requests[0]));
    CHECK(!dynamic_cast<InvalidRequest*>(fixture.data.requests[1]));
}
