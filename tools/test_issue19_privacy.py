from pathlib import Path
import unittest
from migration_contract import build_plan,plan_digest
from migration_export import export_operation

class PrivacyTests(unittest.TestCase):
    def test_static_entry_cannot_collect_or_send_secrets(self):
        root=Path(__file__).resolve().parents[1]
        entry=(root/'tg_selfhost_botapi_migrator.html').read_text(encoding='utf-8').lower()
        for forbidden in ('<input','<textarea','<script','fetch(', 'localstorage','sessionstorage'):
            self.assertNotIn(forbidden,entry)
    def test_private_profile_canaries_are_absent_from_sealed_export(self):
        profile=dict(mode='full',url='https://private.example/secret-path',secret_token='private_canary',certificate_pem=None,ip_address=None,allowed_updates=[],max_connections=40)
        plan=build_plan(operation_id='op',bot_id='123',source='https://api.telegram.org',target='https://private-target.example',token='123:token_canary',profile=profile,action='set',drop=False,key=b'x'*32)
        output=str(export_operation(dict(plan=plan,digest=plan_digest(plan))))
        for marker in ('private_canary','token_canary','private.example','private-target.example','secret-path'):
            self.assertNotIn(marker,output)
