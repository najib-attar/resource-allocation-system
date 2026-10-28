// CDMCS Implementation I1 -- standalone read-only research scheduling engine.
// Model port: V15 explicit minute grid, with V16 normalization performed by caller.
// Boost.JSON header-only compilation; no application database, bookings or writes.
#include <boost/json.hpp>
#include <boost/json/src.hpp>
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <exception>
#include <iostream>
#include <limits>
#include <map>
#include <new>
#include <set>
#include <stdexcept>
#include <string>
#include <tuple>
#include <utility>
#include <vector>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

namespace j = boost::json;
using i64 = std::int64_t;
static void require(bool condition, const std::string& why) { if (!condition) throw std::invalid_argument(why); }
// Fail the entire request, never publish an incomplete top-K as an exact result.
struct WorkBudget {
    std::size_t remaining=10000000;
    void spend(std::size_t units=1) {
        require(units<=remaining,"search work resource limit exceeded");
        remaining-=units;
    }
};
static const j::object& obj(const j::value& v, const char* field) {
    require(v.is_object(), std::string(field)+" must be an object"); return v.as_object();
}
static const j::array& arr(const j::value& v,const char* field) {
    require(v.is_array(), std::string(field)+" must be an array"); return v.as_array();
}
static const j::value& get(const j::object& o, const char* k) {
    auto it=o.find(k); require(it!=o.end(),std::string("missing field: ")+k); return it->value();
}
static i64 number(const j::value& v,const char* field) {
    require(v.is_int64() || v.is_uint64(),std::string(field)+" must be an integer");
    if(v.is_uint64()) {require(v.as_uint64()<=static_cast<std::uint64_t>(INT64_MAX),std::string(field)+" out of range");return static_cast<i64>(v.as_uint64());}
    return v.as_int64();
}
static int integer(const j::value& v,const char* field) {
    auto n=number(v,field);require(n>=INT32_MIN && n<=INT32_MAX,std::string(field)+" out of int range");return static_cast<int>(n);
}
static std::string string(const j::value& v,const char* field) {
    require(v.is_string(),std::string(field)+" must be a string");
    require(v.as_string().size()<=256,std::string(field)+" exceeds 256 bytes");
    return std::string(v.as_string());
}
static bool boolean(const j::value& v,const char* field) {
    require(v.is_bool(),std::string(field)+" must be a boolean");return v.as_bool();
}
static int opt_int(const j::object& o,const char* k,int def){auto it=o.find(k);return it==o.end()?def:integer(it->value(),k);}
static std::vector<std::string> strings(const j::value& v,const char* key){
    const auto& a=arr(v,key);require(a.size()<=256,std::string(key)+" exceeds 256 members");
    std::vector<std::string> r;std::set<std::string> seen;
    for(const auto& el:a){auto s=string(el,key);require(!s.empty() && seen.insert(s).second,std::string(key)+" has blank or duplicate member");r.push_back(s);}return r;
}
static std::vector<int> ints(const j::value& v,const char* key){
    const auto& a=arr(v,key);std::vector<int> r;r.reserve(a.size());for(const auto& x:a) r.push_back(integer(x,key));return r;
}
static std::vector<i64> ints64(const j::value& v,const char* key){
    const auto& a=arr(v,key);std::vector<i64> r;r.reserve(a.size());for(const auto& x:a)r.push_back(number(x,key));return r;
}
static j::array to_array(const std::vector<std::string>& list){j::array a;for(auto& s:list)a.emplace_back(j::string(s));return a;}

struct Meeting {
    std::string id;
    int start=0, duration=0;
    std::vector<std::string> people,resources;
    bool flexible=false;
    int end() const {return start+duration;}
    std::vector<std::string> keys() const {
        std::vector<std::string> keys;keys.reserve(people.size()+resources.size());
        for(const auto& p:people) keys.push_back("p:"+p);
        for(const auto& r:resources) keys.push_back("r:"+r);
        return keys;
    }
};
static bool overlap(const Meeting& a,const Meeting& b){return a.start<b.end() && b.start<a.end();}
static bool conflict(const Meeting& a,const Meeting& b,WorkBudget& work){
    if(!overlap(a,b)) return false;
    const auto ak=a.keys(),bk=b.keys();
    work.spend(ak.size()*bk.size());
    for(const auto& k:ak) if(std::find(bk.begin(),bk.end(),k)!=bk.end())return true;
    return false;
}
struct Profile {
    std::vector<i64> prefix;
    std::vector<std::pair<int,int>> published,exceptions;
    int preferred_break=15,gap_weight=1,nearby_limit=120,exception_fee=30;
    i64 event_cost(const Meeting& e)const{return prefix.at(e.end())-prefix.at(e.start);}
};
struct Case {
    int horizon=0,duration=0,move_fixed_cost=20,move_participant_cost=5,delay_per_day=5,limit=5;
    std::vector<int> starts,replacements,days;
    std::vector<Meeting> existing;
    std::vector<std::string> people,resources;
    std::map<std::string,Profile> profiles;
    std::set<std::string> unresolved;
    int earliest=0;
    Meeting proposal(int t)const{return Meeting{"NEW",t,duration,people,resources,false};}
};
static std::vector<std::pair<int,int>> windows(const j::value& v,int horizon,const char* label){
    std::vector<std::pair<int,int>> r;
    require(arr(v,label).size()<=1024,"availability window count exceeds 1024");
    for(const auto& w:arr(v,label)){
        const auto& a=arr(w,label);require(a.size()==2,"window needs [start,end]");
        int l=integer(a[0],label),h=integer(a[1],label);
        require(0<=l && l<h && h<=horizon,"availability window outside horizon or nonpositive");r.emplace_back(l,h);
    }return r;
}
static Meeting read_meeting(const j::value& v){
    const auto& o=obj(v,"meeting");Meeting m;
    m.id=string(get(o,"id"),"id");m.start=integer(get(o,"start"),"start");
    m.duration=integer(get(o,"duration"),"duration");
    m.people=strings(get(o,"people"),"people");m.resources=strings(get(o,"resources"),"resources");
    if(auto it=o.find("flexible");it!=o.end())m.flexible=boolean(it->value(),"flexible");
    return m;
}
static Case read_case(const j::value& value){
    const auto& o=obj(value,"request");
    require(string(get(o,"operation"),"operation")=="cdmcs_schedule_v1","operation must be cdmcs_schedule_v1");
    Case c;c.horizon=integer(get(o,"horizon_minutes"),"horizon_minutes");
    require(c.horizon>0 && c.horizon<=100800,"horizon must be between 1 and 100800 minutes");
    c.duration=integer(get(o,"duration"),"duration");
    require(c.duration>0 && c.duration<=c.horizon,"invalid new meeting duration");
    c.starts=ints(get(o,"candidate_starts"),"candidate_starts");
    c.replacements=ints(get(o,"replacement_starts"),"replacement_starts");
    require(!c.starts.empty() && c.starts.size()<=10000 && c.replacements.size()<=10000,"bad candidate count");
    auto unique=[](const std::vector<int>& a){return std::set<int>(a.begin(),a.end()).size()==a.size();};
    require(unique(c.starts)&&unique(c.replacements),"candidate times must be unique");
    for(int t:c.starts)require(t>=0 && t<=c.horizon-c.duration,"new candidate outside horizon");
    for(int t:c.replacements)require(t>=0 && t<c.horizon,"replacement candidate outside horizon");
    require(static_cast<i64>(c.starts.size())*std::max<std::size_t>(1,c.replacements.size())<=2000000,"candidate-pair resource limit exceeded");
    c.earliest=*std::min_element(c.starts.begin(),c.starts.end());
    c.people=strings(get(o,"required_people"),"required_people");
    c.resources=strings(get(o,"required_resources"),"required_resources");
    require(!c.people.empty(),"at least one required participant");
    c.days=ints(get(o,"local_day_index"),"local_day_index");
    require(c.days.size()==static_cast<std::size_t>(c.horizon)+1,"local_day_index must contain horizon+1 minute entries");
    for(std::size_t i=1;i<c.days.size();++i)require(c.days[i]>=c.days[i-1],"local day index must be nondecreasing");
    if(auto it=o.find("unresolved_people");it!=o.end()){
        for(auto& s:strings(it->value(),"unresolved_people"))c.unresolved.insert(s);
    }
    if(auto it=o.find("move_fixed_cost");it!=o.end())c.move_fixed_cost=integer(it->value(),"move_fixed_cost");
    if(auto it=o.find("move_participant_cost");it!=o.end())c.move_participant_cost=integer(it->value(),"move_participant_cost");
    if(auto it=o.find("delay_per_day");it!=o.end())c.delay_per_day=integer(it->value(),"delay_per_day");
    c.limit=opt_int(o,"limit",5);
    require(c.limit>=1 && c.limit<=100 && c.move_fixed_cost>=0 && c.move_fixed_cost<=10000000
        && c.move_participant_cost>=0 && c.move_participant_cost<=10000000
        && c.delay_per_day>=0 && c.delay_per_day<=10000000,"invalid costs or output limit");
    const auto& existing=arr(get(o,"existing"),"existing");
    require(existing.size()<=10000,"too many existing meetings");
    std::size_t memberships=0;
    for(const auto& x:existing){
        auto meeting=read_meeting(x);
        memberships+=meeting.people.size()+meeting.resources.size();
        require(memberships<=100000,"calendar membership resource limit exceeded");
        c.existing.push_back(std::move(meeting));
    }
    std::set<std::string> ids;
    for(const auto& m:c.existing){
        require(!m.id.empty() && m.id!="NEW" && ids.insert(m.id).second,"duplicate or reserved meeting ID");
        require(m.start>=0 && m.duration>0 && m.duration<=c.horizon-m.start,"existing meeting outside horizon");
    }
    const auto& p=obj(get(o,"profiles"),"profiles");
    require(p.size()<=256,"too many profiles");
    require(static_cast<i64>(p.size())*(c.horizon+1)<=3000000,"preference data size limit exceeded");
    for(const auto& kv:p){
        require(!kv.key().empty() && kv.key().size()<=256,"invalid profile identifier");
        auto name=std::string(kv.key());const auto& po=obj(kv.value(),"profile");Profile prof;
        prof.prefix=ints64(get(po,"rate_prefix"),"rate_prefix");
        require(prof.prefix.size()==static_cast<std::size_t>(c.horizon)+1,"rate_prefix needs horizon+1 elements");
        require(prof.prefix.front()==0,"rate_prefix must start at 0");
        for(std::size_t i=1;i<prof.prefix.size();++i)
            require(prof.prefix[i]>=prof.prefix[i-1] && prof.prefix[i]>=0 && prof.prefix[i]<=1000000000000LL
                && prof.prefix[i]-prof.prefix[i-1]<=100000000LL,"rate_prefix must be bounded, nonnegative and nondecreasing");
        prof.published=windows(get(po,"published"),c.horizon,"published");
        prof.exceptions=windows(get(po,"exceptions"),c.horizon,"exceptions");
        prof.preferred_break=opt_int(po,"preferred_break",15);
        prof.gap_weight=opt_int(po,"gap_weight",1);
        prof.nearby_limit=opt_int(po,"nearby_limit",120);
        prof.exception_fee=opt_int(po,"exception_fee",30);
        require(prof.preferred_break>=0 && prof.preferred_break<=1440 && prof.gap_weight>=0 && prof.gap_weight<=100000
            && prof.nearby_limit>=0 && prof.nearby_limit<=10080 && prof.exception_fee>=0 && prof.exception_fee<=10000000,
            "invalid preference parameters");
        c.profiles.emplace(name,std::move(prof));
    }
    for(const auto& p:c.people)require(c.profiles.count(p)>0,"missing profile for new participant "+p);
    for(const auto& m:c.existing)for(const auto& p:m.people)require(c.profiles.count(p)>0,"missing profile for existing participant "+p);
    // A valid input has no two baseline commitments that compete for one key.
    std::map<std::string,std::vector<const Meeting*>> keys;
    for(const auto& m:c.existing)for(const auto& key:m.keys())keys[key].push_back(&m);
    for(auto& kv:keys){
        auto& ev=kv.second;std::sort(ev.begin(),ev.end(),[](const Meeting* a,const Meeting* b){return std::tie(a->start,a->id)<std::tie(b->start,b->id);});
        for(std::size_t i=1;i<ev.size();++i)require(ev[i-1]->end()<=ev[i]->start,"overlapping baseline commitments: "+kv.first);
    }
    return c;
}
static bool covered(const Meeting& e,const std::vector<std::pair<int,int>>& windows,WorkBudget& work){
    for(const auto& w:windows){work.spend();if(w.first<=e.start && e.end()<=w.second)return true;}
    return false;
}
static bool requests(const Case& c,const Meeting& e,std::vector<std::string>& pending,WorkBudget& work){
    for(const auto& p:e.people){
        work.spend();
        if(c.unresolved.count(p))return false;
        const auto& prof=c.profiles.at(p);
        if(covered(e,prof.published,work))continue;
        if(!covered(e,prof.exceptions,work))return false;
        pending.push_back(p);
    }
    return true;
}
struct IntervalIndex {
    std::map<std::string,std::vector<const Meeting*>> keys;
    explicit IntervalIndex(const Case& c){
        for(const auto& e:c.existing)for(const auto& k:e.keys())keys[k].push_back(&e);
        for(auto& kv:keys)std::sort(kv.second.begin(),kv.second.end(),[](auto a,auto b){return a->start<b->start;});
    }
    std::map<std::string,const Meeting*> blockers(const Meeting& e,WorkBudget& work,const std::string& ignore="")const{
        std::map<std::string,const Meeting*> found;
        for(const auto& key:e.keys()){
            work.spend();
            auto it=keys.find(key);if(it==keys.end())continue;
            const auto& cal=it->second;
            auto bound=std::lower_bound(cal.begin(),cal.end(),e.end(),[](const Meeting* a,int end){return a->start<end;});
            while(bound!=cal.begin()){
                work.spend();
                --bound;auto* other=*bound;
                if(other->end()<=e.start)break;
                if(other->id!=ignore)found.emplace(other->id,other);
            }
        }return found;
    }
};
struct PersonIndex {
    std::map<std::string,std::vector<const Meeting*>> cals;
    explicit PersonIndex(const Case& c){
        for(const auto& e:c.existing)for(const auto& p:e.people)cals[p].push_back(&e);
        for(auto& [p,ev]:cals)std::sort(ev.begin(),ev.end(),[](auto a,auto b){return std::tie(a->start,a->id)<std::tie(b->start,b->id);});
    }
    using Key=std::pair<int,std::string>;
    static Key key(const Meeting& m){return {m.start,m.id};}
    std::pair<const Meeting*,const Meeting*> neighbors(const std::string& person,const Meeting& target,
                               const std::string& ignore,const Meeting* overlay=nullptr)const{
        const Meeting* prev=nullptr;const Meeting* next=nullptr;
        auto it=cals.find(person);
        if(it!=cals.end()){
            auto const& cal=it->second;
            auto bound=std::lower_bound(cal.begin(),cal.end(),key(target),[](const Meeting* m,const Key& k){return key(*m)<k;});
            auto left=bound;
            while(left!=cal.begin()){
                --left;
                if((*left)->id!=ignore){prev=*left;break;}
            }
            for(auto right=bound;right!=cal.end();++right){
                if((*right)->id!=ignore){next=*right;break;}
            }
        }
        if(overlay){
            if(key(*overlay)<key(target) && (!prev||key(*overlay)>key(*prev)))prev=overlay;
            if(key(*overlay)>key(target) && (!next||key(*overlay)<key(*next)))next=overlay;
        }
        return {prev,next};
    }
};
static i64 gap(const Profile& prof,const Case& c,const Meeting* left,const Meeting* right){
    if(!left||!right)return 0;
    int g=right->start-left->end();require(g>=0,"negative gap in scored calendar");
    if(g>prof.nearby_limit || c.days[left->start]!=c.days[right->start])return 0;
    return static_cast<i64>(std::abs(g-prof.preferred_break))*prof.gap_weight;
}
static i64 person_delta(const Case& c,const PersonIndex& pc,const std::string& person,
                        const Meeting& add,const Meeting* orig,const Meeting* moved){
    const auto& prof=c.profiles.at(person);
    const bool add_participant=std::find(add.people.begin(),add.people.end(),person)!=add.people.end();
    const bool moved_participant=moved && std::find(moved->people.begin(),moved->people.end(),person)!=moved->people.end();
    std::string ignore=moved_participant?orig->id:"";
    i64 value=0;
    if(moved_participant){
        auto [a,b]=pc.neighbors(person,*orig,ignore);
        value-=prof.event_cost(*orig)+gap(prof,c,a,orig)+gap(prof,c,orig,b);
        value+=gap(prof,c,a,b);
    }
    if(add_participant){
        auto [a,b]=pc.neighbors(person,add,ignore);
        value+=prof.event_cost(add)+gap(prof,c,a,&add)+gap(prof,c,&add,b)-gap(prof,c,a,b);
    }
    if(moved_participant){
        auto [a,b]=pc.neighbors(person,*moved,ignore,add_participant?&add:nullptr);
        value+=prof.event_cost(*moved)+gap(prof,c,a,moved)+gap(prof,c,moved,b)-gap(prof,c,a,b);
    }
    return value;
}
struct Score {
    i64 cost=0,fairness=0;
    int start=0,moved_start=-1;
    std::string moved_id;
    std::vector<std::string> new_exceptions,moved_exceptions,move_approvals;
    auto sort_key()const {return std::make_tuple(cost,fairness,start,moved_id,moved_start);}
};
static Score score(const Case& c,const PersonIndex& pc,const Meeting& add,const Meeting* original,const Meeting* moved,
                   const std::vector<std::string>& new_ex,const std::vector<std::string>& moved_ex,WorkBudget& work){
    const auto people=add.people.size()+(moved?moved->people.size():0);
    work.spend(people*(people+64));
    Score s;s.start=add.start;s.new_exceptions=new_ex;s.moved_exceptions=moved_ex;
    if(moved){s.moved_id=moved->id;s.moved_start=moved->start;s.move_approvals=moved->people;}
    std::map<std::string,i64> burdens;
    for(const auto& p:new_ex)burdens[p]+=c.profiles.at(p).exception_fee;
    for(const auto& p:moved_ex)burdens[p]+=c.profiles.at(p).exception_fee;
    if(moved)for(const auto& p:moved->people)burdens[p]+=c.move_participant_cost;
    std::set<std::string> affected(add.people.begin(),add.people.end());
    if(moved)affected.insert(moved->people.begin(),moved->people.end());
    for(const auto& p:affected)burdens[p]+=person_delta(c,pc,p,add,original,moved);
    for(const auto& kv:burdens){s.cost+=kv.second;s.fairness=std::max(s.fairness,std::max<i64>(0,kv.second));}
    s.cost+=(moved?c.move_fixed_cost:0)+(static_cast<i64>(c.days[add.start])-c.days[c.earliest])*c.delay_per_day;
    return s;
}
static j::object as_json(const Score& s,const Case& c){
    j::object o;
    o["start_minute"]=s.start;o["end_minute"]=s.start+c.duration;
    o["total_cost"]=s.cost;o["fairness_max_burden"]=s.fairness;
    o["moved_meeting_id"]=s.moved_id.empty()?j::value(nullptr):j::value(s.moved_id);
    o["replacement_start_minute"]=s.moved_id.empty()?j::value(nullptr):j::value(s.moved_start);
    j::object permissions;
    permissions["new_meeting_extra_availability"]=to_array(s.new_exceptions);
    permissions["relocated_meeting_extra_availability"]=to_array(s.moved_exceptions);
    permissions["relocation_participant_approval"]=to_array(s.move_approvals);
    o["required_permissions"]=std::move(permissions);
    o["proposal_status"]=(s.moved_id.empty()&&s.new_exceptions.empty())?"DIRECT_PENDING_NORMAL_MEETING_APPROVAL":"CONDITIONAL_PENDING_APPROVAL";
    return o;
}
static j::value solve(const Case& c){
    j::object out;out["operation"]="cdmcs_schedule_v1";out["model"]="V15_restricted_one_blocking_move";
    for(const auto& p:c.people)if(c.unresolved.count(p)){
        out["status"]="UNRESOLVED_CALENDAR";out["solutions_evaluated"]=0;
        out["returned_count"]=0;out["truncated"]=false;
        out["recommendations"]=j::array();return out;
    }
    IntervalIndex ix(c);PersonIndex pc(c);
    WorkBudget work;
    std::size_t cached_members=0;
    std::map<std::string,std::vector<std::pair<Meeting,std::vector<std::string>>>> rep_cache;
    std::vector<Score> top;
    i64 count=0;
    auto keep=[&](Score s){++count;top.push_back(std::move(s));
        std::sort(top.begin(),top.end(),[](const Score& a,const Score& b){return a.sort_key()<b.sort_key();});
        if(top.size()>static_cast<std::size_t>(c.limit))top.pop_back();};
    for(int t:c.starts){
        work.spend();
        Meeting newmeet=c.proposal(t);std::vector<std::string> newex;
        if(!requests(c,newmeet,newex,work))continue;
        auto blockers=ix.blockers(newmeet,work);
        if(blockers.empty()){
            keep(score(c,pc,newmeet,nullptr,nullptr,newex,{},work));continue;
        }
        if(blockers.size()!=1)continue;
        const Meeting* old=blockers.begin()->second;
        if(!old->flexible)continue;
        if(!rep_cache.count(old->id)){
            auto& reps=rep_cache[old->id];
            for(int r:c.replacements){
                work.spend();
                if(r+old->duration>c.horizon)continue;
                Meeting moved=*old;moved.start=r;
                std::vector<std::string> ex;
                if(!requests(c,moved,ex,work)||!ix.blockers(moved,work,old->id).empty())continue;
                cached_members+=1+moved.people.size()+moved.resources.size()+ex.size();
                require(cached_members<=250000,"replacement cache resource limit exceeded");
                reps.emplace_back(std::move(moved),std::move(ex));
            }
        }
        for(const auto& [moved,movex]:rep_cache[old->id]){
            if(conflict(newmeet,moved,work))continue;
            keep(score(c,pc,newmeet,old,&moved,newex,movex,work));
        }
    }
    out["status"]=count?"OK":"NO_FEASIBLE_PROPOSAL";
    out["solutions_evaluated"]=count;
    out["returned_count"]=static_cast<i64>(top.size());
    out["truncated"]=count>static_cast<i64>(top.size());
    j::array rec;for(const auto& s:top)rec.push_back(as_json(s,c));out["recommendations"]=std::move(rec);
    return out;
}
int main(){
    try{
#ifdef _WIN32
        // Protocol bytes must not undergo CRLF or Ctrl-Z text-mode translation.
        if(_setmode(_fileno(stdin),_O_BINARY)==-1 || _setmode(_fileno(stdout),_O_BINARY)==-1)
            throw std::runtime_error("cannot configure binary protocol streams");
#endif
        constexpr std::size_t max_bytes=16*1024*1024;
        std::string input;
        std::array<char,65536> chunk{};
        while(std::cin){
            std::cin.read(chunk.data(),static_cast<std::streamsize>(chunk.size()));
            const auto count=static_cast<std::size_t>(std::cin.gcount());
            require(count<=max_bytes-input.size(),"stdin exceeds 16 MiB resource limit");
            input.append(chunk.data(),count);
        }
        require(!std::cin.bad(),"stdin read failure");
        require(!input.empty(),"empty stdin");
        boost::system::error_code error;
        auto document=j::parse(input,error);
        require(!error,"malformed JSON");
        auto c=read_case(document);std::cout<<j::serialize(solve(c))<<'\n';return 0;
    }catch(const std::bad_alloc&){
        std::cout<<"{\"status\":\"ENGINE_ERROR\",\"error\":\"memory allocation failed\"}\n";return 3;
    }catch(const std::invalid_argument& e){
        j::object result;result["status"]="INVALID_INPUT";result["error"]=e.what();
        std::cout<<j::serialize(result)<<'\n';return 2;
    }catch(const std::exception&){
        std::cout<<"{\"status\":\"ENGINE_ERROR\",\"error\":\"unexpected engine failure\"}\n";return 3;
    }
}
