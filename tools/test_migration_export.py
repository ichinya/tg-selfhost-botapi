import unittest
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from migration_export import export_operation
from migration_contract import build_plan, plan_digest


class ExportTests(unittest.TestCase):
    def test_same_plan_identity_and_no_independent_executor(self):
        plan=build_plan(operation_id='op',bot_id='123',source='https://api.telegram.org',target='https://target.example',
                        token='123:secret_canary',profile={'mode':'polling'},action='polling',drop=False,key=b'x'*32)
        result=export_operation({'plan':plan,'digest':plan_digest(plan)})
        self.assertEqual(result['digest'],plan_digest(plan))
        text=str(result)
        for secret in ('secret_canary','https://','curl','binding.key'):
            self.assertNotIn(secret,text)
        self.assertTrue(all('--operation op' in command for command in result['commands']))

    def test_rejects_invalid_or_unbound_digest(self):
        plan=build_plan(operation_id='op',bot_id='123',source='https://api.telegram.org',target='https://target.example',
                        token='123:secret_canary',profile={'mode':'polling'},action='polling',drop=False,key=b'x'*32)
        for digest in (None, '', '0'*64, '$(printf CANARY)', 'A'*64):
            with self.subTest(digest=digest), self.assertRaisesRegex(ValueError, '^invalid plan digest$'):
                export_operation({'plan':plan,'digest':digest})

    @unittest.skipUnless(os.name == 'posix' and shutil.which('bash'), 'Requires POSIX Bash')
    def test_export_preserves_state_directory_as_one_argument(self):
        plan=build_plan(operation_id='op',bot_id='123',source='https://api.telegram.org',target='https://target.example',
                        token='123:secret_canary',profile={'mode':'polling'},action='polling',drop=False,key=b'x'*32)
        result=export_operation({'plan':plan,'digest':plan_digest(plan)})
        with tempfile.TemporaryDirectory() as tmp:
            capture=Path(tmp)/'argv'
            mock=Path(tmp)/'python3'
            mock.write_text("#!/bin/sh\nprintf '%s\\0' \"$@\" > \"$CAPTURE\"\n", encoding='utf-8')
            mock.chmod(0o700)
            state="space ' \" $(touch marker) \x60touch marker\x60 Unicode-λ\nend"
            env={**os.environ, 'PATH':tmp+os.pathsep+os.environ['PATH'], 'CAPTURE':str(capture), 'MIGRATION_STATE_DIR':state}
            for command in result['commands']:
                subprocess.run(['bash','-c',command],cwd=tmp,env=env,check=True)
                args=capture.read_bytes().split(b'\0')[:-1]
                self.assertEqual(args[args.index(b'--state-dir')+1], state.encode())
                self.assertFalse((Path(tmp)/'marker').exists())
