import json
import unittest
import os
import subprocess
import tempfile
from pathlib import Path
from migration_contract import build_plan, plan_digest, validate_plan
from migration_export import export_operation


class PublicExports(unittest.TestCase):
    def test_private_prefixes_never_exported_and_schema_closed(self):
        plan=build_plan(operation_id='safe',bot_id='123',source='https://source.example/private_prefix',
                        target='https://target.example/another_private',token='123:synthetic_canary',
                        profile={'mode':'polling'},action='polling',drop=False,key=b'x'*32,direction='local_to_local')
        exported=export_operation({'plan':plan,'digest':plan_digest(plan)})
        text=json.dumps(exported)
        for marker in ('private_prefix','another_private','synthetic_canary','https://'):
            self.assertNotIn(marker,text)
        with self.assertRaises(ValueError): validate_plan(dict(plan, private='injected'))
        self.assertEqual(exported['digest'],plan_digest(plan))
        self.assertTrue(all('tools/migration_cli.py' in c for c in exported['commands']))

    @unittest.skipUnless(os.name=='posix','Bash/jq projection requires POSIX')
    def test_public_diagnostics_ignores_injected_body_and_fails_closed(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory);run=target/'run';run.mkdir(mode=0o700)
            request=run/'request-1';request.mkdir(mode=0o700)
            (run/'summary.json').write_text(json.dumps({'completed':False,'partial_migration':True,
                'continuation_requires_reconciliation':True,'private':'reflected_canary'}))
            receipt=request/'receipt.json'
            receipt.write_text(json.dumps({'method':'getMe','endpoint_role':'source','outcome':'UNKNOWN',
                'effect_possible':True,'mutating':False,'sanitization_status':'complete','description':'reflected_canary'}))
            receipt.chmod(0o600)
            script='source "$1"; WP_SCRIPT_DIR=$2; source "$3"; API_TMP=$4; RAW_RETAINED=false; REQUEST_ACTIVE=false; public_diagnostics'
            cmd=['bash','-c',script,'_',str(root/'tools/webhook_profile_runtime.sh'),str(root),str(root/'tools/migration_diagnostics_main.sh'),str(run)]
            result=subprocess.run(cmd,capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,'diagnostics projection failed')
            manifest=json.loads((run/'public-manifest.json').read_text())
            self.assertEqual(manifest['receipts'][0]['outcome'],'UNKNOWN')
            self.assertTrue(manifest['continuation_requires_reconciliation'])
            self.assertNotIn('reflected_canary',json.dumps(manifest)+result.stdout+result.stderr)
            bad=json.loads(receipt.read_text());bad['raw_retained']=True;receipt.write_text(json.dumps(bad))
            result=subprocess.run(cmd,capture_output=True,text=True,timeout=10)
            self.assertNotEqual(result.returncode,0)
            self.assertFalse((run/'public-manifest.json').exists())
