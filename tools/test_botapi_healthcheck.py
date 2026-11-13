import os
from pathlib import Path
import shutil
import subprocess
import unittest


class HelperTests(unittest.TestCase):
    @unittest.skipUnless(os.name != 'nt' and shutil.which('curl') and shutil.which('jq'), 'POSIX curl/jq required')
    def test_one_json_document_only(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        class Handler(BaseHTTPRequestHandler):
            body = b'{"ok":false,"error_code":404}'
            def do_GET(self):
                self.send_response(404)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(self.body)
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        path = Path(__file__).resolve().parents[1] / 'tools/botapi_healthcheck.sh'
        for body, expected in [(b'{"ok":false,"error_code":404}', True),
                               (b'{"ok":false,"error_code":404}\n{"ok":false,"error_code":404}', False),
                               (b'{"ok":"false","error_code":404}', False),
                               (b'{"ok":false,"error_code":"404"}', False)]:
            Handler.body = body
            result = subprocess.run(['sh', str(path)], env={**os.environ, 'TELEGRAM_HTTP_PORT': str(server.server_port)}, capture_output=True, timeout=5)
            self.assertEqual(result.returncode == 0, expected, body)
            self.assertEqual(result.stdout + result.stderr, b'')

    @unittest.skipUnless(os.name != 'nt' and shutil.which('curl') and shutil.which('jq'), 'POSIX curl/jq required; NOTRUN on Windows')
    def test_expected_404_and_invalid_contract(self):
        from observability_mock_target import Handler
        from http.server import ThreadingHTTPServer
        import threading
        target = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=target.serve_forever,daemon=True).start()
        path = Path(__file__).resolve().parents[1]/'tools/botapi_healthcheck.sh'
        try:
            for ready in [True,False]:
                Handler.root_ok=ready
                result=subprocess.run(['sh',str(path)],env={**os.environ,'TELEGRAM_HTTP_IP_ADDRESS':'127.0.0.1',
                     'TELEGRAM_HTTP_PORT':str(target.server_port)},capture_output=True,timeout=5)
                self.assertEqual(result.returncode==0,ready)
                self.assertEqual(result.stdout+result.stderr,b'')
        finally:
            Handler.root_ok=True; target.shutdown(); target.server_close()

    @unittest.skipUnless(os.name != 'nt' and shutil.which('curl') and shutil.which('jq'), 'POSIX curl/jq required; NOTRUN on Windows')
    def test_invalid_port_silent(self):
        path = Path(__file__).resolve().parents[1] / 'tools/botapi_healthcheck.sh'
        r = subprocess.run(['sh', str(path)], env={**os.environ, 'TELEGRAM_HTTP_PORT':'invalid'}, capture_output=True, timeout=5)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(r.stdout + r.stderr, b'')
