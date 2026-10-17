#include "EquipmentJsonProtocol.h"
#include "../services/EquipmentMatchingService.h"
#include "../vendor/nlohmann/json.hpp"
#include <iostream>
#include <set>
#include <stdexcept>

using nlohmann::json;
namespace {
std::int64_t integer(const json& row, std::int64_t low=1, std::int64_t high=2147483647) {
    if (!row.is_number_integer() || row.is_boolean() || (row.is_number_unsigned() && row.get<std::uint64_t>()>static_cast<std::uint64_t>(high)))
        throw std::invalid_argument("Expected a bounded integer.");
    auto n=row.get<std::int64_t>();
    if (n<low || n>high) throw std::invalid_argument("Integer outside range.");
    return n;
}
std::string text(const json& row) {
    if (!row.is_string() || row.get_ref<const std::string&>().size()>2000) throw std::invalid_argument("Invalid text.");
    return row.get<std::string>();
}
bool flag(const json& row) {
    if (!row.is_boolean()) throw std::invalid_argument("Expected boolean.");
    return row.get<bool>();
}
const json& collection(const json& row, std::size_t maximum) {
    if (!row.is_array() || row.size()>maximum) throw std::invalid_argument("Invalid bounded list.");
    return row;
}
DatedInterval interval(const json& row) {
    DatedInterval value{integer(row.at("start"),0,4102444800LL),integer(row.at("end"),1,4102444800LL)};
    if (value.start>=value.end || value.start%60 || value.end%60) throw std::invalid_argument("Invalid half-open minute interval.");
    return value;
}
std::map<std::string,std::string> specs(const json& row) {
    if (!row.is_object() || row.size()>50) throw std::invalid_argument("Invalid specifications.");
    std::map<std::string,std::string> values;
    for (auto it=row.begin();it!=row.end();++it) {
        if (it.key().empty() || it.key().size()>100) throw std::invalid_argument("Invalid specification key.");
        values.emplace(it.key(),text(it.value()));
    }
    return values;
}
}
int EquipmentJsonProtocol::run(std::istream& input, std::ostream& output, std::ostream& diagnostics) {
    json result{{"protocolVersion",1},{"operation","equipment"},{"engineVersion","equipment-1"},{"runId",""},
        {"status","error"},{"feasible",false},{"items",json::array()},{"alternativePeriods",json::array()},{"errors",json::array()}};
    try {
        std::string raw;
        char c;
        while(input.get(c)) { if(raw.size()>=16*1024*1024) throw std::invalid_argument("Input exceeds 16 MiB."); raw+=c; }
        auto document=json::parse(raw);
        integer(document.at("protocolVersion"),1,1);
        if(document.at("operation")!="equipment") throw std::invalid_argument("Unknown operation.");
        auto run=text(document.at("runId"));
        if(run.empty()) throw std::invalid_argument("Missing run ID.");
        result["runId"]=run;
        EquipmentMatchInput data;
        data.facultyId=static_cast<int>(integer(document.at("facultyId")));
        data.custodianActive=flag(document.at("custodianActive"));
        data.proposed=interval(document.at("proposed"));
        if(data.proposed.end-data.proposed.start>365*86400LL) throw std::invalid_argument("Period exceeds one year.");
        for(const auto& n:collection(document.at("borrowerFacultyIds"),100)) data.borrowerFacultyIds.push_back(static_cast<int>(integer(n)));
        std::set<int> typeIds,unitIds,needIds;
        for(const auto& row:collection(document.at("types"),1000)) {
            EquipmentOption type;
            type.id=static_cast<int>(integer(row.at("id")));
            if(!typeIds.insert(type.id).second) throw std::invalid_argument("Duplicate type.");
            type.facultyId=static_cast<int>(integer(row.at("facultyId")));
            type.categoryId=static_cast<int>(integer(row.at("categoryId")));
            type.maxLoanDays=static_cast<int>(integer(row.at("maxLoanDays"),1,365));
            type.enabled=flag(row.at("enabled")); type.specifications=specs(row.at("specifications"));
            for(const auto& n:collection(row.at("eligibleFacultyIds"),100)) type.eligibleFacultyIds.push_back(static_cast<int>(integer(n)));
            data.types.push_back(type);
        }
        for(const auto& row:collection(document.at("items"),50)) {
            int id=static_cast<int>(integer(row.at("typeId")));
            if(!typeIds.count(id) || !needIds.insert(id).second) throw std::invalid_argument("Unknown or duplicate requested type.");
            data.items.push_back({id,static_cast<int>(integer(row.at("quantity"),1,1000)),specs(row.at("specifications"))});
        }
        if(data.items.empty()) throw std::invalid_argument("At least one requested item required.");
        const std::set<std::string> conditions{"usable","maintenance","damaged","missing","lost","retired"};
        for(const auto& row:collection(document.at("units"),10000)) {
            EquipmentAsset unit;
            unit.id=static_cast<int>(integer(row.at("id")));unit.typeId=static_cast<int>(integer(row.at("typeId")));
            if(!unitIds.insert(unit.id).second || !typeIds.count(unit.typeId)) throw std::invalid_argument("Invalid unit reference.");
            unit.condition=text(row.at("condition"));unit.held=flag(row.at("held"));
            if(!conditions.count(unit.condition)) throw std::invalid_argument("Unknown unit condition.");
            for(const auto& period:collection(row.at("reservations"),1000)) unit.reservations.push_back(interval(period));
            data.units.push_back(unit);
        }
        auto matches=EquipmentMatchingService::match(data,data.proposed);
        result["feasible"]=true;
        for(const auto& row:matches) {
            if(row.reason!="AVAILABLE") result["feasible"]=false;
            result["items"].push_back({{"typeId",row.typeId},{"availableQuantity",row.availableQuantity},{"unitIds",row.unitIds},
                {"reasonCode",row.reason},{"alternativeTypeIds",row.alternativeTypeIds}});
        }
        if(!result["feasible"].get<bool>()) for(const auto& p:EquipmentMatchingService::alternatives(data))
            result["alternativePeriods"].push_back({{"start",p.start},{"end",p.end}});
        result["status"]="success"; output<<result.dump()<<'\n'; return 0;
    } catch(const json::exception& error) {
        diagnostics<<"Equipment protocol: "<<error.what()<<'\n';
        result["errors"].push_back({{"code","INVALID_INPUT"},{"message","Malformed or incomplete equipment document."}});
    } catch(const std::invalid_argument& error) {
        diagnostics<<"Equipment validation: "<<error.what()<<'\n';
        result["errors"].push_back({{"code","INVALID_INPUT"},{"message",error.what()}});
    }
    output<<result.dump()<<'\n';return 2;
}
