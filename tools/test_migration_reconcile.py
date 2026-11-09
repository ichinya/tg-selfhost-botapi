import time
import unittest
from migration_engine import Stop
from migration_http import Result
from migration_reconcile import apply_external,validate_external,apply_delivery
import test_migration_engine as fixtures


class ReconcileTests(fixtures.EngineTests):
    def test_trusted_provider_rejects_unsigned_tampered_and_wrong_binding(self):
        import hashlib
        import hmac
        from migration_contract import canonical
        from migration_reconcile import TrustedReceipts
        verifier=TrustedReceipts({'providers':{'audit':{'key_hex':'ab'*32,'kinds':['quiescence'],'fixture':True}}})
        payload=dict(version=1,kind='quiescence',operation_id='op',digest=self.s['digest'],
                     source_fingerprint=self.s['plan']['source_fingerprint'],target_fingerprint=self.s['plan']['target_fingerprint'],
                     token_fingerprint=self.s['plan']['token_fingerprint'],observed_at=time.time(),no_writers=True)
        signature=hmac.new(bytes.fromhex('ab'*32),canonical(payload).encode(),hashlib.sha256).hexdigest()
        envelope={'provider':'audit','payload':payload,'signature':signature}
        verifier(envelope,kind='quiescence',state=self.s)
        payload['digest']='f'*64
        with self.assertRaises(ValueError):
            verifier(envelope,kind='quiescence',state=self.s)
        with self.assertRaises(ValueError):
            verifier(payload,kind='quiescence',state=self.s)

    def test_refresh_unknown_detach_makes_no_bot_calls(self):
        self.api.fault[(self.runtime.source,'logOut')]=Result('unknown','transport_unknown')
        with self.assertRaises(Stop):
            self.run_plan()
        self.api.trace.clear()
        with self.assertRaises(Stop):
            self.e.refresh(self.s)
        self.assertEqual(self.api.trace,[])

    def evidence(self,step='source_logout',outcome='performed'):
        return dict(version=1,operation_id='op',step_id=step,attempt_id=self.s['steps'][step][-1]['id'],
                    endpoint_fingerprint=self.s['plan'][('source' if step.startswith('source') else 'target')+'_fingerprint'],
                    token_fingerprint=self.s['plan']['token_fingerprint'],observed_at=time.time(),outcome=outcome,
                    provenance={'kind':'server_audit','reference':'receipt1','verified_by':'fixture_server'})

    def test_evidence_after_lost_logout_never_repeats_logout(self):
        self.api.fault[(self.runtime.source,'logOut')]=Result('unknown','transport_unknown')
        with self.assertRaises(Stop):
            self.run_plan()
        evidence=self.evidence()
        evidence['attempt_id']='unrelated'
        with self.assertRaises(ValueError):
            apply_external(self.j,self.s,evidence)
        apply_external(self.j,self.s,self.evidence())
        self.api.trace=[]
        self.run_plan(resume=True)
        self.assertTrue(all(e==self.runtime.target for e,m,p in self.api.trace))
        events=self.s['steps']['source_logout'][0]['events']
        self.assertEqual([x['outcome'] for x in events],['in_flight','unknown','confirmed'])

    def test_not_performed_evidence_permits_explicit_retry(self):
        self.api.fault[(self.runtime.source,'logOut')]=Result('unknown','transport_unknown')
        with self.assertRaises(Stop):
            self.run_plan()
        apply_external(self.j,self.s,self.evidence(outcome='not_performed'))
        self.api.fault.clear()
        self.run_plan(resume=True)
        self.assertEqual(len(self.s['steps']['source_logout']),2)

    def test_source_delete_observation_without_second_delete(self):
        self.api.urls[self.runtime.source]=''
        self.j.intent(self.s,'source_delete')
        self.j.finish(self.s,'source_delete','unknown','interrupted')
        self.run_plan(resume=True)
        self.assertFalse(any(e==self.runtime.source and m=='deleteWebhook' for e,m,p in self.api.trace))

    def test_unknown_target_drop_not_repeated_or_inferred(self):
        from dataclasses import replace
        self.runtime=replace(self.runtime,drop=True)
        self.e.r=self.runtime
        self.s=self.e.prepare('dropop',quiescence='stopped')
        self.api.fault[(self.runtime.target,'deleteWebhook')]=Result('unknown','transport_unknown')
        with self.assertRaises(Stop):
            self.run_plan()
        self.api.trace=[]
        with self.assertRaises(Stop):
            self.run_plan(resume=True)
        self.assertEqual(self.api.trace,[])

    def test_target_authorization_observation_has_durable_intent(self):
        self.api.fault[(self.runtime.target,'getMe')]=Result('unknown','transport_unknown')
        with self.assertRaises(Stop):
            self.run_plan()
        self.api.fault.clear()
        self.api.trace=[]
        self.run_plan(resume=True)
        events=self.s['steps']['target_authorize'][0]['events']
        self.assertEqual([x['outcome'] for x in events],['in_flight','unknown','in_flight','confirmed'])
        self.assertTrue(all(e==self.runtime.target for e,m,p in self.api.trace))

    def test_delivery_requires_post_start_operation_bound_receipt(self):
        self.run_plan()
        receipt=dict(operation_id='op',target_fingerprint=self.s['plan']['target_fingerprint'],
                     received_at=time.time(),update_id=1,payload_digest='a'*64,consumer_id='fixture',mode='mock',provenance='receiver')
        apply_delivery(self.j,self.s,receipt)
        self.assertEqual(self.s['results']['delivery_verification'],'mock')
        receipt['received_at']=self.s['checkpoints']['application_start']['time']-1
        with self.assertRaises(ValueError):
            apply_delivery(self.j,self.s,receipt)
