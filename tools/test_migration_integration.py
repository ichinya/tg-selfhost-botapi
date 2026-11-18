"""Real HTTP mocks everywhere; public wrapper subprocess acceptance on Linux."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from tempfile import TemporaryDirectory
import unittest
from unittest import mock
from migration_engine import Engine,Runtime,Stop
from migration_http import Client
from migration_mock import Bot,TOKEN,deployment,Receiver
from migration_probe import Readiness
from migration_reconcile import apply_external,apply_delivery
from migration_store import Journal,StateError
from test_migration_state_privacy import MemoryStore


class LoopbackTests(unittest.TestCase):
    def setUp(self):
        self.trace=[]
        self.source=Bot('source',self.trace)
        self.target=Bot('target',self.trace)
        self.addCleanup(self.target.close)
        self.addCleanup(self.source.close)
        self.j=Journal(MemoryStore())
        self.j.bot='123'
        self.client=Client(fixture=True,connect_timeout=.3,read_timeout=.15,total_timeout=.4)
        self.r=Runtime(self.source.endpoint,self.target.endpoint,TOKEN,{'mode':'polling'},'polling',fixture=True)
        self.e=Engine(self.j,self.client,Readiness(self.client,lambda:deployment(self.target.endpoint),self.j.key),self.r)
        self.s=self.e.prepare('op',quiescence='stopped')
        self.trace.clear()

    def run_plan(self):
        return self.e.run(self.s,confirm_digest=self.s['digest'],quiescence='stopped',
                          endpoint_change='changed',application_start='started',resume=True)

    def evidence(self,outcome):
        return dict(version=1,operation_id='op',step_id='source_logout',attempt_id=self.s['steps']['source_logout'][-1]['id'],
                    endpoint_fingerprint=self.s['plan']['source_fingerprint'],token_fingerprint=self.s['plan']['token_fingerprint'],
                    observed_at=time.time(),outcome=outcome,provenance={'kind':'fixture','reference':'ledger','verified_by':'mock'})

    def test_success_order_and_polling_removes_existing_target_webhook(self):
        self.run_plan()
        actions=[(side,method) for side,method,p in self.trace]
        self.assertLess(actions.index(('source','logOut')),actions.index(('target','getMe')))
        self.assertEqual(self.target.url,'')
        self.assertEqual(self.source.effects['drop'],0)
        self.assertEqual(self.target.effects['deleteWebhook'],1)
        self.assertEqual(self.s['results']['delivery_verification'],'NOTRUN')
        self.trace.clear()
        self.run_plan()
        self.assertTrue(all(side=='target' for side,m,p in self.trace))
        self.assertEqual(self.target.effects['deleteWebhook'],1)

    def test_both_lost_logout_modes_unknown_then_bound_reconcile(self):
        # Separate fresh state for each mode is provided by subTest setup manually.
        for fault,outcome,expected in [('lost_unapplied','not_performed',1),('lost_applied','performed',1)]:
            if fault=='lost_applied':
                self.setUp()
            self.source.faults['logOut']=fault
            with self.assertRaises(Stop):
                self.run_plan()
            self.assertEqual(self.j.outcome(self.s,'source_logout'),'unknown')
            self.trace.clear()
            with self.assertRaises(Stop):
                self.run_plan()
            self.assertEqual(self.trace,[])
            apply_external(self.j,self.s,self.evidence(outcome))
            self.source.faults.clear()
            self.run_plan()
            self.assertEqual(self.source.effects['logOut'],expected)
            self.assertEqual(self.source.calls['logOut'],2 if fault=='lost_unapplied' else 1)

    def test_wrong_service_no_source_mutation(self):
        self.target.faults['probe']='html'
        with self.assertRaises(Stop):
            self.run_plan()
        self.assertFalse(any(side=='source' for side,m,p in self.trace))

    def test_rate_limit_waits_and_no_dependent_effect(self):
        self.source.faults['deleteWebhook']='429'
        with self.assertRaises(Stop) as caught:
            self.run_plan()
        self.assertEqual(caught.exception.code,3)
        self.trace.clear()
        with self.assertRaises(Stop):
            self.run_plan()
        self.assertFalse(any(m in ('deleteWebhook','logOut','getMe') for side,m,p in self.trace))
        self.assertEqual(self.source.effects['logOut'],0)

    def test_unknown_drop_retains_later_updates(self):
        from dataclasses import replace
        self.r=replace(self.r,drop=True)
        self.e.r=self.r
        self.s=self.e.prepare('dropop',quiescence='stopped')
        self.target.faults['deleteWebhook']='lost_applied'
        with self.assertRaises(Stop):
            self.run_plan()
        self.target.queue.append(99)
        self.trace.clear()
        with self.assertRaises(Stop):
            self.run_plan()
        self.assertEqual(self.target.effects['drop'],1)
        self.assertEqual(self.target.queue,[99])
        self.assertFalse(any(m=='deleteWebhook' for side,m,p in self.trace))

    def test_timeout_malformed_and_rejection_stop_dependents(self):
        for fault,expected in [('timeout','unknown'),('malformed','unknown'),('reject','failed')]:
            if fault!='timeout':
                self.setUp()
            self.source.faults['deleteWebhook']=fault
            with self.assertRaises(Stop):
                self.run_plan()
            self.assertEqual(self.j.outcome(self.s,'source_delete'),expected)
            self.assertEqual(self.source.effects['logOut'],0)
            self.assertEqual(self.target.effects['getMe'],0)

    def test_receiver_observes_mock_update_after_controlled_start(self):
        import hashlib
        import http.client
        self.run_plan()
        receiver=Receiver()
        self.addCleanup(receiver.close)
        update={'update_id':9001,'message':{'text':'synthetic migration test'}}
        body=json.dumps(update,sort_keys=True).encode()
        conn=http.client.HTTPConnection('127.0.0.1',receiver.port,timeout=2)
        try:
            conn.request('POST','/fixture',body,{'Content-Type':'application/json'})
            response=conn.getresponse()
            self.assertEqual(response.status,204)
            response.read()
        finally:
            conn.close()
        self.assertEqual(receiver.updates,[update])
        record=dict(operation_id='op',target_fingerprint=self.s['plan']['target_fingerprint'],received_at=time.time(),
                    update_id=9001,payload_digest=hashlib.sha256(body).hexdigest(),consumer_id='loopback_receiver',mode='mock',provenance='fixture_receipt')
        apply_delivery(self.j,self.s,record)
        self.assertEqual(self.s['results']['delivery_verification'],'mock')

    def test_unready_deployment_evidence_stops_before_source_calls(self):
        def unready():
            record=deployment(self.target.endpoint)
            record['write_verified']=False
            return record
        self.e.readiness.evidence_provider=unready
        with self.assertRaises(Stop):
            self.run_plan()
        self.assertFalse(any(side=='source' or method not in ('probe',) for side,method,p in self.trace))

    def test_remote_success_without_durable_receipt_recovers_unknown(self):
        write=self.j.store.write
        def fail_receipt(name,envelope):
            attempts=envelope['state']['steps']['source_logout']
            if attempts and attempts[-1]['events'][-1]['outcome']=='confirmed':
                raise StateError('injected failure after response before durable receipt')
            return write(name,envelope)
        with mock.patch.object(self.j.store,'write',side_effect=fail_receipt):
            with self.assertRaises(StateError):
                self.run_plan()
        self.assertEqual(self.source.effects['logOut'],1)
        self.s=self.j.load('op')
        self.assertEqual(self.j.outcome(self.s,'source_logout'),'in_flight')
        self.trace.clear()
        with self.assertRaises(Stop):
            self.run_plan()
        self.assertEqual(self.j.outcome(self.s,'source_logout'),'unknown')
        self.assertEqual(self.trace,[])
        self.assertEqual(self.source.calls['logOut'],1)


@unittest.skipUnless(os.name=='posix','public Bash/POSIX acceptance is mandatory in Linux CI')
class WrapperTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(prefix='migration-acceptance-')
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.trace=[]
        self.source=Bot('source',self.trace)
        self.target=Bot('target',self.trace)
        self.addCleanup(self.target.close)
        self.addCleanup(self.source.close)
        self.wrapper=Path(__file__).resolve().parents[1]/'tools'/'migration_executor.sh'
        self.evidence=self.root/'evidence.json'
        self.write(self.evidence,deployment(self.target.endpoint))
        self.env={'PATH':os.environ['PATH'],'HOME':str(self.root),'MIGRATION_PYTHON':sys.executable,
                  'BOT_TOKEN':TOKEN,'OLD_BOT_URL':self.source.endpoint,'SELF_BOT_URL':self.target.endpoint,
                  'MIGRATION_STATE_DIR':str(self.root/'state'),'MIGRATION_EVIDENCE_FILE':str(self.evidence)}
        (self.root/'.env').write_text('BOT_TOKEN=$(touch never-execute-dotenv)\n')

    @staticmethod
    def write(path,data):
        path.write_text(json.dumps(data),encoding='utf-8')
        path.chmod(0o600)

    def call(self,command,*args,expected=None):
        argv=['bash',str(self.wrapper),command,'--operation','op']
        if command not in ('status','reconcile'):
            argv+=['--fixture-loopback']
        child=subprocess.run([*argv,*args],env=self.env,cwd=self.root,stdin=subprocess.DEVNULL,
                             capture_output=True,text=True,timeout=15)
        if expected is not None:
            self.assertEqual(child.returncode,expected,child.stdout+child.stderr)
        self.assertNotIn(TOKEN,child.stdout+child.stderr)
        self.assertFalse((self.root/'never-execute-dotenv').exists())
        return child,json.loads(child.stdout)

    def plan(self):
        _,plan=self.call('plan','--action','polling','--quiescence-receipt','stopped',expected=0)
        return plan

    def test_public_wrapper_success_and_local_status(self):
        plan=self.plan()
        self.call('apply','--confirm-digest',plan['digest'],'--quiescence-receipt','stopped',expected=2)
        self.call('resume','--endpoint-change-receipt','changed','--application-start-receipt','started',expected=0)
        self.trace.clear()
        _,status=self.call('status',expected=0)
        self.assertEqual(self.trace,[])
        self.assertEqual(status['results']['delivery_verification'],'NOTRUN')
        self.assertEqual(self.source.effects['logOut'],1)

    def test_public_unknown_logout_reconcile_no_second_logout(self):
        plan=self.plan()
        self.source.faults['logOut']='lost_applied'
        self.call('apply','--confirm-digest',plan['digest'],'--quiescence-receipt','stopped',expected=2)
        self.trace.clear()
        self.call('resume','--quiescence-receipt','stopped',expected=2)
        self.assertEqual(self.trace,[])
        _,status=self.call('status',expected=0)
        record=dict(version=1,operation_id='op',step_id='source_logout',attempt_id=status['attempts']['source_logout'],
                    endpoint_fingerprint=status['plan']['source_fingerprint'],token_fingerprint=status['plan']['token_fingerprint'],
                    observed_at=time.time(),outcome='performed',provenance={'kind':'fixture','reference':'ledger','verified_by':'fixture'})
        file=self.root/'audit.json'
        self.write(file,record)
        self.call('reconcile','--evidence-file',str(file),expected=0)
        self.call('resume','--quiescence-receipt','stopped','--endpoint-change-receipt','changed',
                  '--application-start-receipt','started',expected=0)
        self.assertEqual(self.source.effects['logOut'],1)
        self.assertEqual(self.source.calls['logOut'],1)

    def test_public_not_performed_logout_needs_evidence_before_retry(self):
        plan=self.plan()
        self.source.faults['logOut']='lost_unapplied'
        self.call('apply','--confirm-digest',plan['digest'],'--quiescence-receipt','stopped',expected=2)
        self.trace.clear()
        self.call('resume','--quiescence-receipt','stopped',expected=2)
        self.assertEqual(self.trace,[])
        _,status=self.call('status',expected=0)
        record=dict(version=1,operation_id='op',step_id='source_logout',attempt_id=status['attempts']['source_logout'],
                    endpoint_fingerprint=status['plan']['source_fingerprint'],token_fingerprint=status['plan']['token_fingerprint'],
                    observed_at=time.time(),outcome='not_performed',provenance={'kind':'fixture','reference':'ledger','verified_by':'fixture'})
        file=self.root/'audit.json'
        self.write(file,record)
        self.call('reconcile','--evidence-file',str(file),expected=0)
        self.source.faults.clear()
        self.call('resume','--quiescence-receipt','stopped','--endpoint-change-receipt','changed',
                  '--application-start-receipt','started',expected=0)
        self.assertEqual(self.source.effects['logOut'],1)
        self.assertEqual(self.source.calls['logOut'],2)

    def test_missing_quiescence_and_binding_change_no_effects(self):
        self.call('plan','--action','polling',expected=2)
        self.assertEqual(self.trace,[])
        self.plan()
        self.trace.clear()
        self.env['BOT_TOKEN']='123:changed_synthetic'
        self.call('apply','--quiescence-receipt','stopped',expected=4)
        self.assertEqual(self.trace,[])

    def test_wrapper_path_with_spaces_and_missing_runtime(self):
        import shutil
        copy=self.root/'helper path with spaces'
        (copy/'tools').mkdir(parents=True)
        shutil.copyfile(self.wrapper,copy/'tools'/self.wrapper.name)
        for name in ('contract','store','engine','http','probe','reconcile','cli','export'):
            shutil.copyfile(self.wrapper.parent/f'migration_{name}.py',copy/'tools'/f'migration_{name}.py')
        self.wrapper=copy/'tools'/self.wrapper.name
        self.plan()
        self.env['MIGRATION_PYTHON']='/does-not-exist/python'
        child=subprocess.run(['bash',str(self.wrapper),'status','--operation','op'],env=self.env,
                             capture_output=True,text=True,timeout=5)
        self.assertEqual(child.returncode,4)
