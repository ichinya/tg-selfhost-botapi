import http.client
import io
import json
import os
import socket
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from tools import download_server as server
from tools.file_contract import UpstreamError
from tools.file_access import FileAccessError

CRED_A, CRED_B = 'A' * 40, 'B' * 40


def config():
    return {'bots': [dict(alias='bot-' + letter.lower(), credential=credential,
                         token='12345:SYNTHETIC_' + letter, endpoint='http://botapi:8081',
                         media_root='/srv/media', bot_root='/srv/media/12345:SYNTHETIC_' + letter)
                     for letter, credential in [('A', CRED_A), ('B', CRED_B)]]}


class RegistryTests(unittest.TestCase):
    def test_auth_binding_and_rotation_before_io(self):
        with patch.object(server, 'Root'):
            registry = server.Registry(config())
            self.addCleanup(registry.close)
            for headers, alias, expected in [([], 'bot-a', 401), (['Bearer wrong'], 'bot-a', 401),
                    (['Bearer ' + CRED_A] * 2, 'bot-a', 401), (['Bearer ' + CRED_A], 'bot-b', 403),
                    (['Bearer ' + CRED_A], 'unknown', 403), (['Bearer ' + CRED_A], 'bot-a', 200)]:
                self.assertEqual(registry.authorize(headers, alias)[0], expected)
            updated = config()
            updated['bots'][0]['credential'] = 'C' * 40
            rotated = server.Registry(updated)
            self.addCleanup(rotated.close)
            self.assertEqual(rotated.authorize(['Bearer ' + CRED_A], 'bot-a')[0], 401)

    def test_duplicate_identity_and_overlapping_roots_reject_startup(self):
        for mutation in ('credential', 'alias', 'root', 'unknown'):
            value = config()
            if mutation in ('credential', 'alias'):
                value['bots'][1][mutation] = value['bots'][0][mutation]
            elif mutation == 'root':
                value['bots'][1]['token'] = value['bots'][0]['token']
                value['bots'][1]['bot_root'] = value['bots'][0]['bot_root']
            else:
                value['bots'][0]['path'] = '/etc/passwd'
            with patch.object(server, 'Root'), self.assertRaises(server.ContractError):
                server.Registry(value)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.root_patch = patch.object(server, 'Root')
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.registry = server.Registry(config())
        self.addCleanup(self.registry.close)
        self.service = server.Server(('127.0.0.1', 0), self.registry)
        self.thread = threading.Thread(target=self.service.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.upstream_patch = patch.object(server, 'get_file', return_value='/srv/media/result')
        self.upstream = self.upstream_patch.start()
        self.addCleanup(self.upstream_patch.stop)

    def stop(self):
        self.service.shutdown()
        self.service.server_close()
        self.thread.join(2)

    def request(self, body=b'{"file_id":"fixture"}', credential=CRED_A, method='POST',
                path='/downloads/bot-a', extra=None):
        conn = http.client.HTTPConnection(*self.service.server_address, timeout=3)
        headers = {'Content-Type': 'application/json'}
        if credential:
            headers['Authorization'] = 'Bearer ' + credential
        headers.update(extra or {})
        try:
            conn.request(method, path, body=body, headers=headers)
            result = conn.getresponse()
            return result.status, dict(result.getheaders()), result.read()
        finally:
            conn.close()

    def test_unauthorized_scopes_and_legacy_never_call_upstream(self):
        for kwargs, status in [(dict(credential=None), 401), (dict(credential='wrong'), 401),
                (dict(credential=CRED_B), 403), (dict(path='/downloads/unknown'), 403),
                (dict(credential=None, extra={'X-Telegram-Bot-Token': 'secret'}), 401),
                (dict(method='HEAD'), 405), (dict(method='GET'), 405)]:
            with self.subTest(kwargs=kwargs):
                self.assertEqual(self.request(**kwargs)[0], status)
        self.upstream.assert_not_called()
        for entry in self.registry.entries:
            entry.root.open.assert_not_called()

    def test_query_credentials_and_unknown_methods_do_not_bypass_contract(self):
        self.assertEqual(self.request(path='/downloads/bot-a?path=/etc/passwd')[0], 400)
        self.assertEqual(self.request(method='BREW')[0], 405)
        self.upstream.assert_not_called()

    def test_header_budget_is_enforced_before_upstream(self):
        with socket.create_connection(self.service.server_address, timeout=3) as sock:
            sock.sendall(b'POST /downloads/bot-a HTTP/1.1\r\nHost: fixture\r\nX-Large: '
                         + b'x' * 16400 + b'\r\n\r\n')
            response = http.client.HTTPResponse(sock)
            response.begin()
            self.assertEqual(response.status, 413)
            response.read()
        self.upstream.assert_not_called()

    def test_slow_header_has_an_absolute_deadline(self):
        with patch.object(server, 'CLIENT_TIMEOUT', 0.15):
            with socket.create_connection(self.service.server_address, timeout=2) as sock:
                stop = threading.Event()
                sock.sendall(b'POST /downloads/bot-a HTTP/1.1\r\nX-Slow: ')
                def drip():
                    try:
                        while not stop.wait(0.03):
                            sock.sendall(b'x')
                    except OSError:
                        pass
                sender = threading.Thread(target=drip, daemon=True)
                sender.start()
                started = time.monotonic()
                response = None
                try:
                    response = http.client.HTTPResponse(sock)
                    try:
                        response.begin()
                        self.assertEqual(response.status, 413)
                        response.read()
                    except (ConnectionResetError, ConnectionAbortedError, http.client.RemoteDisconnected):
                        # A partial slow header may be dropped at the hard deadline;
                        # neither a response status nor graceful TCP close is promised.
                        pass
                    self.assertLess(time.monotonic() - started, 1.5)
                finally:
                    stop.set()
                    sender.join(1)
                    if response is not None:
                        response.close()
        self.upstream.assert_not_called()

    def test_bad_bodies_framing_range_and_limits_precede_upstream(self):
        for body, extra, expected in [(b'{"file_id":"a","path":"/etc/passwd"}', {}, 400),
                (b'{"file_id":"a","file_id":"b"}', {}, 400), (b'[]', {}, 400),
                (b'{"file_id":"' + b'a' * 1025 + b'"}', {}, 400),
                (b'x' * 16385, {}, 413), (b'{}', {'Range': 'bytes=0-1'}, 416),
                (b'{}', {'Transfer-Encoding': 'chunked'}, 400)]:
            with self.subTest(expected=expected):
                self.assertEqual(self.request(body=body, extra=extra)[0], expected)
        self.upstream.assert_not_called()

    def test_success_stream_has_only_open_fd_metadata(self):
        def opened(_):
            readfd, writefd = os.pipe()
            os.write(writefd, b'FIXTURE_BYTES')
            os.close(writefd)
            return readfd, SimpleNamespace(st_size=13)
        self.registry.entries[0].root.open.side_effect = opened
        status, headers, body = self.request()
        self.assertEqual((status, body), (200, b'FIXTURE_BYTES'))
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(headers['Content-Length'], '13')
        self.assertEqual(headers['Content-Disposition'], 'attachment; filename="download.bin"')
        for name in ('ETag', 'Last-Modified', 'Content-Range', 'Location', 'Accept-Ranges'):
            self.assertNotIn(name, headers)

    def test_upstream_and_path_errors_are_generic(self):
        self.upstream.side_effect = UpstreamError('RAW_PRIVATE_CANARY')
        status, _, body = self.request()
        self.assertEqual(status, 502)
        self.assertNotIn(b'RAW_PRIVATE', body)
        self.upstream.side_effect = None
        self.registry.entries[0].root.open.side_effect = FileAccessError('PRIVATE_PATH')
        status, _, body = self.request()
        self.assertEqual(status, 404)
        self.assertNotIn(b'PRIVATE_PATH', body)

    def test_duplicate_auth_and_content_length_are_rejected(self):
        for duplicate, expected in [(b'Authorization: Bearer ' + CRED_A.encode() + b'\r\n', 401),
                                    (b'Content-Length: 2\r\n', 400)]:
            with socket.create_connection(self.service.server_address, timeout=3) as sock:
                sock.sendall(b'POST /downloads/bot-a HTTP/1.1\r\nHost: fixture\r\nAuthorization: Bearer '
                             + CRED_A.encode() + b'\r\nContent-Type: application/json\r\nContent-Length: 2\r\n'
                             + duplicate + b'\r\n{}')
                result = http.client.HTTPResponse(sock)
                result.begin()
                self.assertEqual(result.status, expected)
                result.read()
        self.upstream.assert_not_called()


if __name__ == '__main__':
    unittest.main()
