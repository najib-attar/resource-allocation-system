#include "test_framework.h"
#include "../src/integration/JsonEngineProtocol.h"
#include <sstream>

namespace {
using Json = nlohmann::json;
Json fixture(const std::string& type = "OneTime") {
    Json input = {
        {"protocolVersion", 1}, {"runId", "test-run"}, {"strategy", "greedy"},
        {"users", {{{"id", 1}, {"name", "Professor"}, {"role", "Instructor"}}}},
        {"spaces", {{{"id", 101}, {"name", "Room"}, {"type", "Classroom"}, {"capacity", 100},
                     {"available", true}, {"features", {{"projector", true}, {"whiteboard", true}, {"computers", false}}}}}},
        {"busySlots", Json::array()},
        {"requests", {{{"id", 1}, {"type", type}, {"requesterId", 1}, {"spaceId", 101}, {"participantCount", 10},
                      {"title", "Test"}, {"purpose", "Teaching"},
                      {"slots", {{{"day", 1}, {"startMinutes", 600}, {"endMinutes", 660}}}}}}}
    };
    if (type == "Exam") input["requests"][0]["exam"] = {{"courseCode", "CS1"}, {"courseName", "Algorithms"}, {"examType", "Final"}, {"canSplitAcrossRooms", true}};
    if (type == "CommitteeMeeting") {
        input["spaces"][0]["type"] = "MeetingRoom";
        input["requests"][0]["participants"] = {{{"userId", 1}, {"role", "Chair"}}};
    }
    return input;
}
void rejectedInput(const Json& input) {
    auto result = JsonEngineProtocol::execute(input);
    CHECK(result["status"] == "error");
    CHECK(!result["errors"].empty());
    CHECK(result["allocations"].empty());
}
}

TEST_CASE("JSON OneTime returns structured approval and capacity") {
    auto result = JsonEngineProtocol::execute(fixture());
    CHECK(result["status"] == "success");
    CHECK(result["requestResults"][0]["status"] == "Approved");
    CHECK(result["allocations"][0]["spaceCapacity"] == 100);
    CHECK(result["allocations"][0]["slot"]["startMinutes"] == 600);
}
TEST_CASE("JSON Recurring preserves each occurrence") {
    auto input = fixture("Recurring");
    input["requests"][0]["slots"].push_back({{"day", 2}, {"startMinutes", 600}, {"endMinutes", 660}});
    auto result = JsonEngineProtocol::execute(input);
    CHECK(result["allocations"].size() == 2);
}
TEST_CASE("JSON Exam splits rooms under both best-fit strategies") {
    for (auto strategy : {"multi_room_exam_greedy", "multi_room_exam_best_fit", "shared_room_exam_best_fit"}) {
        auto input = fixture("Exam");
        input["strategy"] = strategy;
        input["requests"][0]["participantCount"] = 120;
        auto second = input["spaces"][0]; second["id"] = 102; second["capacity"] = 30;
        input["spaces"].push_back(second);
        auto result = JsonEngineProtocol::execute(input);
        CHECK(result["requestResults"][0]["status"] == "Approved");
        CHECK(result["allocations"].size() == 2);
        CHECK(result["allocations"][0]["spaceId"] != result["allocations"][1]["spaceId"]);
        CHECK(result["allocations"][0]["assignedParticipants"].get<int>() + result["allocations"][1]["assignedParticipants"].get<int>() == 120);
    }
}
TEST_CASE("JSON shared exam uses remaining capacity") {
    auto input = fixture("Exam"); input["strategy"] = "shared_room_exam_best_fit";
    input["requests"][0]["participantCount"] = 60;
    auto secondRequest = input["requests"][0]; secondRequest["id"] = 2; secondRequest["participantCount"] = 50;
    input["requests"].push_back(secondRequest);
    auto secondRoom = input["spaces"][0]; secondRoom["id"] = 102; secondRoom["capacity"] = 20;
    input["spaces"].push_back(secondRoom);
    auto result = JsonEngineProtocol::execute(input);
    CHECK(result["allocations"].size() == 3);
    CHECK(result["requestResults"][1]["status"] == "Approved");
}
TEST_CASE("JSON Committee participant conflict exposes structured suggestions") {
    auto input = fixture("CommitteeMeeting");
    input["busySlots"] = {{{"userId", 1}, {"slot", input["requests"][0]["slots"][0]}, {"reason", "Lecture"}}};
    auto result = JsonEngineProtocol::execute(input);
    CHECK(result["requestResults"][0]["status"] == "Rejected");
    CHECK(!result["requestResults"][0]["rejectionReason"].get<std::string>().empty());
    CHECK(result["suggestions"][0]["items"].size() == 3);
    CHECK(result["suggestions"][0]["items"][0].contains("score"));
}
TEST_CASE("JSON capacity rejection is a successful execution decision") {
    auto input = fixture(); input["requests"][0]["participantCount"] = 101;
    auto result = JsonEngineProtocol::execute(input);
    CHECK(result["status"] == "success"); CHECK(result["requestResults"][0]["status"] == "Rejected");
    CHECK(result["allocations"].empty());
}
TEST_CASE("JSON empty request batch is valid") {
    auto input = fixture(); input["requests"] = Json::array();
    auto result = JsonEngineProtocol::execute(input);
    CHECK(result["status"] == "success"); CHECK(result["requestResults"].empty());
}
TEST_CASE("JSON strings preserve commas quotes Unicode newlines and empty values") {
    auto input = fixture();
    const std::string title = "Algorithms, \"Part II\" \xC3\x96\nSession";
    input["requests"][0]["title"] = title; input["requests"][0]["purpose"] = "";
    auto result = JsonEngineProtocol::execute(Json::parse(input.dump()));
    CHECK(result["requestResults"][0]["title"] == title);
}
TEST_CASE("JSON missing version fails explicitly") { auto input = fixture(); input.erase("protocolVersion"); rejectedInput(input); }
TEST_CASE("JSON unsupported version fails explicitly") { auto input = fixture(); input["protocolVersion"] = 2; rejectedInput(input); }
TEST_CASE("JSON missing and unknown strategy do not fall back") {
    auto input = fixture(); input.erase("strategy"); rejectedInput(input);
    input["strategy"] = "unknown"; rejectedInput(input);
}
TEST_CASE("JSON malformed request and unknown type fail") {
    auto input = fixture(); input["requests"][0] = "invalid"; rejectedInput(input);
    input = fixture(); input["requests"][0]["type"] = "Unknown"; rejectedInput(input);
}
TEST_CASE("JSON invalid numeric values and identifiers fail") {
    for (const auto& value : Json::array({-1, 1.5, true, "10", 2147483648LL})) {
        auto input = fixture(); input["requests"][0]["id"] = value; rejectedInput(input);
    }
    auto input = fixture(); input["requests"][0].erase("requesterId"); rejectedInput(input);
}
TEST_CASE("JSON missing domain references fail") {
    auto input = fixture(); input["requests"][0]["requesterId"] = 999; rejectedInput(input);
    input = fixture(); input["requests"][0]["spaceId"] = 999; rejectedInput(input);
}
TEST_CASE("JSON invalid time ranges fail") {
    for (auto time : {Json{{"day", 0}, {"startMinutes", 600}, {"endMinutes", 660}},
                      Json{{"day", 1}, {"startMinutes", 660}, {"endMinutes", 660}},
                      Json{{"day", 1}, {"startMinutes", -1}, {"endMinutes", 660}}}) {
        auto input = fixture(); input["requests"][0]["slots"][0] = time; rejectedInput(input);
    }
}
TEST_CASE("JSON malformed participants fail without leaking partially loaded objects") {
    auto input = fixture("CommitteeMeeting"); input["requests"][0]["participants"] = "not-array"; rejectedInput(input);
    input = fixture("CommitteeMeeting"); input["requests"][0]["participants"][0]["userId"] = 999; rejectedInput(input);
}
TEST_CASE("JSON invalid room information and roles fail") {
    auto input = fixture(); input["spaces"][0]["capacity"] = -1; rejectedInput(input);
    input = fixture(); input["spaces"][0]["type"] = "Unknown"; rejectedInput(input);
    input = fixture(); input["users"][0]["role"] = "Unknown"; rejectedInput(input);
}
TEST_CASE("JSON duplicate identifiers fail") {
    for (auto collection : {"users", "spaces", "requests"}) {
        auto input = fixture(); input[collection].push_back(input[collection][0]); rejectedInput(input);
    }
}
TEST_CASE("JSON profiles features and availability reach existing domain rules") {
    auto input = fixture();
    input["users"][0]["role"] = "TeachingAssistant";
    input["users"][0]["email"] = "assistant@example.test";
    input["users"][0]["assignedRoles"] = {"TeachingAssistant"};
    input["requests"][0]["requiredFeature"] = "Projector";
    auto result = JsonEngineProtocol::execute(input);
    CHECK(result["requestResults"][0]["priority"] == 2);
    CHECK(result["requestResults"][0]["status"] == "Approved");
    input["spaces"][0]["features"]["projector"] = false;
    result = JsonEngineProtocol::execute(input);
    CHECK(result["requestResults"][0]["rejectionReason"] == "Required feature missing");
    input["spaces"][0]["features"]["projector"] = true;
    input["spaces"][0]["available"] = false;
    result = JsonEngineProtocol::execute(input);
    CHECK(result["requestResults"][0]["status"] == "Rejected");
    input["spaces"][0]["available"] = "false";
    rejectedInput(input);
}
TEST_CASE("JSON stream mode emits exactly one document and uses failure exit code") {
    std::istringstream input(fixture().dump()); std::ostringstream output, diagnostics;
    CHECK_EQ(JsonEngineProtocol::run(input, output, diagnostics), 0);
    CHECK(Json::parse(output.str())["status"] == "success");
    std::istringstream invalid("{broken"); std::ostringstream failed;
    CHECK_EQ(JsonEngineProtocol::run(invalid, failed, diagnostics), 2);
    CHECK(Json::parse(failed.str())["errors"][0]["code"] == "MALFORMED_JSON");
}
