#include "EquipmentMatchingService.h"
#include <algorithm>
#include <set>

namespace {
bool specificationsMatch(const EquipmentOption& option, const EquipmentNeed& need) {
    for (const auto& value : need.specifications) {
        auto found = option.specifications.find(value.first);
        if (found == option.specifications.end() || found->second != value.second) return false;
    }
    return true;
}
bool eligible(const EquipmentMatchInput& input, const EquipmentOption& option, DatedInterval period) {
    if (!input.custodianActive || !option.enabled || option.facultyId != input.facultyId ||
        period.end-period.start > option.maxLoanDays*86400LL) return false;
    return option.eligibleFacultyIds.empty() || std::any_of(input.borrowerFacultyIds.begin(), input.borrowerFacultyIds.end(),
        [&](int id){return std::find(option.eligibleFacultyIds.begin(),option.eligibleFacultyIds.end(),id)!=option.eligibleFacultyIds.end();});
}
std::vector<int> available(const EquipmentMatchInput& input, int type, DatedInterval period) {
    std::vector<int> result;
    for (const auto& unit : input.units) {
        if (unit.typeId != type || unit.condition != "usable" || unit.held) continue;
        bool conflict = std::any_of(unit.reservations.begin(),unit.reservations.end(),[&](auto slot){return period.start<slot.end && slot.start<period.end;});
        if (!conflict) result.push_back(unit.id);
    }
    std::sort(result.begin(),result.end());
    return result;
}
}

std::vector<EquipmentMatch> EquipmentMatchingService::match(const EquipmentMatchInput& input, DatedInterval period) {
    std::vector<EquipmentMatch> result;
    for (const auto& need : input.items) {
        EquipmentMatch item{need.typeId,0,"INELIGIBLE",{}, {}};
        auto option=std::find_if(input.types.begin(),input.types.end(),[&](const auto& row){return row.id==need.typeId;});
        if (!input.custodianActive) item.reason="NO_CUSTODIAN";
        else if (option != input.types.end() && eligible(input,*option,period) && specificationsMatch(*option,need)) {
            item.unitIds=available(input,need.typeId,period);
            item.availableQuantity=static_cast<int>(item.unitIds.size());
            item.reason=item.availableQuantity>=need.quantity ? "AVAILABLE" : "INSUFFICIENT_QUANTITY";
            if (item.reason=="AVAILABLE") item.unitIds.resize(need.quantity);
            else item.unitIds.clear();
        }
        if (option != input.types.end() && item.reason!="AVAILABLE") {
            for (const auto& other : input.types) {
                // Alternatives must satisfy both catalog specifications and explicit requirements.
                EquipmentNeed compatible{other.id,need.quantity,option->specifications};
                if (other.id!=option->id && other.categoryId==option->categoryId && eligible(input,other,period) &&
                    specificationsMatch(other,compatible) && specificationsMatch(other,need) &&
                    available(input,other.id,period).size()>=static_cast<std::size_t>(need.quantity)) item.alternativeTypeIds.push_back(other.id);
            }
            std::sort(item.alternativeTypeIds.begin(),item.alternativeTypeIds.end());
        }
        result.push_back(item);
    }
    bool feasible=std::all_of(result.begin(),result.end(),[](const auto& row){return row.reason=="AVAILABLE";});
    if (!feasible) for (auto& row : result) row.unitIds.clear();
    return result;
}

std::vector<DatedInterval> EquipmentMatchingService::alternatives(const EquipmentMatchInput& input) {
    std::set<std::int64_t> starts;
    for (const auto& unit : input.units) for (const auto& period : unit.reservations)
        if (period.end>input.proposed.start && period.end-input.proposed.start<=30*86400LL) starts.insert(period.end);
    std::vector<DatedInterval> result;
    for (auto start : starts) {
        DatedInterval period{start,start+input.proposed.end-input.proposed.start};
        if (period.end>4102444800LL) continue;
        auto rows=match(input,period);
        if (std::all_of(rows.begin(),rows.end(),[](const auto& row){return row.reason=="AVAILABLE";})) result.push_back(period);
        if (result.size()==3) break;
    }
    return result;
}
