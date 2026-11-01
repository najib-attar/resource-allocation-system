from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict, replace
import io
import json
import logging
from pathlib import Path
import subprocess
import sys
import threading
from time import monotonic
from types import SimpleNamespace
import unittest
from unittest import mock

from research.cdmcs.i3c import runner as kernel
from research.cdmcs.i3c.process import ProcessFailure, ProcessResult
from research.cdmcs.i3c.runner import Budget, ShadowRunner
from research.cdmcs.i3c.tests.test_shadow import production_response, response
from research.cdmcs.i3d.d2.runner import BatchedShadowRunner
from research.cdmcs.i3d.d2.tests.fixtures import fixture, prepared, policy
from web.backend_executable import file_sha256


def all_rows(request):
    result = response(request)
    row = result['recommendations'][0]
    result['recommendations'] = [dict(row, start_minute=t, end_minute=t+request['duration'])
                                 for t in request['candidate_starts']]
    result['returned_count'] = result['solutions_evaluated'] = len(result['recommendations'])
    return result


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.digest = file_sha256(sys.executable)
        backend = SimpleNamespace(path=Path(sys.executable), metadata={'binary_sha256': self.digest})
        patch = mock.patch.object(kernel, 'resolve_backend_executable', return_value=backend)
        self.resolver = patch.start()
        self.addCleanup(patch.stop)

    def runner(self, **kwargs):
        return BatchedShadowRunner(sys.executable, self.digest, enabled=True, **kwargs)

    def success(self, command, request, **kwargs):
        return ProcessResult(production_response(request) if request['operation'] == 'appointment'
                             else all_rows(request), 1, 2)

    def test_disabled_by_default_never_resolves_or_spawns(self):
        with mock.patch.object(kernel, 'execute') as calls:
            self.assertEqual(BatchedShadowRunner().run('not-a-scope').status, 'disabled')
        calls.assert_not_called(); self.resolver.assert_not_called()

    def test_exact_process_counts_and_target_accounting(self):
        value = prepared(fixture(128))
        for size in (1, 2, 8, 32, 99, 100):
            with self.subTest(size=size), mock.patch.object(kernel, 'execute', side_effect=self.success) as calls:
                result = self.runner(batch_size=size).run(value)
                expected = (128+size-1)//size
                self.assertEqual(result.status, 'match')
                self.assertEqual((result.cdmcs_processes,result.production_processes), (expected,128))
                self.assertEqual(calls.call_count, 128+expected)
                self.assertEqual(tuple(r[0] for r in result.observations), tuple(range(128)))
                self.assertEqual(result.ranked_ordinals, tuple(range(128)))
                self.assertNotIn('observations', result.summary())

    def test_delay_reference_repeated_evaluation_is_not_an_extra_booking_or_target(self):
        with mock.patch.object(kernel, 'execute', side_effect=self.success) as calls:
            result = self.runner().run(prepared(fixture(128), weights=policy(delay_per_day=5)))
        self.assertEqual((result.status,result.evaluated,result.reference_evaluations), ('match',128,1))
        self.assertEqual((result.cdmcs_processes,result.production_processes), (2,128))
        self.assertEqual(calls.call_count, 130)

    def test_inconsistent_reference_rows_fail_the_whole_run(self):
        seen = 0
        def inconsistent(command, request, **kwargs):
            nonlocal seen
            result = self.success(command, request, **kwargs)
            if request['operation'] != 'appointment':
                seen += 1
                if seen == 2:
                    result.payload['recommendations'][0]['total_cost'] = 1
                    result.payload['recommendations'].sort(key=lambda r:(r['total_cost'],r['fairness_max_burden'],r['start_minute']))
            return result
        with mock.patch.object(kernel, 'execute', side_effect=inconsistent):
            result = self.runner().run(prepared(fixture(128), weights=policy(delay_per_day=5)))
        self.assertEqual((result.status,result.code,result.complete,result.evaluated),
                         ('engine_failure','INCONSISTENT_REFERENCE',False,0))

    def test_truncation_or_bad_counts_are_not_infeasible_certificates(self):
        for change in ({'truncated':True}, {'returned_count':0}, {'status':'UNRESOLVED_CALENDAR'}):
            def invalid(command, request, **kwargs):
                result = self.success(command,request,**kwargs)
                result.payload.update(change)
                return result
            with self.subTest(change=change), mock.patch.object(kernel,'execute',side_effect=invalid):
                result=self.runner().run(prepared())
                self.assertEqual((result.status,result.code,result.complete),('engine_failure','INVALID_PROTOCOL',False))

    def test_consistently_misreported_membership_is_a_discrepancy_never_false_equality(self):
        def omitted(command,request,**kwargs):
            result=self.success(command,request,**kwargs)
            if request['operation'] != 'appointment':
                result.payload['recommendations'].pop()
                result.payload['returned_count'] -= 1
                result.payload['solutions_evaluated'] -= 1
            return result
        with mock.patch.object(kernel,'execute',side_effect=omitted):
            result=self.runner().run(prepared())
        self.assertEqual((result.status,result.discrepancies),('discrepancy',1))
        self.assertFalse(result.complete)
        self.assertFalse(hasattr(result,'observations'))

    def test_all_transport_failures_preserve_no_partial_success(self):
        for code in ('TIMEOUT','ENGINE_EXIT','MALFORMED_RESPONSE','OUTPUT_LIMIT','LIMIT_OR_PROCESS_FAILURE','THREAD_START'):
            count=0
            def fail(command,request,**kwargs):
                nonlocal count
                count += 1
                if count==3: raise ProcessFailure(code)
                return self.success(command,request,**kwargs)
            with self.subTest(code=code), mock.patch.object(kernel,'execute',side_effect=fail):
                result=self.runner(batch_size=2).run(prepared())
                self.assertEqual((result.status,result.code,result.complete,result.evaluated),('engine_failure',code,False,0))
                self.assertFalse(hasattr(result,'observations'))

    def test_each_child_still_rehashes_its_own_binary(self):
        with mock.patch.object(kernel,'execute',side_effect=self.success) as calls, \
             mock.patch.object(kernel,'file_sha256',wraps=file_sha256) as hashing:
            result=self.runner().run(prepared())
        self.assertEqual(result.status,'match')
        self.assertEqual(hashing.call_count,1+calls.call_count)

    def test_failure_after_a_complete_paired_batch_discards_every_observation(self):
        for code in ('TIMEOUT', 'RUN_DEADLINE', 'ENGINE_EXIT', 'INPUT_LIMIT', 'OUTPUT_LIMIT',
                     'MALFORMED_RESPONSE', 'LIMIT_SETUP', 'THREAD_START'):
            completed = []
            def fail_later(command, request, **kwargs):
                if len(completed) == 3:
                    self.assertEqual(request['operation'], 'cdmcs_schedule_v1')
                    raise ProcessFailure(code)
                completed.append(request['operation'])
                return self.success(command, request, **kwargs)
            with self.subTest(code=code), mock.patch.object(kernel, 'execute', side_effect=fail_later) as calls:
                result = self.runner(batch_size=2).run(prepared(fixture(4)))
            self.assertEqual(completed, ['cdmcs_schedule_v1', 'appointment', 'appointment'])
            self.assertEqual(calls.call_count, 4)
            self.assertEqual((result.status, result.code, result.complete, result.evaluated),
                             ('engine_failure', code, False, 0))
            self.assertFalse(hasattr(result, 'observations'))

    def test_bad_later_batch_never_leaves_a_complete_first_batch_result(self):
        for malformed in ('truncated', 'duplicate', 'foreign', 'missing-count', 'pending-permission'):
            batches_seen = 0
            def bad_later(command, request, **kwargs):
                nonlocal batches_seen
                call = self.success(command, request, **kwargs)
                if request['operation'] == 'cdmcs_schedule_v1':
                    batches_seen += 1
                    if batches_seen == 2:
                        payload = call.payload
                        if malformed == 'truncated': payload['truncated'] = True
                        if malformed == 'duplicate': payload['recommendations'][1] = payload['recommendations'][0]
                        if malformed == 'foreign': payload['recommendations'][0]['start_minute'] = 999999
                        if malformed == 'missing-count': del payload['solutions_evaluated']
                        if malformed == 'pending-permission':
                            payload['recommendations'][0]['required_permissions']['new_meeting_extra_availability'] = ['private']
                return call
            with self.subTest(malformed=malformed), mock.patch.object(kernel, 'execute', side_effect=bad_later) as calls:
                result = self.runner(batch_size=2).run(prepared(fixture(4)))
            self.assertEqual(calls.call_count, 4)
            self.assertEqual((result.status, result.code, result.complete, result.evaluated),
                             ('engine_failure', 'INVALID_PROTOCOL', False, 0))
            self.assertFalse(hasattr(result, 'observations'))

    def test_late_dependency_messages_cannot_enter_logs_or_results(self):
        marker = 'SYNTHETIC-PRIVATE-CALENDAR-MARKER'
        for error in (ValueError(marker), OSError(marker), MemoryError(marker)):
            count = 0
            def fail_later(command, request, **kwargs):
                nonlocal count
                count += 1
                if count == 4: raise error
                return self.success(command, request, **kwargs)
            stdout, stderr = io.StringIO(), io.StringIO()
            with self.subTest(error=type(error).__name__), redirect_stdout(stdout), redirect_stderr(stderr), \
                 mock.patch.object(logging.Logger, '_log') as logs, \
                 mock.patch.object(kernel, 'execute', side_effect=fail_later):
                result = self.runner(batch_size=2).run(prepared(fixture(4)))
            self.assertEqual(count, 4)
            self.assertEqual((result.status, result.complete), ('input_error', False))
            self.assertNotIn(marker, repr(result) + json.dumps(asdict(result)) + stdout.getvalue() + stderr.getvalue())
            logs.assert_not_called()
            self.assertFalse(hasattr(result, 'observations'))

    def test_changed_executable_fails_before_the_next_child(self):
        with mock.patch.object(kernel,'execute',side_effect=self.success) as calls, \
             mock.patch.object(kernel,'file_sha256',side_effect=(self.digest,self.digest,'0'*64)):
            result=self.runner().run(prepared())
        self.assertEqual((result.code,calls.call_count,result.complete),('EXECUTABLE_CHANGED',1,False))

    def test_cdmcs_only_does_not_resolve_production(self):
        with mock.patch.object(kernel,'execute',side_effect=self.success) as calls:
            result=self.runner().run(prepared(),compare=False)
        self.assertEqual((result.status,result.production_processes,calls.call_count),('cdmcs_only',0,1))
        self.resolver.assert_not_called()

    def test_deadline_includes_result_assembly(self):
        now=monotonic()
        with mock.patch.object(kernel,'execute',side_effect=self.success), \
             mock.patch('research.cdmcs.i3d.d2.runner.monotonic',side_effect=(now,now,now+121)):
            result=self.runner().run(prepared())
        self.assertEqual((result.code,result.complete),('RUN_DEADLINE',False))

    def test_shared_admission_slot_prevents_parallel_singleton_and_batch_execution(self):
        entered,finish=threading.Event(),threading.Event()
        results=[]
        def wait(command,request,**kwargs):
            entered.set(); finish.wait(3)
            return self.success(command,request,**kwargs)
        with mock.patch.object(kernel,'execute',side_effect=wait):
            thread=threading.Thread(target=lambda:results.append(self.runner().run(prepared(),compare=False)))
            thread.start()
            try:
                self.assertTrue(entered.wait(3))
                self.assertEqual(ShadowRunner(enabled=True).run('unused').status,'busy')
                self.assertEqual(self.runner().run('unused').status,'busy')
            finally:
                finish.set(); thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results[0].status,'cdmcs_only')

    def test_unsupported_delay_size_one_launches_nothing(self):
        with mock.patch.object(kernel,'execute') as calls:
            result=self.runner(batch_size=1).run(prepared(fixture(128),weights=policy(delay_per_day=5)))
        self.assertEqual((result.status,result.code),('unsupported','BATCH_DELAY_CAPACITY'))
        calls.assert_not_called()

    def test_tampered_inputs_and_invalid_configuration_do_not_launch(self):
        value=prepared()
        with mock.patch.object(kernel,'execute') as calls:
            for invalid in (value.scope,replace(value,seal=None),None):
                self.assertEqual(self.runner().run(invalid).status,'input_error')
            self.assertEqual(self.runner().run(value,compare='yes').status,'input_error')
        calls.assert_not_called()
        for size in (0,101,True,1.0):
            with self.assertRaises(ValueError): self.runner(batch_size=size)


class ActualProcessTests(unittest.TestCase):
    def test_actual_second_batch_faults_are_reaped_without_exposing_earlier_scores(self):
        # This is a transport double, not a native cost/feasibility oracle.
        good = """import json,sys
q=json.load(sys.stdin)
rows=[{'start_minute':t,'end_minute':t+q['duration'],'total_cost':0,'fairness_max_burden':0,
       'moved_meeting_id':None,'replacement_start_minute':None,
       'required_permissions':{'new_meeting_extra_availability':[],
           'relocated_meeting_extra_availability':[],'relocation_participant_approval':[]},
       'proposal_status':'DIRECT_PENDING_NORMAL_MEETING_APPROVAL'} for t in q['candidate_starts']]
print(json.dumps({'operation':'cdmcs_schedule_v1','model':'V15_restricted_one_blocking_move',
    'status':'OK','returned_count':len(rows),'solutions_evaluated':len(rows),
    'truncated':False,'recommendations':rows}))
"""
        original = subprocess.Popen
        for expected, fault in (
                ('ENGINE_EXIT', "import sys;sys.stdin.read();sys.stderr.write('PRIVATE-MARKER');sys.exit(7)"),
                ('MALFORMED_RESPONSE', "import sys;sys.stdin.read();print('{')"),
                ('ENGINE_EXIT', "import sys;sys.stdin.read();sys.stdout.write('{');sys.exit(7)"),
                ('OUTPUT_LIMIT', "import sys;sys.stdin.read();sys.stdout.write('x'*100000)"),
                ('TIMEOUT', "import sys,time;sys.stdin.read();time.sleep(10)"),
                ('ENGINE_EXIT', "import sys;sys.stdin.read();a=bytearray(512*1024**2)")):
            children = []
            def spawn(command, **kwargs):
                child = original([sys._base_executable, '-B', '-c', good if not children else fault], **kwargs)
                children.append(child)
                return child
            budget = Budget(per_process_seconds=0.3 if expected == 'TIMEOUT' else 3,
                            memory_bytes=64*1024**2, output_bytes=1024)
            runner = BatchedShadowRunner(sys.executable, file_sha256(sys.executable),
                                         enabled=True, batch_size=2, budget=budget)
            with self.subTest(expected=expected, fault=fault), \
                 mock.patch('research.cdmcs.i3c.process.subprocess.Popen', side_effect=spawn):
                result = runner.run(prepared(fixture(4)), compare=False)
            self.assertEqual(len(children), 2)
            self.assertEqual(children[0].returncode, 0)
            self.assertEqual((result.status, result.code, result.complete, result.evaluated),
                             ('engine_failure', expected, False, 0))
            self.assertNotIn('PRIVATE', repr(result))
            self.assertFalse(hasattr(result, 'observations'))
            for child in children:
                self.assertIsNotNone(child.poll())
                self.assertTrue(all(stream.closed for stream in (child.stdin, child.stdout, child.stderr)))

    def test_faulting_children_are_bounded_reaped_and_sanitized(self):
        digest=file_sha256(sys.executable)
        original=subprocess.Popen
        cases=[('ENGINE_EXIT',"import sys;sys.stdin.read();sys.stderr.write('PRIVATE-MARKER');sys.exit(7)"),
               ('MALFORMED_RESPONSE',"import sys;sys.stdin.read();print('PRIVATE-MARKER')"),
               ('OUTPUT_LIMIT',"import sys;sys.stdin.read();sys.stdout.write('x'*100000)"),
               ('TIMEOUT',"import sys,time;sys.stdin.read();time.sleep(10)"),
               ('ENGINE_EXIT',"import sys;sys.stdin.read();a=bytearray(512*1024**2)")]
        for expected,script in cases:
            children=[]
            def spawn(command,**kwargs):
                child=original([sys._base_executable,'-B','-c',script],**kwargs)
                children.append(child)
                return child
            budget=Budget(per_process_seconds=0.3 if expected=='TIMEOUT' else 3,
                          memory_bytes=64*1024**2,output_bytes=1024)
            runner=BatchedShadowRunner(sys.executable,digest,enabled=True,budget=budget)
            with self.subTest(expected=expected), mock.patch('research.cdmcs.i3c.process.subprocess.Popen',side_effect=spawn):
                result=runner.run(prepared(),compare=False)
                self.assertEqual((result.status,result.code,result.complete),('engine_failure',expected,False))
                self.assertNotIn('PRIVATE',repr(result))
            self.assertEqual(len(children),1)
            self.assertIsNotNone(children[0].poll())
            self.assertTrue(all(p.closed for p in (children[0].stdin,children[0].stdout,children[0].stderr)))
