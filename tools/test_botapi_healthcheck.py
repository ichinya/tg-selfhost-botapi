import os
from pathlib import Path
import shutil
import subprocess
import unittest


class HelperTests(unittest.TestCase):
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
