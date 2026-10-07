#include "DataLoader.h"
#include <fstream>
#include <sstream>
#include <iostream>
#include <unordered_map>
#include <unordered_set>
#include "../models/SpaceFactory.h"
#include "../models/UserFactory.h"
#include "../utils/CsvReader.h"

namespace {
    using HeaderIndex = std::unordered_map<std::string, size_t>;

    std::string removeUtf8Bom(const std::string& text) {
        if (text.size() >= 3 &&
            static_cast<unsigned char>(text[0]) == 0xEF &&
            static_cast<unsigned char>(text[1]) == 0xBB &&
            static_cast<unsigned char>(text[2]) == 0xBF) {
            return text.substr(3);
        }

        return text;
    }

    std::string trim(const std::string& text) {
        const std::string whitespace = " \t\r\n";
        const size_t first = text.find_first_not_of(whitespace);
        if (first == std::string::npos) {
            return "";
        }

        const size_t last = text.find_last_not_of(whitespace);
        return removeUtf8Bom(text.substr(first, last - first + 1));
    }

    bool readCsvRow(CsvReader& reader, std::vector<std::string>& columns,
                    const std::string& rowType, bool trimFields = true) {
        std::string error;
        while (true) {
            const auto result = reader.readRecord(columns, error);
            if (result == CsvReader::Result::End) return false;
            if (result == CsvReader::Result::Malformed) {
                std::cerr << "Warning: Skipping malformed " << rowType << " CSV record "
                          << reader.getRecordNumber() << ": " << error << ".\n";
                continue;
            }
            if (trimFields) {
                for (std::string& column : columns) column = trim(column);
            }
            return true;
        }
    }

    std::string optionalColumn(const std::vector<std::string>& columns,
                               size_t index,
                               const std::string& defaultValue = "") {
        if (index >= columns.size() || columns[index].empty()) {
            return defaultValue;
        }

        return columns[index];
    }

    HeaderIndex buildHeaderIndex(const std::vector<std::string>& headers) {
        HeaderIndex index;

        for (size_t i = 0; i < headers.size(); ++i) {
            index[headers[i]] = i;
        }

        return index;
    }

    std::string optionalColumnByName(const std::vector<std::string>& columns,
                                     const HeaderIndex& headerIndex,
                                     const std::string& columnName,
                                     size_t fallbackIndex,
                                     const std::string& defaultValue = "") {
        const auto it = headerIndex.find(columnName);
        if (it != headerIndex.end()) {
            return optionalColumn(columns, it->second, defaultValue);
        }

        return optionalColumn(columns, fallbackIndex, defaultValue);
    }

    std::vector<std::string> splitRoleNames(const std::string& text) {
        std::vector<std::string> roles;
        std::stringstream ss(text);
        std::string role;

        while (std::getline(ss, role, '|')) {
            role = trim(role);
            if (!role.empty()) {
                roles.push_back(role);
            }
        }

        return roles;
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

    bool tryParseFlag(const std::string& text, bool& value) {
        if (text == "0") {
            value = false;
            return true;
        }
        if (text == "1") {
            value = true;
            return true;
        }
        return false;
    }

    bool tryParseTimeOfDay(const std::string& text, int& minutesFromMidnight) {
        const std::string trimmed = trim(text);
        const size_t colonPosition = trimmed.find(':');

        if (colonPosition == std::string::npos) {
            int hour = 0;
            if (!tryParseInt(trimmed, hour)) {
                return false;
            }

            if (hour < 0 || hour > 24) {
                return false;
            }

            minutesFromMidnight = hour * 60;
            return true;
        }

        const std::string hourText = trimmed.substr(0, colonPosition);
        const std::string minuteText = trimmed.substr(colonPosition + 1);
        int hour = 0;
        int minute = 0;

        if (!tryParseInt(hourText, hour) || !tryParseInt(minuteText, minute)) {
            return false;
        }

        if (hour < 0 || hour > 24 || minute < 0 || minute > 59) {
            return false;
        }

        if (hour == 24 && minute != 0) {
            return false;
        }

        minutesFromMidnight = hour * 60 + minute;
        return true;
    }

}

std::vector<User*> DataLoader::loadUsers(const std::string& filename) {
    std::vector<User*> users;
    std::unordered_set<int> acceptedUserIds;
    std::ifstream file(filename, std::ios::binary);

    if (!file.is_open()) {
        std::cerr << "Error: Could not open users file: " << filename << "\n";
        return users;
    }

    CsvReader reader(file);
    std::vector<std::string> columns;
    HeaderIndex userHeaderIndex;
    while (readCsvRow(reader, columns, "user")) {
        const size_t lineNumber = reader.getRecordNumber();
        if (columns.empty()) continue;
        if (lineNumber == 1 && columns[0] == "userId") {
            userHeaderIndex = buildHeaderIndex(columns);
            continue;
        }

        if (columns.size() < 3) {
            std::cerr << "Warning: Skipping malformed user row " << lineNumber << ".\n";
            continue;
        }

        std::string idToken = columns[0];
        std::string name = columns[1];
        std::string roleString = columns[2];
        int id = 0;

        if (!tryParseInt(idToken, id) || id < 0) {
            std::cerr << "Warning: Skipping malformed user row " << lineNumber << ".\n";
            continue;
        }

        if (acceptedUserIds.find(id) != acceptedUserIds.end()) {
            std::cerr << "Warning: Duplicate user ID " << id
                      << " on row " << lineNumber
                      << ". Keeping first user and skipping duplicate row.\n";
            continue;
        }

        UserProfileData profile;
        profile.email = optionalColumnByName(columns, userHeaderIndex, "email", 3);
        profile.status = optionalColumnByName(columns, userHeaderIndex, "status", 4, "active");
        profile.primaryUnitName = optionalColumnByName(columns, userHeaderIndex, "primaryUnit", 13);
        profile.assignedRoleNames = splitRoleNames(
            optionalColumnByName(columns, userHeaderIndex, "assignedRoles", 14)
        );
        profile.studentNo = optionalColumnByName(columns, userHeaderIndex, "studentNo", 5);
        profile.program = optionalColumnByName(columns, userHeaderIndex, "program", 6);
        tryParseInt(
            optionalColumnByName(columns, userHeaderIndex, "yearLevel", 7, "0"),
            profile.yearLevel
        );
        profile.title = optionalColumnByName(columns, userHeaderIndex, "title", 8);
        profile.officeRoom = optionalColumnByName(columns, userHeaderIndex, "officeRoom", 9);
        profile.assistantType = optionalColumnByName(columns, userHeaderIndex, "assistantType", 10);
        profile.jobTitle = optionalColumnByName(columns, userHeaderIndex, "jobTitle", 11);
        profile.adminLevel = optionalColumnByName(columns, userHeaderIndex, "adminLevel", 12);

        User* user = UserFactory::createUser(id, name, roleString, profile);
        if (!user) {
            std::cerr << "Warning: Skipping malformed user row " << lineNumber << ".\n";
            continue;
        }

        acceptedUserIds.insert(id);
        users.push_back(user);
    }

    return users;
}

std::vector<Space*> DataLoader::loadSpaces(const std::string& filename) {
    std::vector<Space*> spaces;
    std::unordered_set<int> acceptedSpaceIds;
    std::ifstream file(filename, std::ios::binary);

    if (!file.is_open()) {
        std::cerr << "Error: Could not open spaces file: " << filename << "\n";
        return spaces;
    }

    CsvReader reader(file);
    std::vector<std::string> columns;
    while (readCsvRow(reader, columns, "space", false)) {
        const size_t lineNumber = reader.getRecordNumber();
        if (columns.empty()) continue;
        if (lineNumber == 1 && trim(columns[0]) == "spaceId") continue;

        if (columns.size() < 9) {
            std::cerr << "Warning: Skipping malformed space row " << lineNumber << ".\n";
            continue;
        }
        const std::string& idToken = columns[0];
        const std::string& type = columns[1];
        const std::string& name = columns[2];
        const std::string& capacityToken = columns[3];
        const std::string& projectorToken = columns[4];
        const std::string& whiteboardToken = columns[5];
        const std::string& computersToken = columns[6];
        const std::string& availableToken = columns[7];
        const std::string& building = columns[8];
        int id = 0;
        int capacity = 0;
        bool hasProjector = false;
        bool hasWhiteboard = false;
        bool hasComputers = false;
        bool isAvailable = false;

        if (!tryParseInt(idToken, id) ||
            !tryParseInt(capacityToken, capacity) ||
            !tryParseFlag(projectorToken, hasProjector) ||
            !tryParseFlag(whiteboardToken, hasWhiteboard) ||
            !tryParseFlag(computersToken, hasComputers) ||
            !tryParseFlag(availableToken, isAvailable) ||
            id < 0) {
            std::cerr << "Warning: Skipping malformed space row " << lineNumber << ".\n";
            continue;
        }

        if (acceptedSpaceIds.find(id) != acceptedSpaceIds.end()) {
            std::cerr << "Warning: Duplicate space ID " << id
                      << " on row " << lineNumber
                      << ". Keeping first space and skipping duplicate row.\n";
            continue;
        }

        Space* space = SpaceFactory::createSpace(id, name, type, capacity,
                                                 hasProjector, hasWhiteboard,
                                                 hasComputers, isAvailable,
                                                 building);
        if (!space) {
            std::cerr << "Warning: Skipping malformed space row " << lineNumber << ".\n";
            continue;
        }

        acceptedSpaceIds.insert(id);
        spaces.push_back(space);
    }

    return spaces;
}

std::vector<UserBusySlot> DataLoader::loadUserBusySlots(const std::string& filename) {
    std::vector<UserBusySlot> busySlots;
    std::ifstream file(filename, std::ios::binary);

    if (!file.is_open()) {
        std::cerr << "Warning: Could not open user busy slots file: " << filename
                  << ". Continuing with no busy slots.\n";
        return busySlots;
    }

    CsvReader reader(file);
    std::vector<std::string> columns;
    while (readCsvRow(reader, columns, "user busy slot")) {
        const size_t lineNumber = reader.getRecordNumber();
        if (columns.empty()) continue;
        if (lineNumber == 1 && columns[0] == "userId") continue;

        if (columns.size() < 5) {
            std::cerr << "Warning: Skipping malformed user busy slot row "
                      << lineNumber << ".\n";
            continue;
        }

        int userId = 0;
        int day = 0;
        int startMinutes = 0;
        int endMinutes = 0;

        if (!tryParseInt(columns[0], userId) ||
            !tryParseInt(columns[1], day) ||
            !tryParseTimeOfDay(columns[2], startMinutes) ||
            !tryParseTimeOfDay(columns[3], endMinutes) ||
            userId < 0) {
            std::cerr << "Warning: Skipping malformed user busy slot row "
                      << lineNumber << ".\n";
            continue;
        }

        try {
            TimeSlot slot = TimeSlot::fromMinutes(day, startMinutes, endMinutes);
            busySlots.emplace_back(userId, slot, columns[4]);
        } catch (...) {
            std::cerr << "Warning: Skipping invalid user busy slot row "
                      << lineNumber << ".\n";
        }
    }

    return busySlots;
}

std::vector<RequestParticipant> DataLoader::loadRequestParticipants(const std::string& filename) {
    std::vector<RequestParticipant> participants;
    std::ifstream file(filename, std::ios::binary);

    if (!file.is_open()) {
        std::cerr << "Warning: Could not open request participants file: " << filename
                  << ". Continuing with no request participants.\n";
        return participants;
    }

    CsvReader reader(file);
    std::vector<std::string> columns;
    while (readCsvRow(reader, columns, "request participant")) {
        const size_t lineNumber = reader.getRecordNumber();
        if (columns.empty()) continue;
        if (lineNumber == 1 && columns[0] == "requestId") continue;

        if (columns.size() < 3) {
            std::cerr << "Warning: Skipping malformed request participant row "
                      << lineNumber << ".\n";
            continue;
        }

        int requestId = 0;
        int userId = 0;

        if (!tryParseInt(columns[0], requestId) ||
            !tryParseInt(columns[1], userId) ||
            columns[2].empty() ||
            requestId < 0 ||
            userId < 0) {
            std::cerr << "Warning: Skipping malformed request participant row "
                      << lineNumber << ".\n";
            continue;
        }

        participants.emplace_back(requestId, userId, columns[2]);
    }

    return participants;
}
