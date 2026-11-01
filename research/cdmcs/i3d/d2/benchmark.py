"""Bounded matched-path synthetic measurements, not optimizer-only timings."""

import argparse
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import platform
from statistics import median, pstdev
import subprocess
from time import monotonic, perf_counter_ns
from types import SimpleNamespace
from unittest import mock

from research.cdmcs.i3a.adapter import cdmcs_request, normalize
from research.cdmcs.i3a.fixtures import basic, period, stamp
from research.cdmcs.i3c.admission import admitted_snapshot, synthetic_fixture
from research.cdmcs.i3c.benchmark import _windows_usage
from research.cdmcs.i3c.runner import ShadowRunner
from research.cdmcs.i3d.d2.planning import prepare
from research.cdmcs.i3d.d2.runner import BatchedShadowRunner
from web.backend_executable import file_sha256, resolve_backend_executable


def fixture(count):
    value = basic()
    end = 15 * (count-1) + 30
    value['horizon'] = period(0,end)
    value['participants'][1]['published'] = [period(0,end)]
    value['candidates'] = {'mode':'explicit','anchor_participant':'professor-A',
                           'starts':[stamp(i*15) for i in range(count)]}
    for person in value['participants']:
        person['preference'] = {'base_rate':0,'preferred_break':0,'gap_weight':0,'nearby_limit':0,
                                'source':'synthetic-D2-matched-neutral'}
    source = {'source':'synthetic-D2-measurement','fixture_id':'fictional-2030-fixed-calendar'}
    preferences = [{'preference_version':1,'synthetic':True,'owner':p['id'],'revision':1,'state':'configured',
        'timezone':value['timezone'],'effective':{'from':'2029-01-01','until':'2031-12-31'},
        'preferred_weekdays':[],'preferred_windows':[],'desired_gap_minutes':0,'provenance':source}
        for p in value['participants']]
    policy = {'policy_version':1,'synthetic':True,'id':'synthetic-D2-zero-cost','revision':1,
        'rate_model':'weekday_window_tiers_v1','preferred_rate':0,'outside_window_rate':0,'outside_day_rate':0,
        'gap_weight':0,'nearby_limit':0,'exception_fee':0,'move_fixed_cost':0,'move_participant_cost':0,
        'delay_per_day':0,'provenance':source}
    context = {'context_version':1,'synthetic':True,'state':'complete','coverage':value['horizon'],
        'complete_for':[p['id'] for p in value['participants']],'left_boundary':'calendar_start',
        'right_boundary':'calendar_end','commitments':[],'provenance':source}
    scope = synthetic_fixture(value)
    compiled = prepare(scope,preferences,policy,context)
    if cdmcs_request(normalize(admitted_snapshot(scope))) != compiled.compiled.to_request():
        raise ValueError('Benchmark paths have different native problem definitions')
    return value, preferences, policy, context


def measure(runner, inputs, batched):
    original_spawn, original_dump = subprocess.Popen, json.dumps
    children, active, dumping = [], 0, {'calls':0,'ns':0,'characters':0}
    hashes = {'calls':0,'bytes':0,'ns':0}

    def spawn(*args,**kwargs):
        nonlocal active
        child = original_spawn(*args,**kwargs)
        children.append(child)
        active = max(active,sum(p.poll() is None for p in children))
        return child

    def dump(*args,**kwargs):
        begun = perf_counter_ns()
        text = original_dump(*args,**kwargs)
        dumping['ns'] += perf_counter_ns()-begun
        dumping['characters'] += len(text)
        dumping['calls'] += 1
        return text

    def hashing(path):
        begun = perf_counter_ns()
        digest = file_sha256(path)
        hashes['ns'] += perf_counter_ns()-begun
        hashes['calls'] += 1
        hashes['bytes'] += Path(path).stat().st_size
        return digest

    before = None
    if os.name != 'nt':
        import resource
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
    begun = perf_counter_ns()
    raw,preferences,policy,context = inputs
    scope = synthetic_fixture(raw)
    value = prepare(scope,preferences,policy,context)
    prepared_at = perf_counter_ns()
    with mock.patch('research.cdmcs.i3c.process.subprocess.Popen',new=spawn), \
         mock.patch('research.cdmcs.i3c.process.json.dumps',new=dump), \
         mock.patch('research.cdmcs.i3c.runner.file_sha256',new=hashing), \
         mock.patch('web.backend_executable.file_sha256',new=hashing):
        result = runner.run(value if batched else scope)
    ended = perf_counter_ns()
    count = len(raw['candidates']['starts'])
    expected = count + math.ceil(count/runner.batch_size) if batched else 2*count
    if (result.status != 'match' or not result.complete or result.cdmcs_feasible != count
            or result.production_feasible != count or len(children) != expected or active != 1
            or any(c.poll() is None for c in children)):
        raise ValueError('Matched synthetic benchmark failed')
    if batched and result.ranked_ordinals != tuple(range(count)):
        raise ValueError('Benchmark ordering differs')
    child_cpu, peak_child, parent_peak = None,None,None
    if os.name == 'nt':
        usage = [_windows_usage(c) for c in children]
        if all(u[0] is not None for u in usage): child_cpu = sum(u[0] for u in usage)
        if all(u[1] is not None for u in usage): peak_child = max(u[1] for u in usage)
        import ctypes
        k = ctypes.WinDLL('kernel32')
        k.GetCurrentProcess.restype = ctypes.c_void_p
        parent_peak = _windows_usage(SimpleNamespace(_handle=k.GetCurrentProcess()))[1]
    else:
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        child_cpu = round((after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime)*10**9)
        peak_child = after.ru_maxrss*1024
        parent_peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
    return {'end_to_end_ns':ended-begun,'preparation_ns':prepared_at-begun,'runner_ns':ended-prepared_at,
        'processes':len(children),'max_active_children':active,'peak_child_rss_bytes':peak_child,
        'parent_lifetime_peak_rss_bytes':parent_peak,'child_cpu_ns':child_cpu,
        'json_dumps':dumping,'hashing':hashes,
        'result':result.summary() if batched else asdict(result)}


def statistics(trials):
    values = sorted(t['end_to_end_ns'] for t in trials)
    return {'median_ns':median(values),'sample_p95_ns':values[math.ceil(.95*len(values))-1],
            'min_ns':values[0],'max_ns':values[-1],'stdev_ns':pstdev(values),
            'coefficient_of_variation':pstdev(values)/(sum(values)/len(values))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cdmcs',required=True)
    parser.add_argument('--cdmcs-sha256',required=True)
    parser.add_argument('--production',required=True)
    parser.add_argument('--candidates',type=int,nargs='+',default=[1,8,32,128,256])
    parser.add_argument('--batch-size',type=int,default=100)
    parser.add_argument('--repetitions',type=int,default=5)
    parser.add_argument('--warmups',type=int,default=1)
    args = parser.parse_args()
    if (not 1 <= args.batch_size <= 100 or not 1 <= args.repetitions <= 7 or not 0 <= args.warmups <= 2
            or not 1 <= len(args.candidates) <= 8 or any(not 1 <= n <= 256 for n in args.candidates)
            or len(set(args.candidates)) != len(args.candidates)
            or sum(3*n+math.ceil(n/args.batch_size) for n in args.candidates)*(args.repetitions+args.warmups)>10000):
        parser.error('Synthetic experiment exceeds its explicit resource budget')
    try:
        deadline = monotonic()+900
        singleton = ShadowRunner(args.cdmcs,args.cdmcs_sha256,production_path=args.production,enabled=True)
        batch = BatchedShadowRunner(args.cdmcs,args.cdmcs_sha256,production_path=args.production,
                                    enabled=True,batch_size=args.batch_size)
        rows = []
        for index,count in enumerate(args.candidates):
            inputs = fixture(count)
            trials = {'singleton':[],'batched':[]}
            for iteration in range(-args.warmups,args.repetitions):
                order = ('singleton','batched') if (iteration+index)%2 else ('batched','singleton')
                for mode in order:
                    if monotonic()>deadline: raise ValueError('Experiment deadline')
                    result = measure(singleton if mode=='singleton' else batch,inputs,mode=='batched')
                    if iteration >= 0: trials[mode].append(result)
            summaries = {key:statistics(value) for key,value in trials.items()}
            rows.append({'candidates':count,'trials':trials,'statistics':summaries,
                         'median_path_speedup':summaries['singleton']['median_ns']/summaries['batched']['median_ns']})
        binary = Path(args.cdmcs)
        provenance = {'platform':platform.platform(),'python':platform.python_version(),
            'head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
            'working_tree':subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],text=True),
            'cdmcs_sha256':file_sha256(binary),'production':resolve_backend_executable('.',args.production).metadata,
            'cmake_flags':(binary.parent/'CMakeFiles/cdmcs_i1.dir/flags.make').read_text(),
            'sources':{str(p):file_sha256(p) for base in ('research/cdmcs/i3c','research/cdmcs/i3d/d1','research/cdmcs/i3d/d2')
                       for p in Path(base).glob('*.py')},
            'batch_size':args.batch_size,'repetitions':args.repetitions,'warmups':args.warmups}
        print(json.dumps({'provenance':provenance,'rows':rows,
            'methodology':'Matched explicit neutral synthetic costs, two required people, empty fixed calendars, identical grids and problem JSON. D1 preparation is included equally in both end-to-end paths. Alternating order, sequential execution, one child maximum. JSON dumps time excludes UTF-8 encoding; Popen launch time is partial startup; child CPU includes parsing/scoring/serialization, not pure optimizer computation. Child RSS is a per-trial terminated-child maximum on Windows, cumulative experiment maximum on Linux. Parent peak is process-lifetime, not per-trial. Nearest-rank sample p95 with five trials equals maximum: not a stable population-tail estimate. Hooks add overhead; no algorithmic speedup or production workload claim.'},indent=2))
        return 0
    except (ValueError,OSError,KeyError):
        parser.exit(2,'Synthetic benchmark failed; no calendar diagnostics retained.\n')


if __name__ == '__main__':
    raise SystemExit(main())
