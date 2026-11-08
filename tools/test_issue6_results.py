"""Run the shipped-page result contract with an external watchdog."""
import subprocess
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from issue10_test_support import bash_binary


class ResultContract(unittest.TestCase):
    def test_node_contract(self):
        result = subprocess.run(
            ['node', str(ROOT / 'tools/issue10_timeout.cjs'), '60', 'node',
             str(ROOT / 'tools/issue6_result_contract.cjs')],
            cwd=ROOT, capture_output=True, text=True, timeout=75,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('5 scenarios passed', result.stdout)

    def test_shell_known_refusal_stops(self):
        calls = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                method = self.path.rsplit('/', 1)[-1]
                calls.append(method)
                result = {'id': 123} if method == 'getMe' else {'url': ''}
                self.reply(200, {'ok': True, 'result': result})

            def do_POST(self):
                calls.append(self.path.rsplit('/', 1)[-1])
                self.rfile.read(int(self.headers.get('Content-Length', '0')))
                self.reply(400, {'ok': False, 'error_code': 400})

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
            js = ("const p=require('./tools/issue10_ui_harness.cjs').page({mode:'hook-only',"
                  "hook:'https://sink.test/hook'}); p.elements.get('oldApi').value=process.argv[1];"
                  "process.stdout.write(p.plan());")
            plan = subprocess.run(['node', '-e', js, address], cwd=ROOT, check=True,
                                  capture_output=True, text=True, timeout=10).stdout
            result = subprocess.run([bash_binary(), '-c', plan],
                                    input=b'y\n123:synthetic_token_for_tests_only\n', cwd=ROOT,
                                    capture_output=True, timeout=20)
            self.assertNotEqual(result.returncode, 0, repr((calls, result.stdout, result.stderr)))
            self.assertIn(b'ERROR phase=delivery_configured', result.stderr)
            self.assertNotIn(b'synthetic_token', result.stderr)
            self.assertEqual(calls, ['getMe', 'getWebhookInfo', 'setWebhook'])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
