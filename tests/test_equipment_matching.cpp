#include "test_framework.h"
#include "src/services/EquipmentMatchingService.h"
#include "src/integration/EquipmentJsonProtocol.h"
#include "src/vendor/nlohmann/json.hpp"
#include <sstream>

namespace {
EquipmentMatchInput fixture() {
    EquipmentMatchInput in;
    in.facultyId=1;in.custodianActive=true;in.proposed={1800000000,1800086400};in.borrowerFacultyIds={1};
    in.items={{10,2,{{"architecture","arm"}}}};
    in.types={{10,1,1,7,true,{{"architecture","arm"}},{}},{11,1,1,7,true,{{"architecture","arm"},{"usb","c"}},{}},
              {12,1,1,7,true,{{"architecture","avr"}},{}},{13,2,1,7,true,{{"architecture","arm"}},{}}};
    in.units={{2,10,"usable",false,{}},{1,10,"usable",false,{}},{3,11,"usable",false,{}},
              {4,11,"usable",false,{}},{5,12,"usable",false,{}},{6,13,"usable",false,{}}};
    return in;
}
nlohmann::json document() {
    using nlohmann::json;
    return {{"protocolVersion",1},{"operation","equipment"},{"runId","equipment-test"},{"facultyId",1},
      {"custodianActive",true},{"borrowerFacultyIds",{1}},{"proposed",{{"start",1800000000},{"end",1800086400}}},
      {"items",{{{"typeId",10},{"quantity",1},{"specifications",{{"label","Board, \"A\"\n\xC3\xBC"}}}}}},
      {"types",{{{"id",10},{"facultyId",1},{"categoryId",1},{"maxLoanDays",7},{"enabled",true},
                 {"specifications",{{"label","Board, \"A\"\n\xC3\xBC"}}},{"eligibleFacultyIds",json::array()}}}},
      {"units",{{{"id",1},{"typeId",10},{"condition","usable"},{"held",false},{"reservations",json::array()}}}}};
}
nlohmann::json execute(nlohmann::json input,int expected=0) {
    std::istringstream in(input.dump());std::ostringstream out,err;
    CHECK_EQ(EquipmentJsonProtocol::run(in,out,err),expected);
    return nlohmann::json::parse(out.str());
}
}

TEST_CASE("Equipment selects distinct identical physical units in stable ID order") {
    auto in=fixture();auto rows=EquipmentMatchingService::match(in,in.proposed);
    CHECK_EQ(rows[0].reason,"AVAILABLE");CHECK_EQ(rows[0].unitIds.size(),std::size_t(2));
    CHECK_EQ(rows[0].unitIds[0],1);CHECK_EQ(rows[0].unitIds[1],2);
}
TEST_CASE("Equipment insufficient quantity never yields a partial reservation") {
    auto in=fixture();in.items[0].quantity=3;
    auto rows=EquipmentMatchingService::match(in,in.proposed);
    CHECK_EQ(rows[0].reason,"INSUFFICIENT_QUANTITY");CHECK(rows[0].unitIds.empty());
}
TEST_CASE("Equipment excludes damage maintenance missing lost and retired assets") {
    for(const std::string state:{"damaged","maintenance","missing","lost","retired"}) {
        auto in=fixture();in.units[0].condition=state;
        CHECK_EQ(EquipmentMatchingService::match(in,in.proposed)[0].availableQuantity,1);
    }
}
TEST_CASE("Equipment held loans stay unavailable even beyond planned due dates") {
    auto in=fixture();in.units[0].held=true;in.units[0].reservations={{1700000000,1700086400}};
    CHECK_EQ(EquipmentMatchingService::match(in,in.proposed)[0].availableQuantity,1);
}
TEST_CASE("Equipment reservations use half open intervals and permit adjacent loans") {
    auto in=fixture();in.units[0].reservations={{in.proposed.end,in.proposed.end+86400}};
    CHECK_EQ(EquipmentMatchingService::match(in,in.proposed)[0].reason,"AVAILABLE");
    in.units[0].reservations[0].start-=60;
    CHECK_EQ(EquipmentMatchingService::match(in,in.proposed)[0].reason,"INSUFFICIENT_QUANTITY");
}
TEST_CASE("Equipment requires faculty eligibility custody policy and exact specifications") {
    auto in=fixture();in.custodianActive=false;
    CHECK_EQ(EquipmentMatchingService::match(in,in.proposed)[0].reason,"NO_CUSTODIAN");
    in=fixture();in.types[0].eligibleFacultyIds={2};
    CHECK_EQ(EquipmentMatchingService::match(in,in.proposed)[0].reason,"INELIGIBLE");
    in=fixture();in.items[0].specifications={{"architecture","avr"}};
    CHECK_EQ(EquipmentMatchingService::match(in,in.proposed)[0].reason,"INELIGIBLE");
    in=fixture();in.types[0].maxLoanDays=1;in.proposed.end+=60;
    CHECK_EQ(EquipmentMatchingService::match(in,in.proposed)[0].reason,"INELIGIBLE");
}
TEST_CASE("Equipment suggests only compatible same faculty alternative types") {
    auto in=fixture();in.units[0].held=true;
    auto row=EquipmentMatchingService::match(in,in.proposed)[0];
    CHECK_EQ(row.alternativeTypeIds.size(),std::size_t(1));CHECK_EQ(row.alternativeTypeIds[0],11);
}
TEST_CASE("Equipment alternative periods fulfill every item after known reservations end") {
    auto in=fixture();in.units[0].reservations={in.proposed};
    auto periods=EquipmentMatchingService::alternatives(in);
    CHECK_EQ(periods.size(),std::size_t(1));CHECK_EQ(periods[0].start,in.proposed.end);
}
TEST_CASE("Equipment mixed requests are all or nothing without reusing units") {
    auto in=fixture();in.items.push_back({11,3,{}});
    auto rows=EquipmentMatchingService::match(in,in.proposed);
    CHECK(rows[0].unitIds.empty());CHECK(rows[1].unitIds.empty());
}
TEST_CASE("Equipment JSON roundtrips escaped Unicode text without filesystem access") {
    auto out=execute(document());CHECK(out["feasible"].get<bool>());CHECK_EQ(out["operation"].get<std::string>(),"equipment");
    CHECK(out["errors"].empty());CHECK_EQ(out["items"][0]["unitIds"][0].get<int>(),1);
}
TEST_CASE("Equipment JSON rejects missing versions fractional counts and broken references") {
    auto in=document();in.erase("protocolVersion");CHECK_EQ(execute(in,2)["status"].get<std::string>(),"error");
    in=document();in["protocolVersion"]=2;execute(in,2);
    in=document();in["items"][0]["quantity"]=1.5;execute(in,2);
    in=document();in["items"][0]["typeId"]=-1;execute(in,2);
    in=document();in["units"][0]["typeId"]=99;execute(in,2);
    in=document();in["units"].push_back(in["units"][0]);execute(in,2);
    in=document();in["proposed"]["end"]=1800000000;execute(in,2);
    in=document();in["items"][0]["quantity"]=true;execute(in,2);
}
TEST_CASE("Equipment malformed JSON returns one explicit protocol error") {
    std::istringstream in("{broken");std::ostringstream out,err;
    CHECK_EQ(EquipmentJsonProtocol::run(in,out,err),2);
    CHECK_EQ(nlohmann::json::parse(out.str())["status"].get<std::string>(),"error");CHECK(!err.str().empty());
}

namespace {
nlohmann::json equipmentSeries() {
    auto in=document();in["operation"]="equipmentSeries";
    in["occurrences"]={in["proposed"],{{"start",1800604800},{"end",1800691200}}};return in;
}
nlohmann::json executeEquipmentSeries(nlohmann::json value,int expected=0) {
    std::istringstream in(value.dump());std::ostringstream out,err;
    CHECK_EQ(EquipmentJsonProtocol::run(in,out,err,true),expected);return nlohmann::json::parse(out.str());
}
}
TEST_CASE("Equipment series may reserve the same unit in separate non overlapping periods") {
    auto out=executeEquipmentSeries(equipmentSeries());CHECK(out["feasible"].get<bool>());
    CHECK_EQ(out["occurrences"].size(),std::size_t(2));
    CHECK_EQ(out["occurrences"][0]["items"][0]["unitIds"][0].get<int>(),1);
    CHECK_EQ(out["occurrences"][1]["items"][0]["unitIds"][0].get<int>(),1);
}
TEST_CASE("One unavailable equipment occurrence makes the complete proposal infeasible") {
    auto in=equipmentSeries();in["units"][0]["reservations"]={in["occurrences"][1]};
    auto out=executeEquipmentSeries(in);CHECK(!out["feasible"].get<bool>());
    CHECK(out["occurrences"][0]["feasible"].get<bool>());CHECK(!out["occurrences"][1]["feasible"].get<bool>());
    CHECK(out["items"].empty());
}
TEST_CASE("Equipment series may choose different eligible physical units per period") {
    auto in=equipmentSeries();auto unit=in["units"][0];unit["id"]=2;unit["reservations"]={in["occurrences"][1]};
    in["units"][0]["reservations"]={in["occurrences"][0]};in["units"].push_back(unit);
    auto out=executeEquipmentSeries(in);CHECK(out["feasible"].get<bool>());
    CHECK_EQ(out["occurrences"][0]["items"][0]["unitIds"][0].get<int>(),2);
    CHECK_EQ(out["occurrences"][1]["items"][0]["unitIds"][0].get<int>(),1);
}
TEST_CASE("Overdue unreturned equipment is unavailable in every later series occurrence") {
    auto in=equipmentSeries();in["units"][0]["held"]=true;
    auto out=executeEquipmentSeries(in);CHECK(!out["feasible"].get<bool>());
    CHECK(out["occurrences"][0]["items"][0]["unitIds"].empty());
    CHECK(out["occurrences"][1]["items"][0]["unitIds"].empty());
}
TEST_CASE("Equipment series never silently reduces quantity") {
    auto in=equipmentSeries();in["items"][0]["quantity"]=2;
    auto out=executeEquipmentSeries(in);CHECK(!out["feasible"].get<bool>());
    for(const auto& row:out["occurrences"])CHECK(row["items"][0]["unitIds"].empty());
}
TEST_CASE("Equipment series validates complete sorted periods and distinct operation") {
    auto in=equipmentSeries();in["occurrences"]=nlohmann::json::array();executeEquipmentSeries(in,2);
    in=equipmentSeries();in["occurrences"][1]=in["proposed"];executeEquipmentSeries(in,2);
    in=equipmentSeries();in["operation"]="equipment";executeEquipmentSeries(in,2);
}
