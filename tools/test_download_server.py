import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import socket
import threading
import time
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from download_server import Configuration, Server
from file_access import FileAccessError
from file_contract import Binding, ContractError, UpstreamTimeout, UpstreamError, file_id_value, get_file


class FakeRoot:
    def __init__(self): self.calls = 0; self.unsafe = False
    def open(self, path):
        self.calls += 1
        if self.unsafe: raise FileAccessError('unavailable')
        read, write = os.pipe(); os.write(write, b'EXACT_BYTES'); os.close(write)
        return read, SimpleNamespace(st_size=11)
    def close(self): pass


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.root = FakeRoot()
        self.config = Configuration('A' * 40, None, self.root)
        self.server = Server(('127.0.0.1', 0), self.config)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.upstream = patch('download_server.get_file', return_value='/unused/file').start()
        self.addCleanup(patch.stopall)
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2)

    def request(self, body=b'{"file_id":"synthetic"}', headers=None, path='/v1/files/download', method='POST'):
        headers = headers if headers is not None else {'Authorization': 'Bearer ' + 'A' * 40,
                                                       'Content-Type': 'application/json'}
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=3)
        connection.request(method, path, body, headers)
        response = connection.getresponse(); data = response.read()
        result = response.status, dict(response.getheaders()), data
        connection.close()
        return result

    def test_success_stream_headers(self):
        code, headers, data = self.request()
        self.assertEqual((200, b'EXACT_BYTES'), (code, data))
        self.assertEqual('no-store', headers['Cache-Control'])
        self.assertEqual('11', headers['Content-Length'])
        self.assertEqual('nosniff', headers['X-Content-Type-Options'])
        self.assertEqual(1, self.root.calls)

    def test_auth_before_upstream_and_media(self):
        for headers in ({}, {'X-Telegram-Bot-Token': '12345:SYNTHETIC'},
                        {'Authorization': 'Bearer ' + 'B' * 40}, {'Authorization': 'Bearer 12345:SYNTHETIC'}):
            self.assertEqual(401, self.request(headers=headers)[0])
        self.assertEqual(0, self.root.calls); self.upstream.assert_not_called()

    def test_schema_framing_and_methods(self):
        headers = {'Authorization': 'Bearer ' + 'A' * 40, 'Content-Type': 'application/json'}
        for body in (b'{}', b'[]', b'{"file_id":"a","path":"/secret"}',
                     b'{"file_id":"a","file_id":"b"}', b'{"file_id":false}',
                     b'{"file_id":"\\u0000"}', b'{"file_id":"/etc/passwd"}',
                     b'{"file_id":"../foreign"}', b'{"file_id":"https://other/file"}',
                     b'{"file_id":"%252e%252e"}'):
            self.assertEqual(400, self.request(body)[0])
        self.assertEqual(413, self.request(b'x' * 4097)[0])
        self.assertEqual(415, self.request(headers={**headers, 'Content-Type': 'text/plain'})[0])
        self.assertEqual(416, self.request(headers={**headers, 'Range': 'bytes=0-1'})[0])
        self.assertEqual(400, self.request(path='/v1/files/download?q=x')[0])
        self.assertEqual(405, self.request(method='HEAD')[0])
        self.upstream.assert_not_called()

    def test_duplicate_headers_and_chunked_are_rejected(self):
        for extra, expected in ((b'Authorization: Bearer ' + b'A' * 40 + b'\r\n', 401),
                                (b'Content-Length: 2\r\n', 400),
                                (b'Transfer-Encoding: chunked\r\n', 400)):
            with socket.create_connection(self.server.server_address, timeout=3) as sock:
                request = (b'POST /v1/files/download HTTP/1.1\r\nHost: local\r\nAuthorization: Bearer ' +
                           b'A' * 40 + b'\r\nContent-Type: application/json\r\nContent-Length: 2\r\n' + extra + b'\r\n{}')
                sock.sendall(request)
                self.assertIn(str(expected).encode(), sock.recv(1024).split(b'\r\n')[0])
        self.upstream.assert_not_called()

    def test_uniform_unsafe_notfound_and_upstream_timeout(self):
        self.root.unsafe = True
        code, _, body = self.request()
        self.assertEqual(404, code); self.assertNotIn(b'/unused', body)
        self.upstream.side_effect = UpstreamTimeout('private detail')
        self.assertEqual(504, self.request()[0])

    def test_limits_fail_closed(self):
        with self.assertRaises(ValueError): Server(('127.0.0.1', 0), self.config, workers=100)
        with self.assertRaises(ValueError): Server(('127.0.0.1', 0), self.config, max_duration=0)
        acquired = [self.server.slots.acquire(False) for _ in range(4)]
        self.assertTrue(all(acquired))
        try: self.assertEqual(503, self.request()[0])
        finally:
            for _ in acquired: self.server.slots.release()

    def test_disconnect_releases_slot(self):
        sock = socket.create_connection(self.server.server_address, timeout=3)
        sock.sendall(b'POST /v1/files/download HTTP/1.1\r\nHost: local\r\nAuthorization: Bearer ' +
                     b'A' * 40 + b'\r\nContent-Type: application/json\r\nContent-Length: 15\r\n\r\n{"file_id":"a"}')
        sock.close()
        deadline = time.monotonic() + 2
        while self.server.slots._value != 4 and time.monotonic() < deadline: time.sleep(0.01)
        self.assertEqual(200, self.request()[0])

    def test_header_deadline_releases_slow_client(self):
        with patch('download_server.CLIENT_TIMEOUT', 0.1):
            with socket.create_connection(self.server.server_address, timeout=3) as sock:
                sock.sendall(b'POST /v1/files/download HTTP/1.1\r\nHost:')
                time.sleep(0.3)
                # The connection ends rather than occupying a worker indefinitely.
                sock.settimeout(1)
                data = sock.recv(1024)
                self.assertTrue(not data or b'413' in data)
        self.assertEqual(200, self.request()[0])


class ContractTests(unittest.TestCase):
    def test_binding_and_file_id_validation(self):
        for value in ('', 'x' * 1025, '\ud800', False, '/file', 'a\\file',
                      'https://other/file', '..', '%2e%2e', 'a b'):
            with self.assertRaises(ContractError): file_id_value(value)
        for endpoint in ('http://api.telegram.org', 'http://user:pass@botapi', 'http://botapi/path'):
            with self.assertRaises(ContractError):
                Binding('12345:SYNTHETIC_TOKEN', endpoint, '/media', '/media/12345:SYNTHETIC_TOKEN')

    def test_real_getfile_bounds_status_and_no_redirects(self):
        class Upstream(BaseHTTPRequestHandler):
            code, body = 200, b'{"ok":true,"result":{"file_path":"/media/12345:SYNTHETIC_TOKEN/file"}}'
            extra_length = 0
            def log_message(self, *_): pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(type(self).code)
                self.send_header('Content-Length', str(len(type(self).body) + type(self).extra_length))
                self.send_header('Location', 'http://untrusted.invalid/secret')
                self.end_headers(); self.wfile.write(type(self).body)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            binding = Binding('12345:SYNTHETIC_TOKEN', 'http://127.0.0.1:' + str(server.server_port),
                              '/media', '/media/12345:SYNTHETIC_TOKEN')
            with patch.dict(os.environ, {'http_proxy': 'http://untrusted.invalid', 'HTTP_PROXY': 'http://untrusted.invalid'}):
                self.assertTrue(get_file(binding, 'synthetic').endswith('/file'))
            Upstream.code, Upstream.body = 400, b'{"ok":false,"error_code":400}'
            with self.assertRaises(FileAccessError): get_file(binding, 'unknown')
            Upstream.code = 302
            Upstream.body = b'{}'
            with self.assertRaises(UpstreamError): get_file(binding, 'synthetic')
            Upstream.code, Upstream.body = 200, b'x' * 65537
            with self.assertRaises(UpstreamError): get_file(binding, 'synthetic')
            for body in (b'not-json', b'{"ok":true,"ok":true}', b'{"ok":true,"result":{}}'):
                Upstream.body = body
                with self.subTest(body=body), self.assertRaises(UpstreamError): get_file(binding, 'synthetic')
            Upstream.body = b'{"ok":true,"result":{"file_path":"/media/12345:SYNTHETIC_TOKEN/file"}}'
            Upstream.extra_length = 10
            with self.assertRaises(UpstreamError): get_file(binding, 'synthetic')
        finally:
            server.shutdown(); server.server_close(); thread.join(2)


class RemoteClientTests(unittest.TestCase):
    def test_shipped_client_rejects_truncated_or_ambiguous_response(self):
        class Download(BaseHTTPRequestHandler):
            lengths = ['11']
            body = b'EXACT_BYTES'
            def log_message(self, *_): pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200)
                for length in self.lengths:
                    self.send_header('Content-Length', length)
                self.end_headers(); self.wfile.write(self.body)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Download)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            client = Path(__file__).resolve().parents[1] / 'examples/files/remote_client.py'
            # Only this loopback transport is substituted. The full Docker gate
            # runs the same executable through certificate-verified TLS.
            script = ('import http.client,runpy,sys; '
                      'http.client.HTTPSConnection=http.client.HTTPConnection; '
                      'client=sys.argv.pop(1); runpy.run_path(client,run_name="__main__")')
            env = {**os.environ, 'DOWNLOAD_URL': f'https://127.0.0.1:{server.server_port}/v1/files/download',
                   'DOWNLOAD_AUTH_TOKEN': 'A' * 40}
            env.pop('DOWNLOAD_AUTH_TOKEN_FILE', None)
            for lengths, body, success in ((['11'], b'EXACT_BYTES', True), (['0'], b'', True),
                                            (['11'], b'EXACT', False), ([], b'EXACT', False),
                                            (['5', '6'], b'EXACT', False), (['bad'], b'EXACT', False)):
                Download.lengths, Download.body = lengths, body
                result = subprocess.run([sys.executable, '-c', script, str(client), 'small'],
                                        env=env, capture_output=True, timeout=10)
                with self.subTest(lengths=lengths, body=body):
                    self.assertEqual(success, result.returncode == 0)
                    if success: self.assertEqual(body, result.stdout)
                    else: self.assertIn(b'download unavailable', result.stderr)
                    self.assertNotIn(b'A' * 40, result.stderr)
        finally:
            server.shutdown(); server.server_close(); thread.join(2)
