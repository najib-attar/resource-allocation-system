#include "JsonEngineProtocol.h"
#include "../services/ResourceAllocationSession.h"
#include "../models/UserFactory.h"
#include "../models/SpaceFactory.h"
#include "../models/RequestFactory.h"
#include <iostream>
#include <limits>
#include <map>
#include <memory>
#include <set>
#include <sstream>
#include <stdexcept>

namespace {
using Json = nlohmann::json;
const std::string engineVersion = "allocation-engine-json-1";
const std::set<std::string> strategies = {
    "greedy", "priority", "multi_room_exam_greedy", "multi_room_exam_best_fit",
    "shared_room_exam_best_fit"
};

struct InputError : std::runtime_error {
    std::string code;
    InputError(const std::string& code, const std::string& message)
        : std::runtime_error(message), code(code) {}
};

void require(bool condition, const std::string& path) {
    if (!condition) throw InputError("INVALID_INPUT", "Invalid or missing " + path);
}

std::string text(const Json& item, const std::string& key, bool required = false) {
    require(item.is_object(), key + " object");
    if (!item.contains(key)) {
        require(!required, key);
        return "";
    }
    require(item[key].is_string(), key);
    auto value = item[key].get<std::string>();
    require(!required || !value.empty(), key);
    return value;
}

int number(const Json& item, const std::string& key, int minimum = 0, int maximum = std::numeric_limits<int>::max()) {
    require(item.is_object() && item.contains(key), key);
    const auto& value = item[key];
    require(value.is_number_integer() && value >= minimum && value <= maximum, key);
    return value.get<int>();
}

bool flag(const Json& item, const std::string& key) {
    require(item.is_object() && item.contains(key) && item[key].is_boolean(), key);
    return item[key].get<bool>();
}

const Json& list(const Json& item, const char* key) {
    require(item.is_object() && item.contains(key) && item[key].is_array() && item[key].size() <= 10000, key);
    return item[key];
}

TimeSlot slot(const Json& value) {
    const int day = number(value, "day", 1, 7);
    const int start = number(value, "startMinutes", 0, 1439);
    const int end = number(value, "endMinutes", 1, 1440);
    require(TimeSlot::isValid(day, start, end), "time range");
    return TimeSlot::fromMinutes(day, start, end);
}

Json slotJson(const TimeSlot& value) {
    return {{"day", value.getDay()}, {"startMinutes", value.getStartMinutes()},
            {"endMinutes", value.getEndMinutes()}};
}

Json envelope(const std::string& runId, const std::string& strategy, const std::string& status) {
    return {{"protocolVersion", JsonEngineProtocol::Version}, {"engineVersion", engineVersion},
            {"runId", runId}, {"strategy", strategy}, {"status", status},
            {"requestResults", Json::array()}, {"allocations", Json::array()},
            {"suggestions", Json::array()}, {"errors", Json::array()}};
}

// Own every object during validation. Ownership transfers only after all input is valid.
struct DomainInput {
    std::vector<std::unique_ptr<User>> users;
    std::vector<std::unique_ptr<Space>> spaces;
    std::vector<std::unique_ptr<Request>> requests;
    SystemData data;
};

Json executeValidated(const Json& input) {
    require(input.is_object(), "execution object");
    require(number(input, "protocolVersion", 1) == JsonEngineProtocol::Version, "protocolVersion");
    const auto runId = text(input, "runId", true);
    const auto strategy = text(input, "strategy", true);
    if (!strategies.count(strategy)) throw InputError("UNKNOWN_STRATEGY", "Unknown strategy: " + strategy);
    DomainInput domain;
    std::map<int, User*> users;
    std::map<int, Space*> spaces;
    std::set<int> requestIds;
    for (const auto& value : list(input, "users")) {
        const int id = number(value, "id", 1);
        require(!users.count(id), "duplicate user id");
        UserProfileData profile;
        profile.email = text(value, "email");
        if (value.contains("status")) profile.status = text(value, "status");
        profile.primaryUnitName = text(value, "primaryUnit");
        profile.studentNo = text(value, "studentNo");
        profile.program = text(value, "program");
        if (value.contains("yearLevel")) profile.yearLevel = number(value, "yearLevel");
        profile.title = text(value, "title");
        profile.officeRoom = text(value, "officeRoom");
        profile.assistantType = text(value, "assistantType");
        profile.jobTitle = text(value, "jobTitle");
        profile.adminLevel = text(value, "adminLevel");
        if (value.contains("assignedRoles")) {
            for (const auto& role : list(value, "assignedRoles")) {
                require(role.is_string(), "assignedRoles entry");
                profile.assignedRoleNames.push_back(role.get<std::string>());
            }
        }
        domain.users.emplace_back(UserFactory::createUser(id, text(value, "name", true), text(value, "role", true), profile));
        require(domain.users.back() != nullptr, "user role");
        users[id] = domain.users.back().get();
        domain.data.users.push_back(users[id]);
    }
    for (const auto& value : list(input, "spaces")) {
        const int id = number(value, "id", 1);
        require(!spaces.count(id), "duplicate space id");
        require(value.contains("features") && value["features"].is_object(), "features");
        const auto& features = value["features"];
        domain.spaces.emplace_back(SpaceFactory::createSpace(id, text(value, "name", true), text(value, "type", true),
            number(value, "capacity", 1), flag(features, "projector"), flag(features, "whiteboard"),
            flag(features, "computers"), flag(value, "available"), text(value, "building")));
        require(domain.spaces.back() != nullptr, "space type");
        spaces[id] = domain.spaces.back().get();
        domain.data.spaces.push_back(spaces[id]);
    }
    for (const auto& value : list(input, "busySlots")) {
        const int id = number(value, "userId", 1);
        require(users.count(id) && value.contains("slot"), "busy slot user/slot");
        domain.data.userBusySlots.emplace_back(id, slot(value["slot"]), text(value, "reason"));
    }
    for (const auto& value : list(input, "requests")) {
        const int id = number(value, "id", 1);
        require(requestIds.insert(id).second, "duplicate request id");
        const auto type = text(value, "type", true);
        require(type == "OneTime" || type == "Recurring" || type == "Exam" || type == "CommitteeMeeting", "request type");
        const int userId = number(value, "requesterId", 1);
        const int spaceId = number(value, "spaceId", 1);
        require(users.count(userId) && spaces.count(spaceId), "request user/space reference");
        const auto& slots = list(value, "slots");
        require(!slots.empty() && (type == "Recurring" || slots.size() == 1), "request slots");
        std::string times;
        for (const auto& time : slots) {
            auto parsed = slot(time);
            if (!times.empty()) times += ";";
            times += std::to_string(parsed.getDay()) + "-" + parsed.getStartTimeString() + "-" + parsed.getEndTimeString();
        }
        std::string code, name, examType;
        bool split = false;
        if (type == "Exam") {
            require(value.contains("exam") && value["exam"].is_object(), "exam");
            code = text(value["exam"], "courseCode");
            name = text(value["exam"], "courseName");
            examType = text(value["exam"], "examType");
            split = flag(value["exam"], "canSplitAcrossRooms");
        }
        domain.requests.emplace_back(RequestFactory::createRequest(id, type, users.at(userId), spaces.at(spaceId),
            number(value, "participantCount", 1), text(value, "title"), text(value, "purpose"),
            text(value, "requiredFeature"), text(value, "requiredBuilding"), times, code, name, examType, split));
        auto* request = domain.requests.back().get();
        if (auto* committee = dynamic_cast<CommitteeMeetingRequest*>(request)) {
            std::set<int> participants;
            for (const auto& participant : list(value, "participants")) {
                const int participantId = number(participant, "userId", 1);
                require(users.count(participantId) && participants.insert(participantId).second, "participant reference/duplicate");
                const auto role = text(participant, "role");
                committee->addRequiredParticipant(participantId, role.empty() ? "Participant" : role);
                domain.data.requestParticipants.emplace_back(id, participantId, role.empty() ? "Participant" : role);
            }
        }
        domain.data.requests.push_back(request);
    }

    ResourceAllocationSession session;
    // After transfer the session owns all raw pointers, including on engine exceptions.
    SystemData transferred = std::move(domain.data);
    for (auto& value : domain.requests) value.release();
    for (auto& value : domain.spaces) value.release();
    for (auto& value : domain.users) value.release();
    session.initialize(std::move(transferred), strategy);
    if (!session.runAllocation()) throw std::runtime_error("Allocation session did not run");
    auto output = envelope(runId, strategy, "success");
    std::size_t requestIndex = 0;
    for (const auto* request : session.getSystemData().requests) {
        const bool approved = request->getStatus() == RequestStatus::Approved;
        const auto& reason = request->getRejectionReason();
        const auto& original = input["requests"][requestIndex++];
        std::int64_t assigned = 0;
        auto allocationIds = Json::array();
        auto allocatedSpaceIds = Json::array();
        for (const auto& allocation : session.getAllocations()) {
            if (allocation.getRequestId() == request->getId()) {
                assigned += allocation.getAssignedParticipants();
                allocationIds.push_back(allocation.getId());
                allocatedSpaceIds.push_back(allocation.getSpace()->getId());
            }
        }
        output["requestResults"].push_back({{"requestId", request->getId()}, {"requestType", request->getRequestType()},
            {"title", request->getTitle()}, {"purpose", request->getPurpose()},
            {"requesterName", request->getRequester()->getName()}, {"requesterRole", request->getRequester()->getRoleName()},
            {"priority", request->getPriority()}, {"status", approved ? "Approved" : "Rejected"},
            {"reasonCode", approved ? "APPROVED" : "REQUEST_REJECTED"}, {"rejectionReason", reason},
            {"history", request->getLifecycleHistory()}, {"requesterId", request->getRequester()->getId()},
            {"participantCount", request->getParticipantCount()}, {"requestedSpaceId", request->getRequestedSpace()->getId()},
            {"slots", original["slots"]}, {"requiredFeature", request->getRequiredFeature()},
            {"requiredBuilding", request->getRequiredBuilding()}, {"assignedParticipants", assigned},
            {"allocationCount", allocationIds.size()}, {"allocationIds", allocationIds}, {"allocatedSpaceIds", allocatedSpaceIds},
            {"participants", request->getRequestType() == "CommitteeMeeting" ? original["participants"] : Json::array()},
            {"exam", request->getRequestType() == "Exam" ? original["exam"] : Json::object()}});
    }
    for (const auto& allocation : session.getAllocations()) {
        const auto* space = allocation.getSpace();
        output["allocations"].push_back({{"allocationId", allocation.getId()}, {"requestId", allocation.getRequestId()},
            {"spaceId", space->getId()}, {"spaceName", space->getName()}, {"spaceType", space->getType()},
            {"building", space->getBuilding()}, {"spaceCapacity", space->getCapacity()},
            {"slot", slotJson(allocation.getTimeSlot())}, {"assignedParticipants", allocation.getAssignedParticipants()},
            {"requiredParticipantIds", allocation.getRequiredParticipantIds()}});
    }
    for (const auto& entry : session.getMeetingSuggestions()) {
        auto suggestions = Json::array();
        for (const auto& suggestion : entry.second) {
            suggestions.push_back({{"spaceId", suggestion.getSpaceId()}, {"slot", slotJson(suggestion.getTimeSlot())},
                {"score", suggestion.getScore()}, {"timeDistanceMinutes", suggestion.getTimeDistanceMinutes()},
                {"dayDistance", suggestion.getDayDistance()}, {"conflictCount", suggestion.getConflictCount()},
                {"reason", suggestion.getReason()}});
        }
        output["suggestions"].push_back({{"requestId", entry.first}, {"items", suggestions}});
    }
    return output;
}
}

nlohmann::json JsonEngineProtocol::execute(const nlohmann::json& input) {
    std::string runId, strategy;
    if (input.is_object()) {
        if (input.contains("runId") && input["runId"].is_string()) runId = input["runId"];
        if (input.contains("strategy") && input["strategy"].is_string()) strategy = input["strategy"];
    }
    try {
        if (input.is_object() && input.contains("protocolVersion") && input["protocolVersion"] != Version)
            throw InputError("UNSUPPORTED_VERSION", "Unsupported protocolVersion");
        return executeValidated(input);
    } catch (const InputError& error) {
        auto output = envelope(runId, strategy, "error");
        output["errors"].push_back({{"code", error.code}, {"message", error.what()}});
        return output;
    }
}

int JsonEngineProtocol::run(std::istream& input, std::ostream& output, std::ostream& diagnostics) {
    // Redirect existing human-readable engine messages, even on an exception.
    struct Redirect {
        std::streambuf* old;
        explicit Redirect(std::ostream& target) : old(std::cout.rdbuf(target.rdbuf())) {}
        ~Redirect() { std::cout.rdbuf(old); }
    };
    Json result;
    int exitCode = 0;
    {
        Redirect redirect(diagnostics);
        try {
            std::string document;
            char buffer[4096];
            while (input.read(buffer, sizeof(buffer)) || input.gcount()) {
                document.append(buffer, static_cast<std::size_t>(input.gcount()));
                if (document.size() > 16 * 1024 * 1024) throw InputError("INPUT_TOO_LARGE", "Input exceeds 16 MiB");
            }
            result = execute(Json::parse(document));
            if (result["status"] == "error") exitCode = 2;
        } catch (const Json::parse_error&) {
            result = envelope("", "", "error");
            result["errors"].push_back({{"code", "MALFORMED_JSON"}, {"message", "Input is not valid JSON"}});
            exitCode = 2;
        } catch (const InputError& error) {
            result = envelope("", "", "error");
            result["errors"].push_back({{"code", error.code}, {"message", error.what()}});
            exitCode = 2;
        } catch (const std::exception& error) {
            diagnostics << "Engine failure: " << error.what() << '\n';
            result = envelope("", "", "error");
            result["errors"].push_back({{"code", "ENGINE_FAILURE"}, {"message", "Internal engine failure"}});
            exitCode = 3;
        }
    }
    output << result.dump() << '\n';
    return output ? exitCode : 3;
}
