#include "test_framework.h"
#include "src/services/RoomSelectionService.h"
#include "src/models/SpaceFactory.h"
#include "src/integration/RoomRequestJsonProtocol.h"
#include "src/vendor/nlohmann/json.hpp"
#include <sstream>

namespace {
StudentRoomOption room(int id, int capacity, int faculty = 1) {
    StudentRoomOption r;
    r.space.reset(SpaceFactory::createSpace(id,"Campus room","Classroom",capacity,true,true,false,true,"Main"));
    r.enabled=true; r.facultyId=faculty; r.approverId=10;
    r.categories={"study","meeting","lecture","club","other"};
    return r;
}
RoomSelectionInput fixture() {
    RoomSelectionInput in;
    in.organizerId=1; in.attendeeCount=10; in.category="study"; in.strategy="best_fit";
    in.proposed={1800000000,1800003600}; in.horizon={1800000000,1800086400};
    in.rooms={room(101,30),room(102,10),room(103,10,2)};
    return in;
}
nlohmann::json document() {
    using nlohmann::json;
    return {{"protocolVersion",1},{"operation","studentRoom"},{"runId","rooms-test"},{"action","recommend"},
            {"organizerId",1},{"organizerRole","Student"},{"attendeeCount",10},{"category","study"},{"strategy","best_fit"},
            {"requiredFeatures",json::array()},{"preferredFacultyId",0},{"preferredBuilding",""},{"organizerResolved",true},
            {"organizerBusy",json::array()},{"proposed",{{"start",1800000000},{"end",1800003600}}},
            {"horizon",{{"start",1800000000},{"end",1800086400}}},
            {"rooms", {{{"id",101},{"name","Study, \"Lab\""},{"type","Laboratory"},{"capacity",20},{"building","Main"},
                         {"available",true},{"features",{{"projector",true},{"whiteboard",true},{"computers",true}}},
                         {"facultyId",1},{"approverId",10},{"enabled",true},{"restricted",false},{"calendarResolved",true},
                         {"allowedUserIds",json::array()},{"categories",{"study","meeting","lecture","club","other"}},{"busy",json::array()}}}}};
}
nlohmann::json execute(nlohmann::json input, int expected=0) {
    std::istringstream in(input.dump()); std::ostringstream out,diagnostics;
    CHECK_EQ(RoomRequestJsonProtocol::run(in,out,diagnostics),expected);
    CHECK_EQ(out.str().back(),'\n');
    return nlohmann::json::parse(out.str());
}
}

TEST_CASE("Student rooms rank single distinct physical rooms by best fit") {
    auto in=fixture(); auto result=RoomSelectionService::rank(in,in.proposed);
    CHECK_EQ(result.size(),std::size_t(3)); CHECK_EQ(result[0].roomId,102); CHECK_EQ(result[1].roomId,103);
    CHECK_EQ(result[0].spareSeats,0); CHECK_EQ(result.back().roomId,101);
}
TEST_CASE("Student rooms support all permitted purposes with the same policy") {
    auto in=fixture();
    for(const std::string category:{"study","meeting","lecture","club","other"}) {
        in.category=category; CHECK(!RoomSelectionService::rank(in,in.proposed).empty());
    }
}
TEST_CASE("Student room capacity facilities access ownership and approvers are mandatory") {
    auto in=fixture(); auto r=room(101,5);
    CHECK_EQ(RoomSelectionService::roomReason(in,r,in.proposed),"INSUFFICIENT_CAPACITY");
    r=room(101,30); in.requiredFeatures={"computers"};
    CHECK_EQ(RoomSelectionService::roomReason(in,r,in.proposed),"MISSING_FACILITY");
    in.requiredFeatures={"projector","whiteboard"}; CHECK_EQ(RoomSelectionService::roomReason(in,r,in.proposed),"AVAILABLE");
    r.restricted=true; CHECK_EQ(RoomSelectionService::roomReason(in,r,in.proposed),"ACCESS_RESTRICTED");
    r.allowedUserIds={1}; CHECK_EQ(RoomSelectionService::roomReason(in,r,in.proposed),"AVAILABLE");
    r.approverId=0; CHECK_EQ(RoomSelectionService::roomReason(in,r,in.proposed),"NO_APPROVER");
}
TEST_CASE("Student room preferences do not grant access or restrict another faculty") {
    auto in=fixture(); in.preferredFacultyId=2;
    auto result=RoomSelectionService::rank(in,in.proposed); CHECK_EQ(result.front().roomId,103);
    CHECK_EQ(result.size(),std::size_t(3));
    in.rooms[2].restricted=true;
    result=RoomSelectionService::rank(in,in.proposed); CHECK_EQ(result.front().roomId,102);
}
TEST_CASE("Dated room closures and academic commitments use half open intervals") {
    auto in=fixture(); in.rooms[0].busy={{1800000000,1800003600}};
    CHECK_EQ(RoomSelectionService::roomReason(in,in.rooms[0],in.proposed),"ROOM_BUSY");
    CHECK_EQ(RoomSelectionService::roomReason(in,in.rooms[0],{1800003600,1800007200}),"AVAILABLE");
    CHECK_EQ(RoomSelectionService::roomReason(in,in.rooms[0],{1800604800,1800608400}),"AVAILABLE");
}
TEST_CASE("Unmapped room or organizer calendars never masquerade as free") {
    auto in=fixture(); in.rooms[1].calendarResolved=false;
    CHECK_EQ(RoomSelectionService::roomReason(in,in.rooms[1],in.proposed),"UNRESOLVED_CALENDAR");
    in.organizerResolved=false; CHECK(RoomSelectionService::rank(in,in.proposed).empty());
}
TEST_CASE("Organizer appointments block room selection but adjacent times are valid") {
    auto in=fixture(); in.organizerBusy={in.proposed};
    CHECK(RoomSelectionService::rank(in,in.proposed).empty());
    CHECK(!RoomSelectionService::rank(in,{1800003600,1800007200}).empty());
}
TEST_CASE("Greedy room selection preserves source order within preference ties") {
    auto in=fixture(); in.strategy="greedy";
    CHECK_EQ(RoomSelectionService::rank(in,in.proposed).front().roomId,101);
}
TEST_CASE("Room protocol preserves structured candidates and standard text escaping") {
    auto in=document(); in["rooms"][0]["name"]="Study, \"Lab\" \u00dc\n";
    auto result=execute(in); CHECK(result["feasible"].get<bool>());
    CHECK_EQ(result["candidates"][0]["roomId"].get<int>(),101);
    CHECK_EQ(result["candidates"][0]["spareSeats"].get<int>(),10);
}
TEST_CASE("Room protocol never substitutes another room for a stale selection") {
    auto in=document(); in["action"]="validate"; in["selectedRoomId"]=999;
    auto result=execute(in); CHECK(!result["feasible"].get<bool>()); CHECK(result["candidates"].empty());
    CHECK(result["alternatives"].empty());
}
TEST_CASE("Room protocol offers only feasible alternative times after a conflict") {
    auto in=document(); in["rooms"][0]["busy"]={{{"start",1800000000},{"end",1800003600}}};
    auto result=execute(in); CHECK(!result["feasible"].get<bool>());
    CHECK(!result["alternatives"].empty()); CHECK(result["alternatives"][0]["start"].get<long long>()>=1800003600);
}
TEST_CASE("Room protocol rejects malformed numeric policy and strategy values") {
    auto original=document();
    for(const std::string key:{"protocolVersion","attendeeCount","organizerId"}) {
        auto in=original; in[key]=-1; CHECK_EQ(execute(in,2)["status"].get<std::string>(),"error");
    }
    auto in=original; in["strategy"]="shared_room_exam_best_fit"; execute(in,2);
    in=original; in["rooms"][0]["available"]="true"; execute(in,2);
    in=original; in["rooms"][0]["type"]="Unknown"; execute(in,2);
    in=original; in["requiredFeatures"]={"invented"}; execute(in,2);
}

namespace {
nlohmann::json roomSeries() {
    auto in=document();in["operation"]="studentRoomSeries";in["startMinutes"]=600;
    in["horizon"]={{"start",1799966400},{"end",1800777600}};
    in["occurrences"]={in["proposed"],{{"start",1800604800},{"end",1800608400}}};
    return in;
}
nlohmann::json executeRoomSeries(nlohmann::json value,int expected=0) {
    std::istringstream in(value.dump());std::ostringstream out,err;
    CHECK_EQ(RoomRequestJsonProtocol::run(in,out,err,true),expected);
    return nlohmann::json::parse(out.str());
}
}
TEST_CASE("Dated room series keep one common room in existing deterministic rank order") {
    auto in=fixture();auto values=RoomSelectionService::rankSeries(in,{in.proposed,{1800604800,1800608400}});
    CHECK_EQ(values.size(),std::size_t(3));CHECK_EQ(values.front().roomId,102);
}
TEST_CASE("One conflicting room date excludes that room from the complete series") {
    auto in=fixture();in.rooms[1].busy={{1800604800,1800608400}};
    auto values=RoomSelectionService::rankSeries(in,{in.proposed,{1800604800,1800608400}});
    CHECK_EQ(values.size(),std::size_t(2));CHECK_EQ(values.front().roomId,103);
}
TEST_CASE("Alternating available rooms cannot silently substitute across a series") {
    auto in=fixture();in.rooms.resize(2);in.rooms[0].busy={in.proposed};in.rooms[1].busy={{1800604800,1800608400}};
    CHECK(RoomSelectionService::rankSeries(in,{in.proposed,{1800604800,1800608400}}).empty());
}
TEST_CASE("Room series intersection precedes the twenty candidate presentation limit") {
    auto in=roomSeries();auto example=in["rooms"][0];in["rooms"]=nlohmann::json::array();
    for(int i=0;i<25;++i){auto r=example;r["id"]=100+i;if(i<24)r["busy"]={in["occurrences"][1]};in["rooms"].push_back(r);}
    auto out=executeRoomSeries(in);CHECK(out["feasible"].get<bool>());
    CHECK_EQ(out["candidates"].size(),std::size_t(1));CHECK_EQ(out["candidates"][0]["roomId"].get<int>(),124);
    CHECK_EQ(out["occurrences"].size(),std::size_t(2));
}
TEST_CASE("Room series protocol reports dated conflicts and feasible whole pattern time alternatives") {
    auto in=roomSeries();in["rooms"][0]["busy"]={in["occurrences"][1]};
    auto out=executeRoomSeries(in);CHECK(!out["feasible"].get<bool>());
    CHECK(out["occurrences"][0]["feasible"].get<bool>());CHECK(!out["occurrences"][1]["feasible"].get<bool>());
    CHECK(!out["alternatives"].empty());CHECK(out["alternatives"][0].contains("offsetMinutes"));
}
TEST_CASE("Optional professor acceptance validates every dated room occurrence") {
    auto in=roomSeries();in["action"]="attendance";in["organizerRole"]="Instructor";in["organizerBusy"]={in["occurrences"][1]};
    auto out=executeRoomSeries(in);CHECK(!out["feasible"].get<bool>());CHECK_EQ(out["reasonCode"].get<std::string>(),"ORGANIZER_BUSY");
}
TEST_CASE("Room series protocol rejects empty overlapping and mismatched occurrences") {
    auto missing=roomSeries();missing.erase("startMinutes");executeRoomSeries(missing,2);
    auto in=roomSeries();in["occurrences"]=nlohmann::json::array();executeRoomSeries(in,2);
    in=roomSeries();in["occurrences"][1]=in["proposed"];executeRoomSeries(in,2);
    in=roomSeries();in["occurrences"][1]["end"]=1800608460;executeRoomSeries(in,2);
    in=roomSeries();in["operation"]="studentRoom";executeRoomSeries(in,2);
}
