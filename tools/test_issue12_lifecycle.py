"""Production readiness protocol matrix; no bot method or credentials."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import shutil
import subprocess
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name != 'nt' and shutil.which('curl') and shutil.which('jq'),
                     'POSIX curl/jq execution deferred to CI/gates')
class ProtocolTests(unittest.TestCase):
    def test_status_body_type_and_redirect_matrix(self):
        class Handler(BaseHTTPRequestHandler):
            response = (404, 'application/json; charset=utf-8', b'{"ok":false,"error_code":404}')
            def do_GET(self):
                status, content_type, body = self.response
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Location', '/redirected')
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        good = b'{"ok":false,"error_code":404}'
        cases = [(404, 'application/json; charset=utf-8', good, True),
                 (200, 'application/json', good, False),
                 (302, 'application/json', good, False),
                 (404, 'text/html', good, False)]
        for body in (b'{}', b'null', b'[]', b'{', good + good, b' ' * 17000 + good,
                     b'{"ok":0,"error_code":404}', b'{"ok":false,"error_code":"404"}',
                     b'{"ok":false,"error_code":true}'):
            cases.append((404, 'application/json', body, False))
        env = {**os.environ, 'TELEGRAM_HTTP_PORT': str(server.server_port),
               'TELEGRAM_HTTP_IP_ADDRESS': '0.0.0.0'}
        for status, content_type, body, expected in cases:
            Handler.response = status, content_type, body
            result = subprocess.run(['sh', str(ROOT / 'tools/botapi_healthcheck.sh')],
                                    env=env, capture_output=True, timeout=5)
            self.assertEqual(result.returncode == 0, expected, (status, content_type, body[:100]))
            self.assertEqual(result.stdout + result.stderr, b'')


class ComposeLifecycleTests(unittest.TestCase):
    def test_grace_and_startup_order_are_declared(self):
        base = (ROOT / 'docker-compose.yml').read_text()
        gateway = base.split('  gateway:', 1)[1]
        self.assertIn('condition: service_healthy', gateway)
        self.assertIn('condition: service_started', gateway)
        self.assertIn('stop_grace_period: 120s', base)
        self.assertIn('condition: service_healthy', (ROOT / 'docker-compose.downloads.yml').read_text())
