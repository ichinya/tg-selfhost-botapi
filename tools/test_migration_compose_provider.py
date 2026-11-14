import time, unittest
from migration_compose_provider import Collector
from migration_contract import build_plan,plan_digest
from migration_reconcile import TrustedReceipts

class CollectorTests(unittest.TestCase):
    def setup(self):
        identity='1'*64
        plan=build_plan(operation_id='test',bot_id='123',source='https://api.telegram.org',target='https://target.example',token='123:synthetic',profile={'mode':'polling'},action='polling',drop=False,key=b'x'*32,fixture=True)
        config=dict(provider='compose',key_hex='22'*32,fixture=True,project='fixture',containers={identity:dict(service='app',image='sha256:'+'3'*64)},application=identity,endpoint='https://target.example',endpoint_variable='BOT_API_BASE_URL',target_fingerprint=plan['target_fingerprint'])
        item=dict(Id=identity,Image='sha256:'+'3'*64,Config=dict(Labels={'com.docker.compose.project':'fixture','com.docker.compose.service':'app'},Env=['BOT_API_BASE_URL=https://target.example']),State=dict(Running=False,Status='exited'))
        return config,item,dict(plan=plan,digest=plan_digest(plan),checkpoints={})
    def test_signed_stopped_topology_and_tampering(self):
        config,item,state=self.setup()
        collector=Collector(config,lambda _:item)
        envelope=collector.collect('quiescence',state)
        verify=TrustedReceipts({'providers':{'compose':dict(key_hex=config['key_hex'],kinds=['quiescence'],fixture=True)}})
        self.assertTrue(verify(envelope,kind='quiescence',state=state)['no_writers'])
        envelope['payload']['digest']='0'*64
        with self.assertRaises(ValueError): verify(envelope,kind='quiescence',state=state)
    def test_running_wrong_generation_and_effect_are_blocked(self):
        config,item,state=self.setup(); collector=Collector(config,lambda _:item)
        item['State']['Running']=True
        for kind in ('quiescence','application_start','effect','state_transfer','delivery'):
            with self.subTest(kind=kind),self.assertRaises(ValueError): collector.collect(kind,state)
        item['State']['Running']=False; item['Image']='sha256:'+'4'*64
        with self.assertRaises(ValueError): collector.collect('quiescence',state)
