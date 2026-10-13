#include "test_framework.h"
#include "src/services/AppointmentSchedulingService.h"
#include "src/integration/AppointmentJsonProtocol.h"
#include "src/vendor/nlohmann/json.hpp"
#include <sstream>

namespace {
AppointmentSchedulingInput fixture() {
    return {1, {2, 3}, {4, 5}, {}, 60, {1800000000, 1800086400}, 0,
            {{2, {{1800000000, 1800010800}}}, {3, {{1800000000, 1800010800}}}}, {}};
}
}
TEST_CASE("Appointments require every professor publication and organizer availability") {
    auto input = fixture();
    CHECK_EQ(AppointmentSchedulingService::validate(input, {1800000000, 1800003600}), "AVAILABLE");
    input.busy[1].push_back({1800000000, 1800003600});
    CHECK_EQ(AppointmentSchedulingService::validate(input, {1800000000, 1800003600}), "ORGANIZER_BUSY");
    CHECK_EQ(AppointmentSchedulingService::validate(input, {1800003600, 1800007200}), "AVAILABLE");
    input.published.erase(3);
    CHECK_EQ(AppointmentSchedulingService::validate(input, {1800003600, 1800007200}), "OUTSIDE_PUBLISHED_AVAILABILITY");
}
TEST_CASE("Optional invitees rank appointments without blocking feasibility") {
    auto input = fixture();
    input.busy[4].push_back({1800000000, 1800003600});
    input.unresolvedIds = {5};
    auto values = AppointmentSchedulingService::recommend(input, 20);
    CHECK(!values.empty());
    CHECK_EQ(values.front().interval.start, 1800003600);
    CHECK_EQ(values.front().availableInvitees.size(), std::size_t(1));
    CHECK_EQ(values.front().unresolvedInvitees.size(), std::size_t(1));
    CHECK_EQ(AppointmentSchedulingService::validate(input, {1800000000, 1800003600}), "AVAILABLE");
}
TEST_CASE("Unknown mandatory legacy calendars fail safely") {
    auto input = fixture();
    input.unresolvedIds = {1};
    CHECK(AppointmentSchedulingService::recommend(input, 10).empty());
    CHECK_EQ(AppointmentSchedulingService::validate(input, {1800000000, 1800003600}), "UNRESOLVED_CALENDAR");
}
TEST_CASE("Dated weeks do not share weekday-only conflicts") {
    auto input = fixture();
    input.busy[2].push_back({1800000000 - 7 * 86400, 1800003600 - 7 * 86400});
    CHECK_EQ(AppointmentSchedulingService::validate(input, {1800000000, 1800003600}), "AVAILABLE");
    input.busy[2].push_back({1800000000, 1800003600});
    CHECK_EQ(AppointmentSchedulingService::validate(input, {1800000000, 1800003600}), "REQUIRED_PARTICIPANT_BUSY");
}
TEST_CASE("Adjacent publication windows cover one appointment") {
    auto input = fixture();
    input.published[2] = {{1800000000, 1800001800}, {1800001800, 1800003600}};
    CHECK_EQ(AppointmentSchedulingService::validate(input, {1800000000, 1800003600}), "AVAILABLE");
}
TEST_CASE("Appointment protocol rejects malformed input with protocol-only stdout") {
    for (const auto raw : {"{}", "{broken", "{\"protocolVersion\":2}"}) {
        std::istringstream in(raw);
        std::ostringstream out, diagnostic;
        CHECK_EQ(AppointmentJsonProtocol::run(in, out, diagnostic), 2);
        auto response = nlohmann::json::parse(out.str());
        CHECK_EQ(response["status"].get<std::string>(), "error");
        CHECK(!diagnostic.str().empty());
    }
}
TEST_CASE("Appointment protocol validates and recommends without changing allocation v1") {
    nlohmann::json input = {{"protocolVersion",1},{"operation","appointment"},{"runId","test"},{"action","recommend"},
        {"organizerId",1},{"professorIds",{2}},{"invitedIds",nlohmann::json::array()}, {"unresolvedIds",nlohmann::json::array()},
        {"durationMinutes",60},{"horizon",{{"start",1800000000},{"end",1800086400}}},
        {"published", {{{"userId",2},{"start",1800000000},{"end",1800010800}}}}, {"busy",nlohmann::json::array()}};
    std::istringstream in(input.dump());
    std::ostringstream out, diagnostics;
    CHECK_EQ(AppointmentJsonProtocol::run(in,out,diagnostics),0);
    auto response = nlohmann::json::parse(out.str());
    CHECK(response["feasible"].get<bool>());
    CHECK_EQ(response["recommendations"].size(),std::size_t(9));
    CHECK(diagnostics.str().empty());
}
TEST_CASE("Appointment protocol supports unresolved calendars for the full participant batch") {
    nlohmann::json professors = nlohmann::json::array(), invited = nlohmann::json::array(), unresolved = nlohmann::json::array();
    for (int id = 1; id <= 201; ++id) {
        unresolved.push_back(id);
        if (id >= 2 && id <= 101) professors.push_back(id);
        if (id >= 102) invited.push_back(id);
    }
    nlohmann::json input = {{"protocolVersion",1},{"operation","appointment"},{"runId","large-batch"},{"action","recommend"},
        {"organizerId",1},{"professorIds",professors},{"invitedIds",invited},{"unresolvedIds",unresolved}, {"durationMinutes",30},
        {"horizon",{{"start",1800000000},{"end",1800086400}}},{"published",nlohmann::json::array()},{"busy",nlohmann::json::array()}};
    std::istringstream in(input.dump());
    std::ostringstream out, diagnostics;
    CHECK_EQ(AppointmentJsonProtocol::run(in,out,diagnostics),0);
    auto response = nlohmann::json::parse(out.str());
    CHECK_EQ(response["reasonCode"].get<std::string>(),"UNRESOLVED_CALENDAR");
    CHECK(!response["feasible"].get<bool>());
}
