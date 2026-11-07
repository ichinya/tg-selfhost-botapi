import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time
import unittest
from unittest.mock import MagicMock, patch
from tools import file_contract as contract

TOKEN = '12345:SYNTHETIC_A'


def binding(**changes):
    values = dict(token=TOKEN, endpoint='http://botapi:8081', media_root='/srv/media',
                  bot_root='/srv/media/' + TOKEN)
    values.update(changes)
    return contract.Binding(**values)


class ContractTests(unittest.TestCase):
    def test_absolute_upstream_deadline_stops_a_slow_drip(self):
        class Slow(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_POST(self):
                self.send_response(200)
                self.send_header('Content-Length', '1000')
                self.end_headers()
                try:
                    for _ in range(100):
                        self.wfile.write(b'x')
                        self.wfile.flush()
                        time.sleep(0.03)
                except OSError:
                    pass
        service = ThreadingHTTPServer(('127.0.0.1', 0), Slow)
        worker = threading.Thread(target=service.serve_forever, daemon=True)
        worker.start()
        try:
            endpoint = 'http://127.0.0.1:' + str(service.server_port)
            start = time.monotonic()
            with patch.object(contract, 'UPSTREAM_READ_TIMEOUT', 0.12):
                with self.assertRaises(contract.UpstreamTimeout):
                    contract.get_file(binding(endpoint=endpoint), 'fixture')
            self.assertLess(time.monotonic() - start, 1.0)
        finally:
            service.shutdown()
            service.server_close()
            worker.join(2)

    def test_token_dc_and_colon_binding_is_exact(self):
        binding()
        self.assertEqual(contract.bot_suffix(TOKEN, True, False), '12345~SYNTHETIC_A~T')
        for change in (dict(token='12345:SYNTHETIC_B'), dict(test_dc=True), dict(colon=False),
                       dict(bot_root='/srv/media/12345'), dict(bot_root='/srv/media-other/' + TOKEN),
                       dict(media_root='/var/lib/telegram-bot-api/media'),
                       dict(endpoint='https://api.telegram.org'), dict(endpoint='http://a@botapi/'),
                       dict(endpoint='http://botapi/redirect'), dict(private_roots=('/srv',))):
            with self.subTest(change=change), self.assertRaises(contract.ContractError):
                binding(**change)
        self.assertNotIn(TOKEN, repr(binding()))

    def test_file_id_and_duplicate_json_keys(self):
        for value in (None, '', 'x' * 1025, 'line\nbreak', 2, '\ud800'):
            with self.assertRaises(contract.ContractError):
                contract.file_id_value(value)
        with self.assertRaises(contract.ContractError):
            json.loads('{"file_id":"a","file_id":"b"}', object_pairs_hook=contract.unique_object)

    def test_upstream_has_no_redirect_proxy_or_raw_error(self):
        connection = MagicMock()
        response = connection.getresponse.return_value
        response.status = 200
        response.read.return_value = b'{"ok":true,"result":{"file_path":"/srv/media/fixture"}}'
        with patch.object(contract.http.client, 'HTTPConnection', return_value=connection):
            self.assertEqual(contract.get_file(binding(), 'id'), '/srv/media/fixture')
            args = connection.request.call_args.args
            self.assertEqual(args[0:2], ('POST', '/bot' + TOKEN + '/getFile'))
            self.assertEqual(json.loads(args[2]), {'file_id': 'id'})
            response.status = 302
            response.read.return_value = b'RAW_PRIVATE_ERROR'
            with self.assertRaises(contract.UpstreamError) as error:
                contract.get_file(binding(), 'id')
            self.assertNotIn('RAW_PRIVATE_ERROR', str(error.exception))
        connection.close.assert_called()

    def test_malformed_and_oversized_upstream_fail(self):
        for data in (b'[]', b'{"ok":true,"result":{"file_path":1}}', b'x' * 16385,
                     b'{"ok":false,"description":"secret"}', b'{"ok":true,"ok":true}'):
            conn = MagicMock()
            conn.getresponse.return_value.status = 200
            conn.getresponse.return_value.read.return_value = data
            with patch.object(contract.http.client, 'HTTPConnection', return_value=conn):
                with self.assertRaises(contract.UpstreamError):
                    contract.get_file(binding(), 'id')


if __name__ == '__main__':
    unittest.main()
