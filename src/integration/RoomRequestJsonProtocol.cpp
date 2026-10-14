#include "RoomRequestJsonProtocol.h"
#include "../services/RoomSelectionService.h"
#include "../models/SpaceFactory.h"
#include "../vendor/nlohmann/json.hpp"
#include <algorithm>
#include <iostream>
#include <set>
#include <stdexcept>

using nlohmann::json;
namespace {
std::int64_t integer(const json& value, std::int64_t low, std::int64_t high) {
    if (!value.is_number_integer()) throw std::invalid_argument("Expected an integer.");
    auto n = value.get<std::int64_t>();
    if (n < low || n > high) throw std::invalid_argument("Integer outside allowed range.");
    return n;
}
bool flag(const json& value) {
    if (!value.is_boolean()) throw std::invalid_argument("Expected a boolean.");
    return value.get<bool>();
}
std::string label(const json& value, std::size_t limit = 2000) {
    if (!value.is_string() || value.get_ref<const std::string&>().size() > limit) throw std::invalid_argument("Invalid bounded text.");
    return value.get<std::string>();
}
DatedInterval interval(const json& value) {
    DatedInterval slot{integer(value.at("start"),0,4102444800LL),integer(value.at("end"),1,4102444800LL)};
    if (slot.start >= slot.end || slot.start % 60 || slot.end % 60) throw std::invalid_argument("Invalid minute-aligned interval.");
    return slot;
}
std::vector<DatedInterval> intervals(const json& value) {
    if (!value.is_array() || value.size() > 100000) throw std::invalid_argument("Invalid interval collection.");
    std::vector<DatedInterval> values;
    for (const auto& row : value) values.push_back(interval(row));
    return values;
}
std::vector<std::string> strings(const json& value, const std::set<std::string>& allowed) {
    if (!value.is_array() || value.size() > allowed.size()) throw std::invalid_argument("Invalid policy/facility list.");
    std::vector<std::string> result;
    std::set<std::string> seen;
    for (const auto& row : value) {
        auto text = label(row,100);
        if (!allowed.count(text) || !seen.insert(text).second) throw std::invalid_argument("Unknown or duplicate policy/facility.");
        result.push_back(text);
    }
    return result;
}
json candidate(const StudentRoomCandidate& value) {
    return {{"roomId",value.roomId},{"facultyId",value.facultyId},{"capacity",value.capacity},
            {"spareSeats",value.spareSeats},{"extraFacilities",value.extraFacilities},{"preferencePenalty",value.preferencePenalty},
            {"start",value.interval.start},{"end",value.interval.end},{"reason",value.reason}};
}
}

int RoomRequestJsonProtocol::run(std::istream& stream, std::ostream& out, std::ostream& diagnostics) {
    json result{{"protocolVersion",1},{"operation","studentRoom"},{"engineVersion","student-rooms-1"},
                {"runId",""},{"status","error"},{"feasible",false},{"reasonCode","INVALID_INPUT"},
                {"candidates",json::array()},{"alternatives",json::array()},{"explanations",json::array()},{"errors",json::array()}};
    try {
        std::string raw;
        char ch;
        while (stream.get(ch)) {
            if (raw.size() >= 16*1024*1024) throw std::invalid_argument("Input exceeds 16 MiB.");
            raw.push_back(ch);
        }
        auto input = json::parse(raw);
        integer(input.at("protocolVersion"),1,1);
        if (input.at("operation") != "studentRoom") throw std::invalid_argument("Unsupported operation.");
        auto runId = label(input.at("runId"),100);
        if (runId.empty()) throw std::invalid_argument("Missing run identifier.");
        result["runId"] = runId;
        auto action = label(input.at("action"),100);
        if (action != "recommend" && action != "validate" && action != "attendance") throw std::invalid_argument("Unknown action.");
        RoomSelectionInput data;
        data.organizerId = static_cast<int>(integer(input.at("organizerId"),1,2147483647));
        if (label(input.at("organizerRole")) != (action == "attendance" ? "Instructor" : "Student")) throw std::invalid_argument("Invalid organizer role.");
        data.attendeeCount = static_cast<int>(integer(input.at("attendeeCount"),1,2147483647));
        data.category = label(input.at("category"),100);
        const std::set<std::string> categories{"study","meeting","lecture","club","other"};
        if (!categories.count(data.category)) throw std::invalid_argument("Unsupported category.");
        data.strategy = label(input.at("strategy"),100);
        if (data.strategy != "best_fit" && data.strategy != "greedy") throw std::invalid_argument("Unsupported room strategy.");
        data.requiredFeatures = strings(input.at("requiredFeatures"),{"projector","whiteboard","computers"});
        data.preferredFacultyId = static_cast<int>(integer(input.at("preferredFacultyId"),0,2147483647));
        data.preferredBuilding = label(input.at("preferredBuilding"));
        data.organizerResolved = flag(input.at("organizerResolved"));
        data.organizerBusy = intervals(input.at("organizerBusy"));
        data.proposed = interval(input.at("proposed"));
        data.horizon = interval(input.at("horizon"));
        auto duration = data.proposed.end-data.proposed.start;
        if (duration > 86400 || data.horizon.end-data.horizon.start > 32*86400LL || data.proposed.start < data.horizon.start || data.proposed.end > data.horizon.end)
            throw std::invalid_argument("Invalid duration or search horizon.");
        const auto& rooms = input.at("rooms");
        if (!rooms.is_array() || rooms.size()>10000) throw std::invalid_argument("Invalid room collection.");
        std::set<int> ids;
        for (const auto& row : rooms) {
            StudentRoomOption room;
            int id = static_cast<int>(integer(row.at("id"),1,2147483647));
            if (!ids.insert(id).second) throw std::invalid_argument("Duplicate room identifier.");
            const auto& features = row.at("features");
            room.space.reset(SpaceFactory::createSpace(id,label(row.at("name")),label(row.at("type")),
                static_cast<int>(integer(row.at("capacity"),1,2147483647)),flag(features.at("projector")),flag(features.at("whiteboard")),
                flag(features.at("computers")),flag(row.at("available")),label(row.at("building"))));
            if (!room.space) throw std::invalid_argument("Unknown room type.");
            room.facultyId = static_cast<int>(integer(row.at("facultyId"),0,2147483647));
            room.approverId = static_cast<int>(integer(row.at("approverId"),0,2147483647));
            room.enabled = flag(row.at("enabled"));
            room.restricted = flag(row.at("restricted"));
            room.calendarResolved = flag(row.at("calendarResolved"));
            room.categories = strings(row.at("categories"),categories);
            if (!row.at("allowedUserIds").is_array() || row.at("allowedUserIds").size()>10000) throw std::invalid_argument("Invalid whitelist.");
            std::set<int> whitelist;
            for (const auto& uid : row.at("allowedUserIds")) {
                int n = static_cast<int>(integer(uid,1,2147483647));
                if (!whitelist.insert(n).second) throw std::invalid_argument("Duplicate whitelist identifier.");
                room.allowedUserIds.push_back(n);
            }
            room.busy = intervals(row.at("busy"));
            data.rooms.push_back(std::move(room));
        }
        result["status"] = "success";
        auto reason = RoomSelectionService::organizerReason(data,data.proposed);
        if (action == "attendance") {
            result["feasible"] = reason == "AVAILABLE";
            result["reasonCode"] = reason;
        } else {
            auto ranked = RoomSelectionService::rank(data,data.proposed);
            if (action == "validate") {
                int chosen = static_cast<int>(integer(input.at("selectedRoomId"),1,2147483647));
                ranked.erase(std::remove_if(ranked.begin(),ranked.end(),[&](const auto& c){return c.roomId!=chosen;}),ranked.end());
            }
            for (const auto& row : ranked) if (result["candidates"].size()<20) result["candidates"].push_back(candidate(row));
            result["feasible"] = !ranked.empty();
            result["reasonCode"] = !ranked.empty() ? "AVAILABLE" : reason != "AVAILABLE" ? reason : "NO_ELIGIBLE_ROOM";
            std::set<std::string> explanations;
            for (const auto& room : data.rooms) {
                auto value = RoomSelectionService::roomReason(data,room,data.proposed);
                if (value != "AVAILABLE") explanations.insert(value);
            }
            if (reason != "AVAILABLE") explanations.insert(reason);
            result["explanations"] = explanations;
            if (action == "recommend" && ranked.empty()) {
                for (auto t=data.horizon.start; t+duration<=data.horizon.end && result["alternatives"].size()<5; t+=900) {
                    if (t == data.proposed.start) continue;
                    auto values = RoomSelectionService::rank(data,{t,t+duration});
                    if (!values.empty()) result["alternatives"].push_back(candidate(values.front()));
                }
            }
        }
        out << result.dump() << '\n';
        return 0;
    } catch (const json::exception& error) {
        diagnostics << "Room protocol validation failed: " << error.what() << '\n';
        result["status"]="error";
        result["errors"].push_back({{"code","INVALID_INPUT"},{"message","Malformed or incomplete room document."}});
    } catch (const std::invalid_argument& error) {
        diagnostics << "Room validation failed: " << error.what() << '\n';
        result["status"]="error";
        result["errors"].push_back({{"code","INVALID_INPUT"},{"message",error.what()}});
    }
    out << result.dump() << '\n';
    return 2;
}
