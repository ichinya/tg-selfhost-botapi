"""Run the shipped-page result contract with an external watchdog."""
import subprocess
import json
import os
import socket
import sys
import threading
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

ROOT = Path(__file__).resolve().parent.parent
TOKEN = '123:synthetic_token_for_tests_only'
HOOK = 'https://sink.test/private-hook?secret=synthetic-secret'
sys.path.insert(0, str(Path(__file__).resolve().parent))
from issue10_test_support import bash_binary, posix_path


class ResultContract(unittest.TestCase):
    def test_node_contract(self):
        result = subprocess.run(
            ['node', str(ROOT / 'tools/issue10_timeout.cjs'), '60', 'node',
             str(ROOT / 'tools/issue6_result_contract.cjs')],
            cwd=ROOT, capture_output=True, text=True, timeout=75,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('10 scenarios passed', result.stdout)

    def run_shell(self, scenario, mode='hook-only', runtime_hook=HOOK):
        calls = []
        effects = []
        hooks = {'source': 'https://sink.test/inherited', 'target': ''}
        initial_hook = hooks['source']

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path == '/target/':
                    calls.append(('target', 'probe'))
                    self.reply(404, {'ok': False, 'error_code': 404, 'description': 'Not Found'})
                    return
                method = self.path.rsplit('/', 1)[-1]
                role = 'source' if self.path.startswith('/source/') else 'target'
                calls.append((role, method))
                if method == 'getMe':
                    result = {'id': 456 if scenario == 'id-mismatch' and role == 'target' else 123}
                else:
                    final = any(m == 'setWebhook' for _, m in effects)
                    result = {'url': 'https://other.test/hook' if final and scenario == 'url-mismatch' else hooks[role],
                              'max_connections': 40, 'has_custom_certificate': False,
                              'pending_update_count': 0, 'allowed_updates': []}
                self.reply(200, {'ok': True, 'result': result})

            def do_POST(self):
                role = 'source' if self.path.startswith('/source/') else 'target'
                method = self.path.rsplit('/', 1)[-1]
                calls.append((role, method))
                body = parse_qs(self.rfile.read(int(self.headers.get('Content-Length', '0'))).decode())
                if method == 'setWebhook' and scenario == '400':
                    self.reply(400, {'ok': False, 'error_code': 400})
                    return
                if (method == 'setWebhook' and scenario == '429') or (method == 'logOut' and scenario == 'logout-429'):
                    self.reply(429, {'ok': False, 'error_code': 429, 'parameters': {'retry_after': 600}})
                    return
                effects.append((role, method))
                if method == 'setWebhook':
                    hooks[role] = body['url'][0]
                elif method == 'deleteWebhook':
                    hooks[role] = ''
                if method == 'setWebhook' and scenario == 'lost-ack':
                    self.close_connection = True
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                self.reply(200, {'ok': True, 'result': True})

            def reply(self, status, body):
                encoded = json.dumps(body).encode()
                self.send_response(status)
                self.send_header('Content-Length', str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            address = 'http://127.0.0.1:%d' % server.server_port
            # Call the shipped generator directly so both cloud/local roles stay on loopback.
            config = {'mode': mode, 'token': TOKEN, 'oldApi': address + '/source',
                      'newApi': address + '/target', 'webhook': HOOK, 'dropPending': False}
            js = ("const p=require('./tools/issue10_ui_harness.cjs').page();"
                  "process.stdout.write(p.run('buildCommands(' + process.argv[1] + ')').join('\\n'));")
            plan = subprocess.run(['node', '-e', js, json.dumps(config)], cwd=ROOT, check=True,
                                  capture_output=True, text=True, timeout=10).stdout
            self.assertNotIn(HOOK, plan)
            self.assertNotIn(TOKEN, plan)
            env = {k: v for k, v in os.environ.items() if k in ('PATH', 'HOME', 'SYSTEMROOT', 'TEMP', 'TMP')}
            env.update(BOT_TOKEN=TOKEN, SELF_BOT_URL=address + ('/target' if mode == 'official-to-self' else '/source'),
                       OFFICIAL_BOT_URL=address + '/source', WEBHOOK_URL=runtime_hook,
                       WEBHOOK_SECRET_MODE='none', WEBHOOK_IP_MODE='dns', WEBHOOK_CERTIFICATE_MODE='none',
                       NO_PROXY='127.0.0.1', no_proxy='127.0.0.1')
            with tempfile.TemporaryDirectory() as temp:
                script = Path(temp) / 'plan.sh'
                script.write_text(plan, encoding='utf-8', newline='\n')
                result = subprocess.run([bash_binary(), posix_path(script)], input=b'y\n', cwd=ROOT, env=env,
                                        capture_output=True, timeout=30)
            for secret in (TOKEN, HOOK):
                self.assertNotIn(secret.encode(), result.stdout + result.stderr)
            return result, calls, effects, hooks, initial_hook
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_shell_known_refusal_stops(self):
        result, calls, effects, _, _ = self.run_shell('400')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'API HTTP rejection; stop and reconcile', result.stderr)
        self.assertEqual(calls, [('source', 'getMe'), ('source', 'getWebhookInfo'), ('source', 'getWebhookInfo'), ('source', 'setWebhook')])
        self.assertEqual(effects, [])

    def test_shell_429_stops_without_effect(self):
        result, calls, effects, _, _ = self.run_shell('429')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'API HTTP rejection; stop and reconcile', result.stderr)
        self.assertEqual(calls[-1], ('source', 'setWebhook'))
        self.assertEqual(len(calls), 4)
        self.assertEqual(effects, [])

    def test_shell_429_after_detach_stops(self):
        result, calls, effects, _, _ = self.run_shell('logout-429', mode='official-to-self')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'API HTTP rejection; stop and reconcile', result.stderr)
        self.assertEqual(calls[-1], ('source', 'logOut'))
        self.assertEqual(effects, [('source', 'deleteWebhook')])
        self.assertFalse(any(role == 'target' and method != 'probe' for role, method in calls))

    def test_shell_lost_ack_retains_remote_effect(self):
        result, calls, effects, hooks, _ = self.run_shell('lost-ack')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'UNKNOWN: response unavailable; reconcile without retry', result.stderr)
        self.assertEqual(calls[-1], ('source', 'setWebhook'))
        self.assertEqual(effects, [('source', 'setWebhook')])
        self.assertEqual(hooks['source'], HOOK)
        self.assertEqual(len(calls), 4)

    def test_shell_final_url_mismatch_is_reported(self):
        result, calls, effects, _, _ = self.run_shell('url-mismatch')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'"observable_profile_matches":false', result.stdout)
        self.assertEqual(calls[-1], ('source', 'getWebhookInfo'))
        self.assertEqual(effects, [('source', 'setWebhook')])

    def test_shell_target_id_mismatch_stops_before_webhook(self):
        result, calls, effects, _, _ = self.run_shell('id-mismatch', mode='official-to-self')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'Bot identity mismatch; source login forbidden', result.stderr)
        self.assertEqual(calls[-1], ('target', 'getMe'))
        self.assertEqual(effects, [('source', 'deleteWebhook'), ('source', 'logOut')])

    def test_shell_empty_webhook_env_inherits_source(self):
        result, calls, effects, hooks, initial_hook = self.run_shell('success', runtime_hook='')
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertIn(b'"observable_profile_matches":true', result.stdout)
        self.assertIn(b'"delivery_confirmed":false', result.stdout)
        self.assertEqual(hooks['source'], initial_hook)
        self.assertEqual(effects, [('source', 'setWebhook')])
        self.assertEqual(calls[-1], ('source', 'getWebhookInfo'))


if __name__ == '__main__':
    unittest.main()
