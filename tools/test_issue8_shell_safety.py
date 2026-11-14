import os, subprocess, tempfile, unittest
from pathlib import Path
from migration_contract import build_plan,plan_digest
from migration_export import export_operation
class ExportContractTests(unittest.TestCase):
    def test_export_has_no_second_protocol(self):
        plan=build_plan(operation_id='op',bot_id='123',source='https://api.telegram.org',target='https://target.example',token='123:canary',profile={'mode':'polling'},action='polling',drop=False,key=b'x'*32)
        output=export_operation(dict(plan=plan,digest=plan_digest(plan)))
        self.assertNotIn('canary',str(output));self.assertNotIn('curl',str(output))
    @unittest.skipUnless(os.name=='posix','mandatory POSIX shell gate')
    def test_root_executes_exact_cli_argv_without_shell_expansion(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp); fake=tmp/'python3'; capture=tmp/'capture'
            fake.write_text('#!/bin/sh\nif [ "$1" = -c ]; then exit 0; fi\nprintf "%s\\0" "$@" > "$CAPTURE"\n')
            fake.chmod(0o700)
            marker="space ' \" $(touch marker) `touch marker`\n--flag"
            result=subprocess.run(['bash',str(root/'migrate_off_to_self.sh'),'status','--operation','op','--state-dir',marker],cwd=tmp,env={**os.environ,'MIGRATION_PYTHON':str(fake),'CAPTURE':str(capture)},capture_output=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(capture.read_bytes().split(b'\0')[:-1],[str(root/'tools/migration_cli.py').encode(),b'status',b'--operation',b'op',b'--state-dir',marker.encode()])
            self.assertFalse((tmp/'marker').exists())
