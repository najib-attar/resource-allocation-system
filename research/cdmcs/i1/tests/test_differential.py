#!/usr/bin/env python3
"""Independent cross-language oracle: original V15 all-pairs feasibility + FULL cost.
No C++ source or application files are modified by this test.
"""
from __future__ import annotations
import argparse
import json
import random
import subprocess
import sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HERE=Path(__file__).resolve().parent
# External original research source is only used as an independent test oracle.
V15=HERE/'original_reference'
sys.path.insert(0,str(V15))
from cdmcs_v1_reference_prototype import Meeting, conflicts
from cdmcs_v15_minute_domain import (build_profile, MinuteCase, independently_feasible,
                                   full_score, exception_requests)

ANCHOR=datetime(2026,10,26,tzinfo=timezone.utc)

def fixture_profiles(horizon, anchor=ANCHOR, zone='Europe/Istanbul', profiles=('A','B','C','D'), published=None, exceptions=None, preferred_break=15, fee=30):
    pub=tuple(published if published is not None else [(0,horizon)])
    extra=tuple(exceptions if exceptions is not None else ())
    return {p:build_profile(anchor_utc=anchor,zone_name=zone,horizon_minutes=horizon,
        weekday_penalty=(1,2,3,4,5,6,7),
        preferred_bands={d:((8*60,12*60),(13*60,17*60)) for d in range(7)},
        published=pub,exceptions=extra,nonpreferred_hour_penalty=2,preferred_break=preferred_break,
        gap_weight=1,nearby_limit=120,exception_fee=fee) for p in profiles}

def encode(case):
    profile=next(iter(case.profiles.values()))
    local_days=[(profile.anchor+timedelta(minutes=i)).astimezone(profile.zone).date().toordinal()
                for i in range(len(profile.prefix))]
    return {'operation':'cdmcs_schedule_v1','horizon_minutes':len(profile.prefix)-1,
            'duration':case.duration,'candidate_starts':list(case.candidate_starts),
            'replacement_starts':list(case.replacement_starts),'required_people':list(case.participants),
            'required_resources':list(case.resources),
            'existing':[{'id':x.id,'start':x.start,'duration':x.duration,'people':list(x.people),
                         'resources':list(x.resources),'flexible':x.flexible} for x in case.existing],
            'profiles':{p:{'rate_prefix':list(v.prefix),'published':list(v.published),
                           'exceptions':list(v.exceptions),'preferred_break':v.preferred_break,
                           'gap_weight':v.gap_weight,'nearby_limit':v.nearby_limit,
                           'exception_fee':v.exception_fee} for p,v in case.profiles.items()},
            'local_day_index':local_days,'unresolved_people':sorted(case.unresolved_people),
            'move_fixed_cost':case.move_fixed_cost,'move_participant_cost':case.move_participant_cost,
            'delay_per_day':case.delay_per_day,'limit':100}

def oracle(case):
    if set(case.participants)&set(case.unresolved_people):return None,0
    candidates=[]
    for t in case.candidate_starts:
        new=case.new(t)
        if independently_feasible(case,new):candidates.append(full_score(case,new))
        for old in case.existing:
            if not old.flexible or not conflicts(new,old):continue
            for r in case.replacement_starts:
                # Explicit contract guard: unchanged V15 misses this check when
                # a resource-only relocated meeting has no people. See REVIEW.md.
                if r+old.duration>len(next(iter(case.profiles.values())).prefix)-1:continue
                moved=Meeting(old.id,r,old.duration,old.people,old.resources,old.flexible)
                if independently_feasible(case,new,moved):candidates.append(full_score(case,new,moved))
    return sorted(candidates),len(candidates)

def invoke(binary,data):
    proc=subprocess.run([str(binary)],input=json.dumps(data),encoding='utf-8',capture_output=True,timeout=25)
    try:response=json.loads(proc.stdout)
    except:raise AssertionError(f'bad output: {proc.returncode=} {proc.stdout[:500]!r} {proc.stderr[:500]!r}')
    return proc.returncode,response

def tuple_score(x):
    return (x['total_cost'],x['fairness_max_burden'],x['start_minute'],x['moved_meeting_id'] or '',
            x['replacement_start_minute'] if x['replacement_start_minute'] is not None else -1)

def compare(binary,case,name,report):
    request=encode(case)
    code,result=invoke(binary,request)
    assert code==0 and result['status']!='INVALID_INPUT',(name,code,result)
    scores,count=oracle(case)
    if scores is None:
        assert result['status']=='UNRESOLVED_CALENDAR',(name,result)
        assert result['solutions_evaluated']==0
        report['unresolved']+=1
        return
    assert result['solutions_evaluated']==count,(name,'count',count,result.get('solutions_evaluated'))
    actual=[tuple_score(x) for x in result['recommendations']]
    assert actual==scores[:100],(name,'scores',scores[:10],actual[:10])
    assert result['returned_count']==len(actual)
    assert result['truncated']==(count>len(actual))
    if scores:
        assert result['status']=='OK'
    else:
        assert result['status']=='NO_FEASIBLE_PROPOSAL'
    for x in result['recommendations']:
        new=case.new(x['start_minute'])
        moved=None
        if x['moved_meeting_id']:
            old=next(e for e in case.existing if e.id==x['moved_meeting_id'])
            moved=Meeting(old.id,x['replacement_start_minute'],old.duration,old.people,old.resources,old.flexible)
        assert x['end_minute']==new.end
        assert x['required_permissions']=={
            'new_meeting_extra_availability':list(exception_requests(new,case)),
            'relocated_meeting_extra_availability':list(exception_requests(moved,case)) if moved else [],
            'relocation_participant_approval':list(moved.people) if moved else []},(name,x)
        if x['moved_meeting_id']:
            assert x['proposal_status']=='CONDITIONAL_PENDING_APPROVAL'
        elif x['required_permissions']['new_meeting_extra_availability']:
            assert x['proposal_status']=='CONDITIONAL_PENDING_APPROVAL'
        else: assert x['proposal_status']=='DIRECT_PENDING_NORMAL_MEETING_APPROVAL'
    report['cases']+=1;report['arrangements']+=count;report['moves']+=sum(bool(x[3]) for x in scores)

def run(binary,random_count):
    report={'cases':0,'arrangements':0,'moves':0,'unresolved':0,'invalid_inputs_rejected':0,'manual_witnesses':[]}
    H=2880
    pf=fixture_profiles(H)
    def case(name, events, starts, reps=(),people=('A','B'),res=(),duration=30,profiles=None,unresolved=()):
        c=MinuteCase(list(events),tuple(people),tuple(res),duration,tuple(starts),tuple(reps),
                     profiles or pf,unresolved_people=frozenset(unresolved))
        compare(binary,c,name,report)
    case('direct',[],[10,20,300,1200],duration=30)
    case('half_open_adjacency',[Meeting('X',100,30,('A',))],[130],duration=30)
    case('single_shared_block',[Meeting('X',100,30,('A','B'),(),True)],[100],(130,160),duration=30)
    case('two_distinct_block',[Meeting('X',100,30,('A',),(),True),Meeting('Y',100,30,('B',),(),True)],
         [100],(150,),duration=30)
    case('protected_block',[Meeting('P',100,30,('A',),(),False)],[100],(150,),duration=30)
    case('room_block',[Meeting('R1',100,30,('C',),('ROOM',),True)],[100],(150,),res=('ROOM',),duration=30)
    case('new_and_moved_interaction',[Meeting('M',200,60,('A','C'),(),True)],
         [200,250],(240,260,280,340),duration=30)
    case('midnight',[Meeting('M',1245,30,('A',),(),True)],[1245],(1400,),duration=30)
    case('minute_off_grid',[],[365,425,605],duration=30)
    extras=fixture_profiles(H,published=[(0,500)],exceptions=[(500,1000)])
    case('requested_extra',[],[550],profiles=extras,duration=30)
    case('no_extra_allowed',[],[1200],profiles=extras,duration=30)
    case('unresolved',[],[100],unresolved=('A',))
    case('move_extra',[Meeting('F',500,40,('A','C'),(),True)],[500],(600,1100),duration=30,profiles=extras)
    case('gap_preferences',[Meeting('M',130,30,('A',)),Meeting('N',240,30,('B',))],[160,180,190,205],duration=30)
    # Daylight saving transition: two distinct 02:30 local starts in Berlin.
    dst_anchor=datetime(2026,10,25,0,0,tzinfo=timezone.utc)
    dst=fixture_profiles(240,anchor=dst_anchor,zone='Europe/Berlin')
    case('dst_repeated_hour',[],[30,90],duration=30,profiles=dst)
    spring=fixture_profiles(240,anchor=datetime(2026,3,29,tzinfo=timezone.utc),zone='Europe/Berlin')
    case('dst_skipped_hour',[],[30,60,90],duration=30,profiles=spring)
    case('touching_publications_not_implicitly_merged',[],[25],duration=10,
         profiles=fixture_profiles(H,published=[(0,30),(30,H)]))
    case('unresolved_relocation_participant',[Meeting('X',100,30,('A','C'),(),True)],
         [100],(160,),unresolved=('C',))
    case('unicode_relocation_id',[Meeting('M-\u00d6"\n',100,30,('A',),(),True)],
         [100],(160,))
    rng=random.Random(20261028)
    profiles=fixture_profiles(H,published=[(0,1000),(1000,2000),(2100,H)],exceptions=[(2000,2100)])
    for n in range(random_count):
        events=[]
        for j in range(rng.randint(0,9)):
            people=tuple(sorted(rng.sample('ABCD',rng.randint(1,3))))
            resources=('ROOM',) if rng.random()<.3 else ()
            dur=rng.choice((15,30,45,60,75));start=rng.randint(0,H-dur)
            e=Meeting(f'E{j}',start,dur,people,resources,rng.random()<.6)
            if not any(conflicts(e,x) for x in events):events.append(e)
        new_people=tuple(sorted(rng.sample('ABCD',rng.randint(1,3))))
        starts=tuple(sorted({rng.randrange(0,H-90) for _ in range(9)}))
        reps=tuple(sorted({rng.randrange(0,H-90) for _ in range(11)}))
        dur=rng.choice((15,30,45,60))
        case(f'random_{n}',events,starts,reps,new_people,('ROOM',) if rng.random()<.4 else (),dur,profiles)
    # Mutation/adversarial inputs must fail explicitly rather than pretend availability.
    good=encode(MinuteCase([],('A','B'),(),30,(100,),(),pf))
    bad_cases=[]
    def mut(f):
        x=json.loads(json.dumps(good));f(x);bad_cases.append(x)
    mut(lambda x:x.update({'duration':0}))
    mut(lambda x:x.update({'candidate_starts':[H]}))
    mut(lambda x:x['profiles']['A'].update({'rate_prefix':x['profiles']['A']['rate_prefix'][:-1]}))
    mut(lambda x:x['profiles']['A'].update({'published':[[50,50]]}))
    mut(lambda x:x.update({'required_people':['A','A']}))
    mut(lambda x:x.update({'local_day_index':[0]}))
    mut(lambda x:x.update({'candidate_starts':[100,100]}))
    mut(lambda x:x.update({'existing':[{'id':'X','start':10,'duration':50,'people':['A'],'resources':[]},
                                          {'id':'Y','start':20,'duration':50,'people':['A'],'resources':[]}]}))
    mut(lambda x:x.update({'operation':'other'}))
    mut(lambda x:x.update({'unresolved_people':['A'],'duration':-1}))
    for i,x in enumerate(bad_cases):
        code,reply=invoke(binary,x)
        assert code!=0 and reply['status']=='INVALID_INPUT',(i,code,reply)
        report['invalid_inputs_rejected']+=1
    return report,good

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--binary',default=str(HERE.parent/'build'/'cdmcs_i1'))
    parser.add_argument('--random',type=int,default=300)
    parser.add_argument('--output',type=Path,help='Optional explicit result file; default is stdout only.')
    args=parser.parse_args()
    result,good=run(Path(args.binary),args.random)
    if args.output:
        args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))
