import unittest
import time
from migration_engine import Engine,Runtime,Stop
from migration_http import Result
from migration_store import Journal,StateError
from test_migration_state_privacy import MemoryStore


class Ready:
    def __init__(self):
        self.ok=True
        self.binding='a'*64
    def check(self,endpoint):
        if not self.ok:
            raise ValueError('not ready')
        return self.binding


class Api:
    def __init__(self):
        self.trace=[]
        self.urls={'https://api.telegram.org':'https://old.example/hook', 'https://target.example':''}
        self.fault={}
    def request(self,endpoint,method=None,**kw):
        self.trace.append((endpoint,method,kw.get('params')))
        if (endpoint,method) in self.fault:
            return self.fault[(endpoint,method)]
        if method=='getMe':
            return Result('confirmed','api_ok',200,data={'id':123,'is_bot':True})
        if method=='getWebhookInfo':
            return Result('confirmed','api_ok',200,data={'url':self.urls[endpoint]})
        if method=='deleteWebhook':
            self.urls[endpoint]=''
        if method=='setWebhook':
            self.urls[endpoint]=kw['params']['url']
        return Result('confirmed','api_ok',200,data=True)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.j=Journal(MemoryStore())
        self.j.bot='123'
        self.api=Api()
        self.ready=Ready()
        self.runtime=Runtime('https://api.telegram.org','https://target.example','123:synthetic',{'mode':'polling'},'polling',fixture=True)
        self.e=Engine(self.j,self.api,self.ready,self.runtime)
        self.s=self.e.prepare('op',quiescence='workers stopped')
        self.api.trace=[]

    def run_plan(self,**kw):
        return self.e.run(self.s,confirm_digest=self.s['digest'],quiescence='stopped again',
                          endpoint_change='endpoint changed',application_start='controlled start',**kw)

    def test_order_target_only_after_logout(self):
        result=self.run_plan()
        trace=[(e,m) for e,m,p in self.api.trace]
        self.assertLess(trace.index((self.runtime.source,'logOut')),trace.index((self.runtime.target,'getMe')))
        self.assertEqual(result['results']['migration_outcome'],'confirmed')
        self.assertEqual(result['results']['delivery_verification'],'NOTRUN')
        self.assertIn((self.runtime.source,'deleteWebhook',{'drop_pending_updates':'false'}),self.api.trace)

    def test_down_target_and_missing_quiescence_no_source_effects(self):
        self.ready.ok=False
        with self.assertRaises(Stop):
            self.run_plan()
        self.assertEqual(self.api.trace,[])

    def test_confirmed_logout_resume_without_source(self):
        self.api.fault[(self.runtime.target,'getMe')]=Result('failed','not_sent')
        with self.assertRaises(Stop):
            self.run_plan()
        self.assertEqual(self.j.outcome(self.s,'source_logout'),'confirmed')
        self.api.trace=[]
        self.api.fault.clear()
        self.run_plan(resume=True)
        self.assertTrue(all(e==self.runtime.target for e,m,p in self.api.trace))

    def test_lost_logout_blocks_every_bot_call(self):
        self.api.fault[(self.runtime.source,'logOut')]=Result('unknown','transport_unknown')
        with self.assertRaises(Stop):
            self.run_plan()
        self.api.trace=[]
        with self.assertRaises(Stop):
            self.run_plan(resume=True)
        self.assertEqual(self.api.trace,[])

    def test_no_intent_no_mutation(self):
        self.j.store.fail=True
        with self.assertRaises(StateError):
            self.run_plan()
        self.assertEqual(self.api.trace,[])

    def test_changed_snapshot_blocks_mutation(self):
        self.api.urls[self.runtime.source]='https://changed.example'
        with self.assertRaises(Stop):
            self.run_plan()
        self.assertTrue(all(m not in ('logOut','deleteWebhook') for e,m,p in self.api.trace))

    def test_target_identity_mismatch_is_partial_and_no_configuration(self):
        self.api.fault[(self.runtime.target,'getMe')]=Result('confirmed','api_ok',200,data={'id':999,'is_bot':True})
        with self.assertRaises(Stop):
            self.run_plan()
        self.assertEqual(self.s['results']['migration_outcome'],'partial')
        self.assertFalse(any(e==self.runtime.target and m=='deleteWebhook' for e,m,p in self.api.trace))

    def test_final_resume_observes_drift_without_reconfiguring(self):
        self.run_plan()
        self.api.urls[self.runtime.target]='https://drift.example'
        self.api.trace=[]
        with self.assertRaises(Stop):
            self.run_plan(resume=True)
        self.assertEqual(self.s['results']['migration_outcome'],'partial')
        self.assertEqual(self.s['results']['webhook_configuration'],'failed')
        self.assertTrue(all(m=='getWebhookInfo' for e,m,p in self.api.trace))

    def test_deployment_change_blocks_source_mutations(self):
        self.ready.binding='b'*64
        with self.assertRaises(Stop):
            self.run_plan()
        self.assertEqual(self.api.trace,[])

    def test_superseded_plan_never_resumes(self):
        self.j.supersede(self.s,'replacement')
        with self.assertRaises(Stop):
            self.run_plan()
        self.assertEqual(self.api.trace,[])

    def test_local_transfer_blocks_before_target_and_binds_manifest(self):
        from dataclasses import replace
        self.e.r = replace(self.runtime, direction='local_to_local')
        self.j.store.rows.clear()
        self.s = self.e.prepare('transfer', quiescence='fixture')
        self.api.trace.clear()
        with self.assertRaises(Stop) as error:
            self.run_plan()
        self.assertEqual(error.exception.reason, 'state_transfer_checkpoint_required')
        self.assertEqual(self.j.outcome(self.s, 'source_close'), 'confirmed')
        self.assertFalse(any(e == self.runtime.target for e,m,p in self.api.trace))
        receipt = dict(operation_id='transfer',digest=self.s['digest'],close_attempt=self.s['steps']['source_close'][-1]['id'],
                       source_fingerprint=self.s['plan']['source_fingerprint'],target_fingerprint=self.s['plan']['target_fingerprint'],
                       source_deployment='a'*64,target_deployment=self.s['deployment'],source_manifest='b'*64,target_manifest='b'*64,
                       source_closed=True,no_writers=True,layout_valid=True,uid=1000,gid=1000,observed_at=time.time())
        self.run_plan(state_transfer=receipt,resume=True)
        self.assertEqual(self.j.outcome(self.s,'target_configure'),'confirmed')

    def test_webhook_only_preserve_has_no_mutation_or_detach(self):
        r=Runtime(self.runtime.source,self.runtime.source,self.runtime.token,
                  {'mode':'url_only','url':self.api.urls[self.runtime.source]},'preserve',fixture=True,direction='webhook_only')
        self.j.store.rows.clear()
        self.e.r=r
        self.s=self.e.prepare('webhook',quiescence='fixture',url_only_ack=True)
        self.api.trace.clear()
        self.run_plan()
        self.assertTrue(all(m in ('getMe','getWebhookInfo') for e,m,p in self.api.trace))
        self.assertEqual(self.s['results']['migration_outcome'],'confirmed')

    def test_local_to_cloud_cooldown_blocks_authorization(self):
        from dataclasses import replace
        self.e.r=replace(self.runtime,source=self.runtime.target,target=self.runtime.source,
                         direction='local_to_cloud',local_mode=False,queue_ack=True,cloud_not_before=time.time()+600)
        self.j.store.rows.clear()
        self.s=self.e.prepare('cloud',quiescence='fixture')
        self.api.trace.clear()
        with self.assertRaises(Stop) as error:
            self.run_plan()
        self.assertEqual(error.exception.code,3)
        self.assertFalse(any(e==self.e.r.target and m=='getMe' for e,m,p in self.api.trace))
