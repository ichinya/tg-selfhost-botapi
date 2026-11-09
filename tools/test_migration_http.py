import json
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import unittest
from unittest import mock
from migration_http import Client,classify
from migration_probe import protocol_ok, validate_evidence,DockerEvidence


class Handler(BaseHTTPRequestHandler):
    paths=[]
    status=404
    body=b'{"ok":false,"error_code":404}'
    content='application/json'
    def log_message(self,*args):
        pass
    def do_GET(self):
        type(self).paths.append(self.path)
        self.send_response(type(self).status)
        self.send_header('Content-Type',type(self).content)
        self.send_header('Content-Length',str(len(type(self).body)))
        self.end_headers()
        self.wfile.write(type(self).body)
    do_POST=do_GET


class HttpTests(unittest.TestCase):
    def setUp(self):
        Handler.paths=[]
        Handler.status=404
        Handler.body=b'{"ok":false,"error_code":404,"description":"any wording"}'
        Handler.content='application/json'
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.endpoint='http://127.0.0.1:'+str(self.server.server_port)+'/prefix'

    def test_token_free_prefix_and_protocol(self):
        self.assertTrue(protocol_ok(Client(fixture=True).request(self.endpoint)))
        self.assertEqual(Handler.paths,['/prefix/'])
        Handler.content='text/html'
        self.assertFalse(protocol_ok(Client(fixture=True).request(self.endpoint)))

    def test_redirect_never_followed_and_body_bounded(self):
        Handler.status=302
        result=Client(fixture=True).request(self.endpoint,'logOut',token='123:synthetic',effect=True)
        self.assertEqual(result.outcome,'unknown')
        self.assertEqual(len(Handler.paths),1)
        Handler.status=200
        Handler.body=b'x'*200
        result=Client(fixture=True,body_limit=20).request(self.endpoint,'logOut',token='123:synthetic',effect=True)
        self.assertEqual(result.outcome,'unknown')

    def test_classification(self):
        for status,body,expected in [(200,b'cut','unknown'),(502,b'proxy','unknown'),
                                     (401,b'{"ok":false,"error_code":401}','failed'),
                                     (429,b'{"ok":false,"error_code":429,"parameters":{"retry_after":12}}','waiting')]:
            self.assertEqual(classify(status,body,effect=True).outcome,expected)

    def test_allowlist_and_invalid_token_before_connect(self):
        with self.assertRaises(ValueError):
            Client(fixture=True).request('https://api.telegram.org')
        with self.assertRaises(ValueError):
            Client(fixture=True).request(self.endpoint,'getMe',token='unsafe value')
        self.assertEqual(Handler.paths,[])

    def test_incomplete_evidence_blocked(self):
        with self.assertRaises(ValueError):
            validate_evidence({'endpoint':self.endpoint},self.endpoint)

    def test_local_http_and_cloud_limits(self):
        from migration_probe import validate_webhook_mode
        profile = {'mode': 'url_only', 'url': 'http://10.0.0.2:9000/hook'}
        validate_webhook_mode(profile, True)
        with self.assertRaises(ValueError):
            validate_webhook_mode(profile, False)

    def test_local_build_and_container_temp_storage(self):
        from migration_mock import deployment
        record = deployment(self.endpoint)
        record.update(image_digest=None, temp_mount_id=None)
        validate_evidence(record, self.endpoint)

    def test_managed_inspection_timeout_is_a_safe_error(self):
        import subprocess
        with mock.patch('subprocess.run',side_effect=subprocess.TimeoutExpired(['docker','inspect','synthetic'],20)):
            with self.assertRaisesRegex(ValueError,'managed deployment inspection failed'):
                DockerEvidence.run('inspect','synthetic')

    def test_managed_direct_file_credentials_and_actual_mode_with_local_build(self):
        from pathlib import Path
        work,temp='/var/lib/telegram-bot-api','/tmp/telegram-bot-api'
        for file_credentials in (False,True):
            for local_flag in (False,True):
                env=['TELEGRAM_WORK_DIR='+work,'TELEGRAM_TEMP_DIR='+temp,'TELEGRAM_LOCAL=true']
                env+=['TELEGRAM_API_ID_FILE=/run/secrets/id','TELEGRAM_API_HASH_FILE=/run/secrets/hash'] if file_credentials else [
                    'TELEGRAM_API_ID=12345','TELEGRAM_API_HASH='+'a'*32]
                info={'Image':'sha256:'+'1'*64,'Id':'fixture','State':{'Running':True},'Config':{'Env':env},
                      'Mounts':[{'Destination':work,'Source':str(Path(__file__).resolve().parent),'RW':True}]}
                def run(*args):
                    if args[0]=='inspect': return json.dumps([info])
                    if args[:2]==('image','inspect'): return json.dumps([{'RepoDigests':[]}])
                    if args[2:]==('cat','/proc/1/cmdline'):
                        return '\x00'.join(['/usr/local/bin/telegram-bot-api','--dir='+work,'--temp-dir='+temp]+(['--local'] if local_flag else []))
                    if 'id' in args: return '1000'
                    return ''
                adapter=DockerEvidence('fixture',self.endpoint,info['Image'],b'x'*32)
                with mock.patch.object(adapter,'run',side_effect=run):
                    record=adapter()
                self.assertEqual(record['local_mode'],local_flag)
                self.assertIsNone(record['image_digest'])
                self.assertIsNone(record['temp_mount_id'])
                validate_evidence(record,self.endpoint)
