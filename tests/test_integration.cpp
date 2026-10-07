#include "test_framework.h"
#include "test_helpers.h"
#include "../src/data/DataController.h"
#include "../src/models/CommitteeMeetingRequest.h"
#include "../src/models/InvalidRequest.h"
#include "../src/services/AllocationService.h"
#include "../src/services/ResourceAllocationSession.h"
#include <cstdio>
#include <fstream>

namespace {
    void writeCsv(const std::string& path, const std::string& contents) {
        std::ofstream file(path);
        file << contents;
    }

    bool fileExistsAndNotEmpty(const std::string& path) {
        std::ifstream file(path, std::ios::binary | std::ios::ate);
        return file.is_open() && file.tellg() > 0;
    }
}

TEST_CASE("DataController loads temp CSVs, processes requests, and exports results") {
    const std::string usersPath = "tests/tmp_users.csv";
    const std::string spacesPath = "tests/tmp_spaces.csv";
    const std::string requestsPath = "tests/tmp_requests.csv";
    const std::string allocationsPath = "tests/tmp_allocations.csv";
    const std::string resultsPath = "tests/tmp_request_results.csv";

    writeCsv(
        usersPath,
        "userId,name,role\n"
        "1,Student One,Student\n"
        "2,Dr Priority,Instructor\n"
    );
    writeCsv(
        spacesPath,
        "spaceId,type,name,capacity,hasProjector,hasWhiteboard,hasComputers,isAvailable,building\n"
        "301,MeetingRoom,M301,10,1,0,0,1,AdminBuilding\n"
    );
    writeCsv(
        requestsPath,
        "requestId,requestType,userId,spaceId,participantCount,requiredFeature,requiredBuilding,timeData,title,purpose,courseCode,courseName,examType,canSplitAcrossRooms\n"
        "1,OneTime,1,301,5,Projector,AdminBuilding,1-10-11,Student Meeting,Meeting,,,,false\n"
        "2,OneTime,2,301,5,Projector,AdminBuilding,1-10-11,Instructor Conflict,Meeting,,,,false\n"
    );

    DataController controller;
    SystemData data = controller.loadAllData(usersPath, spacesPath, requestsPath);

    CHECK_EQ(data.users.size(), static_cast<size_t>(2));
    CHECK_EQ(data.spaces.size(), static_cast<size_t>(1));
    CHECK_EQ(data.requests.size(), static_cast<size_t>(2));

    AllocationService service("priority", data.users, data.userBusySlots);
    service.processRequests(data.requests, data.spaces);
    CHECK(controller.exportAllocations(allocationsPath, service.getAllocations()));
    CHECK(controller.exportRequestResults(resultsPath, data.requests));

    CHECK(data.requests[0]->getStatus() == RequestStatus::Rejected);
    CHECK(data.requests[1]->getStatus() == RequestStatus::Approved);
    CHECK(fileExistsAndNotEmpty(allocationsPath));
    CHECK(fileExistsAndNotEmpty(resultsPath));
    CHECK_FILE_CONTAINS(resultsPath, "Student Meeting");
    CHECK_FILE_CONTAINS(resultsPath, "Instructor Conflict");
    CHECK_FILE_CONTAINS(resultsPath, "Instructor");
    CHECK_FILE_CONTAINS(resultsPath, "Rejected");
    CHECK_FILE_CONTAINS(resultsPath, "Approved");
    CHECK_FILE_CONTAINS(resultsPath, "Time slot unavailable");
    CHECK_FILE_CONTAINS(resultsPath, "exported");

    controller.cleanupData(data);
    std::remove(usersPath.c_str());
    std::remove(spacesPath.c_str());
    std::remove(requestsPath.c_str());
    std::remove(allocationsPath.c_str());
    std::remove(resultsPath.c_str());
}

TEST_CASE("DataController converts invalid request rows into InvalidRequest objects") {
    const std::string usersPath = "tests/tmp_invalid_users.csv";
    const std::string spacesPath = "tests/tmp_invalid_spaces.csv";
    const std::string requestsPath = "tests/tmp_invalid_requests.csv";

    writeCsv(
        usersPath,
        "userId,name,role\n"
        "1,Student One,Student\n"
    );
    writeCsv(
        spacesPath,
        "spaceId,type,name,capacity,hasProjector,hasWhiteboard,hasComputers,isAvailable,building\n"
        "301,MeetingRoom,M301,10,1,0,0,1,AdminBuilding\n"
    );
    writeCsv(
        requestsPath,
        "requestId,requestType,userId,spaceId,participantCount,requiredFeature,requiredBuilding,timeData\n"
        "1,OneTime,1,301,5,Projector,AdminBuilding,1-10-11\n"
        "2,OneTime,99,301,5,Projector,AdminBuilding,1-10-11\n"
        "3,OneTime,1,999,5,Projector,AdminBuilding,1-10-11\n"
        "4,OneTime,1,301,5,Projector,AdminBuilding,bad-time\n"
        "5,UnknownType,1,301,5,Projector,AdminBuilding,1-10-11\n"
        "5,OneTime,1,301,5,Projector,AdminBuilding,1-12-13\n"
        "bad,row\n"
    );

    DataController controller;
    SystemData data = controller.loadAllData(usersPath, spacesPath, requestsPath);

    CHECK_EQ(data.requests.size(), static_cast<size_t>(7));
    CHECK(dynamic_cast<InvalidRequest*>(data.requests[0]) == nullptr);
    CHECK(dynamic_cast<InvalidRequest*>(data.requests[1]) != nullptr);
    CHECK(dynamic_cast<InvalidRequest*>(data.requests[2]) != nullptr);
    CHECK(dynamic_cast<InvalidRequest*>(data.requests[3]) != nullptr);
    CHECK(dynamic_cast<InvalidRequest*>(data.requests[4]) != nullptr);
    CHECK(dynamic_cast<InvalidRequest*>(data.requests[5]) != nullptr);
    CHECK(dynamic_cast<InvalidRequest*>(data.requests[6]) != nullptr);
    CHECK_EQ(data.requests[1]->getRejectionReason(), std::string("Invalid user reference"));
    CHECK_EQ(data.requests[2]->getRejectionReason(), std::string("Invalid space reference"));
    CHECK_EQ(data.requests[3]->getRejectionReason(), std::string("Malformed input"));
    CHECK_EQ(data.requests[5]->getRejectionReason(), std::string("Duplicate request ID"));
    CHECK_EQ(data.requests[6]->getRejectionReason(), std::string("Malformed input"));

    CHECK_EQ(data.requests[0]->getTitle(), std::string("Untitled Request"));
    CHECK_EQ(data.requests[0]->getPurpose(), std::string("General"));

    controller.cleanupData(data);
    std::remove(usersPath.c_str());
    std::remove(spacesPath.c_str());
    std::remove(requestsPath.c_str());
}

TEST_CASE("DataController handles missing and empty request CSV files safely") {
    const std::string usersPath = "tests/tmp_missing_requests_users.csv";
    const std::string spacesPath = "tests/tmp_missing_requests_spaces.csv";
    const std::string emptyRequestsPath = "tests/tmp_empty_requests.csv";

    writeCsv(
        usersPath,
        "userId,name,role\n"
        "1,Student One,Student\n"
    );
    writeCsv(
        spacesPath,
        "spaceId,type,name,capacity,hasProjector,hasWhiteboard,hasComputers,isAvailable,building\n"
        "301,MeetingRoom,M301,10,1,0,0,1,AdminBuilding\n"
    );
    writeCsv(emptyRequestsPath, "");

    DataController controller;
    SystemData missingData =
        controller.loadAllData(usersPath, spacesPath, "tests/does_not_exist_requests.csv");
    SystemData emptyData =
        controller.loadAllData(usersPath, spacesPath, emptyRequestsPath);

    CHECK_EQ(missingData.users.size(), static_cast<size_t>(1));
    CHECK_EQ(missingData.spaces.size(), static_cast<size_t>(1));
    CHECK(missingData.requests.empty());
    CHECK_EQ(emptyData.users.size(), static_cast<size_t>(1));
    CHECK_EQ(emptyData.spaces.size(), static_cast<size_t>(1));
    CHECK(emptyData.requests.empty());

    controller.cleanupData(missingData);
    controller.cleanupData(emptyData);
    std::remove(usersPath.c_str());
    std::remove(spacesPath.c_str());
    std::remove(emptyRequestsPath.c_str());
}

TEST_CASE("DataController tolerates extra request columns after current schema") {
    const std::string usersPath = "tests/tmp_extra_users.csv";
    const std::string spacesPath = "tests/tmp_extra_spaces.csv";
    const std::string requestsPath = "tests/tmp_extra_requests.csv";

    writeCsv(
        usersPath,
        "userId,name,role\n"
        "1,Student One,Student\n"
    );
    writeCsv(
        spacesPath,
        "spaceId,type,name,capacity,hasProjector,hasWhiteboard,hasComputers,isAvailable,building\n"
        "301,MeetingRoom,M301,10,1,0,0,1,AdminBuilding\n"
    );
    writeCsv(
        requestsPath,
        "requestId,requestType,userId,spaceId,participantCount,requiredFeature,requiredBuilding,timeData,title,purpose,courseCode,courseName,examType,canSplitAcrossRooms,extra\n"
        "1,OneTime,1,301,5,Projector,AdminBuilding,1-10-11,Extra Column Request,Meeting,,,,false,ignored\n"
    );

    DataController controller;
    SystemData data = controller.loadAllData(usersPath, spacesPath, requestsPath);

    CHECK_EQ(data.requests.size(), static_cast<size_t>(1));
    CHECK(dynamic_cast<InvalidRequest*>(data.requests[0]) == nullptr);
    CHECK_EQ(data.requests[0]->getTitle(), std::string("Extra Column Request"));

    controller.cleanupData(data);
    std::remove(usersPath.c_str());
    std::remove(spacesPath.c_str());
    std::remove(requestsPath.c_str());
}

TEST_CASE("DataController converts negative request IDs into InvalidRequest objects") {
    const std::string usersPath = "tests/tmp_negative_request_users.csv";
    const std::string spacesPath = "tests/tmp_negative_request_spaces.csv";
    const std::string requestsPath = "tests/tmp_negative_request_requests.csv";

    writeCsv(
        usersPath,
        "userId,name,role\n"
        "1,Student One,Student\n"
    );
    writeCsv(
        spacesPath,
        "spaceId,type,name,capacity,hasProjector,hasWhiteboard,hasComputers,isAvailable,building\n"
        "301,MeetingRoom,M301,10,1,0,0,1,AdminBuilding\n"
    );
    writeCsv(
        requestsPath,
        "requestId,requestType,userId,spaceId,participantCount,requiredFeature,requiredBuilding,timeData,title,purpose,courseCode,courseName,examType,canSplitAcrossRooms\n"
        "-7,OneTime,1,301,5,Projector,AdminBuilding,1-10-11,Negative Request,Meeting,,,,false\n"
        "7,OneTime,1,301,5,Projector,AdminBuilding,1-11-12,Valid Request,Meeting,,,,false\n"
    );

    DataController controller;
    SystemData data = controller.loadAllData(usersPath, spacesPath, requestsPath);

    CHECK_EQ(data.requests.size(), static_cast<size_t>(2));
    CHECK(dynamic_cast<InvalidRequest*>(data.requests[0]) != nullptr);
    CHECK_EQ(data.requests[0]->getRejectionReason(), std::string("Invalid request ID"));
    CHECK(dynamic_cast<InvalidRequest*>(data.requests[1]) == nullptr);

    controller.cleanupData(data);
    std::remove(usersPath.c_str());
    std::remove(spacesPath.c_str());
    std::remove(requestsPath.c_str());
}

TEST_CASE("DataController loads custom auxiliary busy-slot and request-participant paths") {
    const std::string usersPath = "tests/tmp_aux_users.csv";
    const std::string spacesPath = "tests/tmp_aux_spaces.csv";
    const std::string requestsPath = "tests/tmp_aux_requests.csv";
    const std::string busySlotsPath = "tests/tmp_aux_user_busy_slots.csv";
    const std::string participantsPath = "tests/tmp_aux_request_participants.csv";

    writeCsv(
        usersPath,
        "userId,name,role\n"
        "1,Student One,Student\n"
        "2,Dr Aux,Instructor\n"
    );
    writeCsv(
        spacesPath,
        "spaceId,type,name,capacity,hasProjector,hasWhiteboard,hasComputers,isAvailable,building\n"
        "301,MeetingRoom,M301,10,1,0,0,1,AdminBuilding\n"
    );
    writeCsv(
        requestsPath,
        "requestId,requestType,userId,spaceId,participantCount,requiredFeature,requiredBuilding,timeData,title,purpose,courseCode,courseName,examType,canSplitAcrossRooms\n"
        "40,CommitteeMeeting,1,301,5,Projector,AdminBuilding,5-13:00-14:00,Aux Committee,Presentation,,,,false\n"
    );
    writeCsv(
        busySlotsPath,
        "userId,day,startTime,endTime,reason\n"
        "2,1,10:00,11:00,Lecture\n"
    );
    writeCsv(
        participantsPath,
        "requestId,userId,participantRole\n"
        "40,2,Supervisor\n"
    );

    DataController controller;
    SystemData data = controller.loadAllData(
        usersPath,
        spacesPath,
        requestsPath,
        busySlotsPath,
        participantsPath
    );

    CHECK_EQ(data.userBusySlots.size(), static_cast<size_t>(1));
    CHECK_EQ(data.requestParticipants.size(), static_cast<size_t>(1));
    CHECK_EQ(data.requests.size(), static_cast<size_t>(1));

    CommitteeMeetingRequest* committee =
        dynamic_cast<CommitteeMeetingRequest*>(data.requests[0]);
    REQUIRE(committee);
    CHECK_EQ(committee->getRequiredParticipantIds().size(), static_cast<size_t>(1));
    CHECK_EQ(committee->getRequiredParticipantIds()[0], 2);
    CHECK_EQ(committee->getParticipantRoles()[0], std::string("Supervisor"));
    CHECK(historyContains(*committee, "Loaded 1 required committee participant"));

    controller.cleanupData(data);
    std::remove(usersPath.c_str());
    std::remove(spacesPath.c_str());
    std::remove(requestsPath.c_str());
    std::remove(busySlotsPath.c_str());
    std::remove(participantsPath.c_str());
}

TEST_CASE("Session exports fresh normal-data smoke artifacts to isolated paths") {
    const std::string allocationsPath = "tests/tmp_smoke_allocations.csv";
    const std::string resultsPath = "tests/tmp_smoke_results.csv";
    const std::string requestSummariesPath = "tests/tmp_smoke_request_summaries.csv";
    const std::string allocationSummariesPath = "tests/tmp_smoke_allocation_summaries.csv";

    ResourceAllocationSession session;
    session.loadStrategyName("data/config.txt");
    CHECK(session.loadSystemData("data/users.csv", "data/spaces.csv", "data/requests.csv"));
    CHECK(session.runAllocation());
    CHECK(session.exportResults(allocationsPath, resultsPath,
                                requestSummariesPath, allocationSummariesPath));
    CHECK(fileExistsAndNotEmpty(allocationsPath));
    CHECK(fileExistsAndNotEmpty(resultsPath));
    CHECK(fileExistsAndNotEmpty(requestSummariesPath));
    CHECK(fileExistsAndNotEmpty(allocationSummariesPath));
    CHECK_FILE_CONTAINS(requestSummariesPath, "requestId");
    CHECK_FILE_CONTAINS(requestSummariesPath, "status");
    CHECK_FILE_CONTAINS(allocationSummariesPath, "assignedParticipants");

    session.cleanup();
    std::remove(allocationsPath.c_str());
    std::remove(resultsPath.c_str());
    std::remove(requestSummariesPath.c_str());
    std::remove(allocationSummariesPath.c_str());
}
