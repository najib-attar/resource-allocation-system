#ifndef EQUIPMENT_MATCHING_SERVICE_H
#define EQUIPMENT_MATCHING_SERVICE_H

#include "AppointmentSchedulingService.h"
#include <map>

struct EquipmentNeed {
    int typeId;
    int quantity;
    std::map<std::string, std::string> specifications;
};
struct EquipmentOption {
    int id, facultyId, categoryId, maxLoanDays;
    bool enabled;
    std::map<std::string, std::string> specifications;
    std::vector<int> eligibleFacultyIds;
};
struct EquipmentAsset {
    int id, typeId;
    std::string condition;
    bool held;
    std::vector<DatedInterval> reservations;
};
struct EquipmentMatchInput {
    int facultyId;
    bool custodianActive;
    DatedInterval proposed;
    std::vector<int> borrowerFacultyIds;
    std::vector<EquipmentNeed> items;
    std::vector<EquipmentOption> types;
    std::vector<EquipmentAsset> units;
};
struct EquipmentMatch {
    int typeId, availableQuantity;
    std::string reason;
    std::vector<int> unitIds;
    std::vector<int> alternativeTypeIds;
};
class EquipmentMatchingService {
public:
    static std::vector<EquipmentMatch> match(const EquipmentMatchInput& input, DatedInterval period);
    static std::vector<DatedInterval> alternatives(const EquipmentMatchInput& input);
};
#endif
