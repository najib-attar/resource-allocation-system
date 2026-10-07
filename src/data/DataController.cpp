#include "DataController.h"
#include <fstream>
#include <iostream>
#include <set>
#include <cctype>
#include "DataLoader.h"
#include "AllocationWriter.h"
#include "../models/RequestFactory.h"
#include "../models/CommitteeMeetingRequest.h"
#include "RequestResultWriter.h"
#include "../utils/CsvReader.h"

namespace {
    std::string trim(const std::string& value) {
        const std::string whitespace = " \t\r\n";
        const size_t start = value.find_first_not_of(whitespace);
        if (start == std::string::npos) {
            return "";
        }

        const size_t end = value.find_last_not_of(whitespace);
        return value.substr(start, end - start + 1);
    }

    class CsvFields {
        const std::vector<std::string>& columns;
        size_t index = 0;
    public:
        explicit CsvFields(const std::vector<std::string>& columns) : columns(columns) {}
        bool next(std::string& value) {
            if (index >= columns.size()) {
                value.clear();
                return false;
            }
            value = columns[index++];
            return true;
        }
    };

    std::string normalizeStrategyName(const std::string& strategyName) {
        std::string normalized;

        for (char ch : strategyName) {
            normalized += static_cast<char>(std::tolower(static_cast<unsigned char>(ch)));
        }

        return normalized;
    }

    std::string normalizeOptionalField(const std::string& value) {
        if (value == "None") return "";
        return value;
    }

    std::string normalizeMetadataField(const std::string& value) {
        std::string normalized = trim(value);
        if (normalized == "None") return "";
        return normalized;
    }

    bool parseOptionalBoolField(const std::string& value) {
        std::string normalized = normalizeMetadataField(value);

        for (char& ch : normalized) {
            ch = static_cast<char>(std::tolower(static_cast<unsigned char>(ch)));
        }

        return normalized == "true" || normalized == "1" || normalized == "yes";
    }

    struct OptionalRequestFields {
        std::string title;
        std::string purpose;
        std::string courseCode;
        std::string courseName;
        std::string examType;
        bool canSplitAcrossRooms = false;
    };

    void parseOptionalRequestFields(CsvFields& ss, OptionalRequestFields& fields) {
        std::string token;

        if (ss.next(token)) {
            fields.title = normalizeMetadataField(token);
        }

        if (ss.next(token)) {
            fields.purpose = normalizeMetadataField(token);
        }

        if (ss.next(token)) {
            fields.courseCode = normalizeMetadataField(token);
        }

        if (ss.next(token)) {
            fields.courseName = normalizeMetadataField(token);
        }

        if (ss.next(token)) {
            fields.examType = normalizeMetadataField(token);
        }

        if (ss.next(token)) {
            fields.canSplitAcrossRooms = parseOptionalBoolField(token);
        }
    }

    bool tryParseInt(const std::string& text, int& value) {
        try {
            size_t parsedLength = 0;
            value = std::stoi(text, &parsedLength);
            return parsedLength == text.size();
        } catch (...) {
            return false;
        }
    }

    void printRejectedRequestWarning(int requestId, const std::string& reason) {
        if (requestId >= 0) {
            std::cerr << "Warning: Request " << requestId << " rejected: " << reason << ".\n";
        } else {
            std::cerr << "Warning: Rejected request: " << reason << ".\n";
        }
    }

    User* findUserById(const std::vector<User*>& users, int userId) {
        for (User* user : users) {
            if (user && user->getId() == userId) {
                return user;
            }
        }
        return nullptr;
    }

    Space* findSpaceById(const std::vector<Space*>& spaces, int spaceId) {
        for (Space* space : spaces) {
            if (space && space->getId() == spaceId) {
                return space;
            }
        }
        return nullptr;
    }

    std::vector<Request*> loadRequestsFromCsv(const std::string& filename,
                                              const std::vector<User*>& users,
                                              const std::vector<Space*>& spaces) {
        std::vector<Request*> requests;
        std::set<int> seenRequestIds;
        std::ifstream file(filename, std::ios::binary);

        if (!file.is_open()) {
            std::cerr << "Error: Could not open requests file: " << filename << "\n";
            return requests;
        }

        CsvReader reader(file);
        std::vector<std::string> columns;
        std::string csvError;
        while (true) {
            const auto result = reader.readRecord(columns, csvError);
            if (result == CsvReader::Result::End) break;
            if (result == CsvReader::Result::Malformed) {
                int invalidId = -1;
                if (!columns.empty() && !tryParseInt(columns[0], invalidId)) invalidId = -1;
                if (invalidId >= 0) seenRequestIds.insert(invalidId);
                const std::string reason = "Malformed CSV: " + csvError;
                requests.push_back(RequestFactory::createInvalidRequest(
                    invalidId, columns.size() > 1 ? columns[1] : "Unknown",
                    nullptr, nullptr, 0, "", "", "", "", "", reason
                ));
                printRejectedRequestWarning(invalidId, reason);
                continue;
            }
            if (columns.empty()) continue;
            if (reader.getRecordNumber() == 1 && trim(columns[0]) == "requestId") continue;

            CsvFields ss(columns);
            std::string token;

            int requestId = -1;
            std::string requestType;
            int userId = -1;
            int spaceId = -1;
            int participantCount = 0;
            std::string requiredFeature;
            std::string requiredBuilding;
            std::string timeData;
            OptionalRequestFields optionalFields;

            if (!ss.next(token) || !tryParseInt(token, requestId)) {
                requests.push_back(RequestFactory::createInvalidRequest(
                    -1, "Unknown", nullptr, nullptr, 0, "", "", "", "", "", "Malformed input"
                ));
                printRejectedRequestWarning(-1, "Malformed input");
                continue;
            }

            if (requestId < 0) {
                requests.push_back(RequestFactory::createInvalidRequest(
                    requestId, "Unknown", nullptr, nullptr, 0, "", "", "", "", "", "Invalid request ID"
                ));
                printRejectedRequestWarning(requestId, "Invalid request ID");
                continue;
            }

            if (seenRequestIds.find(requestId) != seenRequestIds.end()) {
                ss.next(requestType);
                ss.next(token);
                userId = tryParseInt(token, userId) ? userId : -1;
                ss.next(token);
                spaceId = tryParseInt(token, spaceId) ? spaceId : -1;
                ss.next(token);
                participantCount = tryParseInt(token, participantCount) ? participantCount : 0;
                ss.next(requiredFeature);
                requiredFeature = normalizeOptionalField(requiredFeature);
                ss.next(requiredBuilding);
                requiredBuilding = normalizeOptionalField(requiredBuilding);
                ss.next(timeData);
                timeData = trim(timeData);

                parseOptionalRequestFields(ss, optionalFields);

                requests.push_back(RequestFactory::createInvalidRequest(
                    requestId,
                    requestType.empty() ? "Unknown" : requestType,
                    findUserById(users, userId),
                    findSpaceById(spaces, spaceId),
                    participantCount,
                    optionalFields.title,
                    optionalFields.purpose,
                    requiredFeature,
                    requiredBuilding,
                    timeData,
                    "Duplicate request ID",
                    optionalFields.courseCode,
                    optionalFields.courseName,
                    optionalFields.examType,
                    optionalFields.canSplitAcrossRooms
                ));
                printRejectedRequestWarning(requestId, "Duplicate request ID");
                continue;
            }

            seenRequestIds.insert(requestId);

            if (!ss.next(requestType)) {
                requests.push_back(RequestFactory::createInvalidRequest(
                    requestId, "Unknown", nullptr, nullptr, 0, "", "", "", "", "", "Malformed input"
                ));
                printRejectedRequestWarning(requestId, "Malformed input");
                continue;
            }

            if (!ss.next(token) || !tryParseInt(token, userId)) {
                requests.push_back(RequestFactory::createInvalidRequest(
                    requestId, requestType, nullptr, nullptr, 0, "", "", "", "", "", "Malformed input"
                ));
                printRejectedRequestWarning(requestId, "Malformed input");
                continue;
            }

            if (!ss.next(token) || !tryParseInt(token, spaceId)) {
                requests.push_back(RequestFactory::createInvalidRequest(
                    requestId, requestType, findUserById(users, userId), nullptr, 0, "", "", "", "", "", "Malformed input"
                ));
                printRejectedRequestWarning(requestId, "Malformed input");
                continue;
            }

            if (!ss.next(token) || !tryParseInt(token, participantCount)) {
                ss.next(requiredFeature);
                requiredFeature = normalizeOptionalField(requiredFeature);
                ss.next(requiredBuilding);
                requiredBuilding = normalizeOptionalField(requiredBuilding);
                ss.next(timeData);
                timeData = trim(timeData);

                parseOptionalRequestFields(ss, optionalFields);

                requests.push_back(RequestFactory::createInvalidRequest(
                    requestId, requestType, findUserById(users, userId), findSpaceById(spaces, spaceId),
                    0, optionalFields.title, optionalFields.purpose, requiredFeature, requiredBuilding, timeData,
                    "Malformed input", optionalFields.courseCode, optionalFields.courseName,
                    optionalFields.examType, optionalFields.canSplitAcrossRooms
                ));
                printRejectedRequestWarning(requestId, "Malformed input");
                continue;
            }

            if (!ss.next(requiredFeature)) {
                requests.push_back(RequestFactory::createInvalidRequest(
                    requestId, requestType, findUserById(users, userId), findSpaceById(spaces, spaceId),
                    participantCount, "", "", "", "", "", "Malformed input"
                ));
                printRejectedRequestWarning(requestId, "Malformed input");
                continue;
            }
            requiredFeature = normalizeOptionalField(requiredFeature);

            if (!ss.next(requiredBuilding)) {
                requests.push_back(RequestFactory::createInvalidRequest(
                    requestId, requestType, findUserById(users, userId), findSpaceById(spaces, spaceId),
                    participantCount, "", "", requiredFeature, "", "", "Malformed input"
                ));
                printRejectedRequestWarning(requestId, "Malformed input");
                continue;
            }
            requiredBuilding = normalizeOptionalField(requiredBuilding);

            if (!ss.next(timeData)) {
                requests.push_back(RequestFactory::createInvalidRequest(
                    requestId, requestType, findUserById(users, userId), findSpaceById(spaces, spaceId),
                    participantCount, "", "", requiredFeature, requiredBuilding, "", "Malformed input"
                ));
                printRejectedRequestWarning(requestId, "Malformed input");
                continue;
            }
            timeData = trim(timeData);

            parseOptionalRequestFields(ss, optionalFields);

            User* user = findUserById(users, userId);
            Space* space = findSpaceById(spaces, spaceId);

            if (!user) {
                requests.push_back(RequestFactory::createInvalidRequest(
                    requestId, requestType, nullptr, space, participantCount,
                    optionalFields.title,
                    optionalFields.purpose,
                    requiredFeature, requiredBuilding, timeData,
                    "Invalid user reference", optionalFields.courseCode, optionalFields.courseName,
                    optionalFields.examType, optionalFields.canSplitAcrossRooms
                ));
                printRejectedRequestWarning(requestId, "Invalid user reference");
                continue;
            }

            if (!space) {
                requests.push_back(RequestFactory::createInvalidRequest(
                    requestId, requestType, user, nullptr, participantCount,
                    optionalFields.title,
                    optionalFields.purpose,
                    requiredFeature, requiredBuilding, timeData,
                    "Invalid space reference", optionalFields.courseCode, optionalFields.courseName,
                    optionalFields.examType, optionalFields.canSplitAcrossRooms
                ));
                printRejectedRequestWarning(requestId, "Invalid space reference");
                continue;
            }

            Request* request = RequestFactory::createRequest(
                requestId,
                requestType,
                user,
                space,
                participantCount,
                optionalFields.title,
                optionalFields.purpose,
                requiredFeature,
                requiredBuilding,
                timeData,
                optionalFields.courseCode,
                optionalFields.courseName,
                optionalFields.examType,
                optionalFields.canSplitAcrossRooms
            );
            if (!request) {
                request = RequestFactory::createInvalidRequest(
                    requestId,
                    requestType,
                    user,
                    space,
                    participantCount,
                    optionalFields.title,
                    optionalFields.purpose,
                    requiredFeature,
                    requiredBuilding,
                    timeData,
                    "Malformed input",
                    optionalFields.courseCode,
                    optionalFields.courseName,
                    optionalFields.examType,
                    optionalFields.canSplitAcrossRooms
                );
            }

            requests.push_back(request);

            if (request->getStatus() == RequestStatus::Rejected) {
                printRejectedRequestWarning(requestId, request->getRejectionReason());
            }
        }

        return requests;
    }

    void attachParticipantsToCommitteeRequests(
        std::vector<Request*>& requests,
        const std::vector<RequestParticipant>& requestParticipants
    ) {
        for (Request* request : requests) {
            CommitteeMeetingRequest* committeeRequest =
                dynamic_cast<CommitteeMeetingRequest*>(request);

            if (!committeeRequest) {
                continue;
            }

            int attachedCount = 0;
            for (const RequestParticipant& participant : requestParticipants) {
                if (participant.getRequestId() == committeeRequest->getId()) {
                    committeeRequest->addRequiredParticipant(
                        participant.getUserId(),
                        participant.getParticipantRole()
                    );
                    attachedCount++;
                }
            }

            if (attachedCount == 0) {
                committeeRequest->addHistoryEvent("No request participants loaded for committee meeting");
            } else {
                committeeRequest->addHistoryEvent(
                    "Loaded " + std::to_string(attachedCount)
                    + " required committee participant(s)"
                );
            }
        }
    }
}

std::string DataController::loadAllocationStrategyName(const std::string& configFile) const {
    std::ifstream file(configFile);

    if (!file.is_open()) {
        std::cerr << "Warning: allocation strategy config missing. Falling back to greedy.\n";
        return "greedy";
    }

    std::string line;
    while (std::getline(file, line)) {
        std::string trimmedLine = trim(line);

        if (trimmedLine.empty() || trimmedLine[0] == '#') {
            continue;
        }

        const size_t equalsPos = trimmedLine.find('=');
        if (equalsPos == std::string::npos) {
            continue;
        }

        const std::string key = trim(trimmedLine.substr(0, equalsPos));
        const std::string value = trim(trimmedLine.substr(equalsPos + 1));

        if (key == "allocation_strategy") {
            if (!value.empty()) {
                const std::string normalizedValue = normalizeStrategyName(value);

                if (normalizedValue == "greedy" ||
                    normalizedValue == "priority" ||
                    normalizedValue == "multi_room_exam_greedy" ||
                    normalizedValue == "multi_room_exam_best_fit" ||
                    normalizedValue == "shared_room_exam_best_fit") {
                    return normalizedValue;
                }

                std::cerr << "Warning: unknown allocation strategy. Falling back to greedy.\n";
                return "greedy";
            }

            std::cerr << "Warning: allocation strategy config missing. Falling back to greedy.\n";
            return "greedy";
        }
    }

    std::cerr << "Warning: allocation strategy config missing. Falling back to greedy.\n";
    return "greedy";
}

SystemData DataController::loadAllData(const std::string& usersFile,
                                       const std::string& spacesFile,
                                       const std::string& requestsFile,
                                       const std::string& userBusySlotsFile,
                                       const std::string& requestParticipantsFile) const {
    SystemData data;
    data.users = DataLoader::loadUsers(usersFile);
    data.spaces = DataLoader::loadSpaces(spacesFile);
    data.requests = loadRequestsFromCsv(requestsFile, data.users, data.spaces);
    data.userBusySlots = DataLoader::loadUserBusySlots(userBusySlotsFile);
    data.requestParticipants = DataLoader::loadRequestParticipants(requestParticipantsFile);
    attachParticipantsToCommitteeRequests(data.requests, data.requestParticipants);
    return data;
}

bool DataController::exportAllocations(const std::string& allocationsFile,
                                       const std::vector<Allocation>& allocations) const {
    return AllocationWriter::writeAllocations(allocationsFile, allocations);
}

void DataController::cleanupData(SystemData& data) const {
    for (Request* request : data.requests) {
        delete request;
    }
    data.requests.clear();

    for (Space* space : data.spaces) {
        delete space;
    }
    data.spaces.clear();

    for (User* user : data.users) {
        delete user;
    }
    data.users.clear();
}

bool DataController::exportRequestResults(const std::string& resultsFile,
                                          const std::vector<Request*>& requests) const {
    return RequestResultWriter::writeRequestResults(resultsFile, requests);
}
