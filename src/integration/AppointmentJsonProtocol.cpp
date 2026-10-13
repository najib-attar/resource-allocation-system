#include "AppointmentJsonProtocol.h"
#include "../services/AppointmentSchedulingService.h"
#include "../vendor/nlohmann/json.hpp"
#include <algorithm>
#include <iostream>
#include <set>
#include <stdexcept>

using nlohmann::json;
namespace {
std::int64_t integer(const json& value, std::int64_t low, std::int64_t high) {
    if (!value.is_number_integer()) throw std::invalid_argument("Expected an integer.");
    auto number = value.get<std::int64_t>();
    if (number < low || number > high) throw std::invalid_argument("Integer outside allowed range.");
    return number;
}
DatedInterval interval(const json& value) {
    DatedInterval result{integer(value.at("start"), 0, 4102444800LL), integer(value.at("end"), 1, 4102444800LL)};
    if (result.start >= result.end) throw std::invalid_argument("Interval must have start before end.");
    return result;
}
std::vector<int> identifiers(const json& value, std::size_t limit = 100) {
    if (!value.is_array() || value.size() > limit) throw std::invalid_argument("Expected a bounded identifier list.");
    std::vector<int> result;
    std::set<int> seen;
    for (const auto& item : value) {
        int id = static_cast<int>(integer(item, 1, 2147483647));
        if (!seen.insert(id).second) throw std::invalid_argument("Duplicate participant identifier.");
        result.push_back(id);
    }
    return result;
}
json candidate(const AppointmentCandidate& value) {
    return {{"start", value.interval.start}, {"end", value.interval.end},
            {"availableInvitees", value.availableInvitees}, {"unavailableInvitees", value.unavailableInvitees},
            {"unresolvedInvitees", value.unresolvedInvitees}, {"preferenceDistanceSeconds", value.preferenceDistance},
            {"reason", "Mandatory participants are available within published professor hours; ranked by known-free invitees, preferred-time distance, then time."}};
}
}

int AppointmentJsonProtocol::run(std::istream& stream, std::ostream& output, std::ostream& diagnostics) {
    json response{{"protocolVersion", 1}, {"operation", "appointment"}, {"engineVersion", "appointments-1"},
                  {"runId", ""}, {"status", "error"}, {"feasible", false}, {"reasonCode", "INVALID_INPUT"},
                  {"recommendations", json::array()}, {"errors", json::array()}};
    try {
        std::string raw;
        char character;
        while (stream.get(character)) {
            if (raw.size() >= 16 * 1024 * 1024) throw std::invalid_argument("Input exceeds 16 MiB.");
            raw.push_back(character);
        }
        const auto input = json::parse(raw);
        if (integer(input.at("protocolVersion"), 1, 1) != 1 || input.at("operation") != "appointment")
            throw std::invalid_argument("Unsupported appointment protocol.");
        if (!input.at("runId").is_string() || input.at("runId").get<std::string>().empty() || input.at("runId").get<std::string>().size() > 100)
            throw std::invalid_argument("Invalid runId.");
        response["runId"] = input.at("runId");
        const std::string action = input.at("action").get<std::string>();
        if (action != "validate" && action != "recommend") throw std::invalid_argument("Unknown appointment action.");
        AppointmentSchedulingInput data;
        data.organizerId = static_cast<int>(integer(input.at("organizerId"), 1, 2147483647));
        data.professorIds = identifiers(input.at("professorIds"));
        data.invitedIds = identifiers(input.at("invitedIds"));
        data.unresolvedIds = identifiers(input.at("unresolvedIds"), 201);
        if (data.professorIds.empty()) throw std::invalid_argument("At least one professor is required.");
        std::set<int> people{data.organizerId};
        for (int id : data.professorIds) if (!people.insert(id).second) throw std::invalid_argument("Participant roles overlap.");
        for (int id : data.invitedIds) if (!people.insert(id).second) throw std::invalid_argument("Participant roles overlap.");
        for (int id : data.unresolvedIds) if (!people.count(id)) throw std::invalid_argument("Unknown unresolved participant.");
        data.durationMinutes = static_cast<int>(integer(input.at("durationMinutes"), 1, 1440));
        data.horizon = interval(input.at("horizon"));
        if (data.horizon.end - data.horizon.start > 32 * 86400LL) throw std::invalid_argument("Search horizon exceeds 32 days.");
        if (input.contains("preferredStart") && !input["preferredStart"].is_null()) data.preferredStart = integer(input["preferredStart"], 0, 4102444800LL);
        for (const std::string key : {"published", "busy"}) {
            if (!input.at(key).is_array() || input.at(key).size() > 100000) throw std::invalid_argument("Invalid interval list.");
            for (const auto& entry : input.at(key)) {
                int id = static_cast<int>(integer(entry.at("userId"), 1, 2147483647));
                if (!people.count(id)) throw std::invalid_argument("Unknown interval participant.");
                (key == "published" ? data.published : data.busy)[id].push_back(interval(entry));
            }
        }
        response["status"] = "success";
        if (action == "validate") {
            auto proposed = interval(input.at("proposed"));
            response["reasonCode"] = AppointmentSchedulingService::validate(data, proposed);
            response["feasible"] = response["reasonCode"] == "AVAILABLE";
            if (response["feasible"] == true) response["recommendations"].push_back(candidate(AppointmentSchedulingService::describe(data, proposed)));
        } else {
            auto values = AppointmentSchedulingService::recommend(data, static_cast<int>(integer(input.value("limit", json(20)), 1, 100)));
            for (const auto& value : values) response["recommendations"].push_back(candidate(value));
            response["feasible"] = !values.empty();
            response["reasonCode"] = values.empty() ? "NO_FEASIBLE_TIME" : "AVAILABLE";
            for (int id : data.unresolvedIds)
                if (id == data.organizerId || std::find(data.professorIds.begin(), data.professorIds.end(), id) != data.professorIds.end())
                    response["reasonCode"] = "UNRESOLVED_CALENDAR";
        }
        output << response.dump() << '\n';
        return 0;
    } catch (const json::exception& error) {
        diagnostics << "Appointment protocol validation failed: " << error.what() << '\n';
        response["status"] = "error";
        response["errors"].push_back({{"code", "INVALID_INPUT"}, {"message", "Malformed or incomplete appointment protocol document."}});
    } catch (const std::invalid_argument& error) {
        diagnostics << "Appointment validation failed: " << error.what() << '\n';
        response["status"] = "error";
        response["errors"].push_back({{"code", "INVALID_INPUT"}, {"message", error.what()}});
    }
    output << response.dump() << '\n';
    return 2;
}
