import hashlib,hmac,time,unittest
from migration_contract import canonical
from migration_engine import Engine,Runtime,Stop
from migration_reconcile import TrustedReceipts
from migration_store import Journal
from test_migration_state_privacy import MemoryStore
from test_migration_engine import Api,Ready

class FullPreserveTests(unittest.TestCase):
    def test_original_private_config_audit_is_required_before_detach(self):
        for verified in (False,True):
            with self.subTest(verified=verified):
                profile=dict(mode='full',url='https://old.example/hook',secret_token=None,certificate_pem=None,ip_address=None,allowed_updates=[],max_connections=40)
                class ProfileApi(Api):
                    def request(self,endpoint,method=None,**kwargs):
                        result=super().request(endpoint,method,**kwargs)
                        if method=='getWebhookInfo':
                            result.data.update(allowed_updates=[],max_connections=40,has_custom_certificate=False)
                        return result
                api=ProfileApi(); ready=Ready();ready.local_mode=True
                journal=Journal(MemoryStore());journal.bot='123'
                runtime=Runtime('https://api.telegram.org','https://target.example','123:synthetic',profile,'preserve')
                key='11'*32
                verifier=TrustedReceipts({'providers':{'audit':dict(key_hex=key,kinds=['quiescence'],fixture=False)}})
                engine=Engine(journal,api,ready,runtime,verifier)
                state=engine.prepare('full',quiescence=None)
                self.assertEqual(api.trace,[])
                payload=dict(version=1,kind='quiescence',operation_id='full',digest=state['digest'],observed_at=time.time(),no_writers=True,original_config_verified=verified,profile_fingerprint=state['plan']['profile_fingerprint'],**{field:state['plan'][field] for field in ('source_fingerprint','target_fingerprint','token_fingerprint')})
                receipt=dict(provider='audit',payload=payload,signature=hmac.new(bytes.fromhex(key),canonical(payload).encode(),hashlib.sha256).hexdigest())
                with self.assertRaises(Stop) as stop:
                    engine.run(state,confirm_digest=state['digest'],quiescence=receipt)
                if verified:
                    self.assertEqual(stop.exception.reason,'endpoint_change_checkpoint_required')
                    self.assertEqual(journal.outcome(state,'target_configure'),'confirmed')
                else:
                    self.assertEqual(stop.exception.reason,'full_preserve_requires_original_private_profile_verification')
                    self.assertFalse(any(method in ('deleteWebhook','logOut','close','setWebhook') for _,method,_ in api.trace))
