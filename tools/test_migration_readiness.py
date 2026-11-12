"""Offline tests for the target probe response contract."""
import unittest
from unittest import mock
from migration_probe import DockerEvidence
from migration_readiness import is_ready, target_base


class ReadinessTests(unittest.TestCase):
    def test_probe_response(self):
        self.assertTrue(is_ready(404, "application/json; charset=utf-8", b'{"ok":false,"error_code":404,"description":"anything"}'))
        for status, content_type, body in [(200, "application/json", b'{"ok":false,"error_code":404}'), (404, "text/html", b"not found"), (502, "application/json", b'{"ok":false,"error_code":404}'), (404, "application/json", b'{"ok":false,"error_code":true}')]:
            self.assertFalse(is_ready(status, content_type, body))

    def test_endpoint(self):
        self.assertEqual(target_base("https://example.invalid/proxy"), "https://example.invalid/proxy/")
        for endpoint in ("https://user:pass@example.invalid", "https://example.invalid/?token=x", "https://example.invalid/#x", "https://example.invalid/../x"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                target_base(endpoint)


class DockerInspectTests(unittest.TestCase):
    def test_process_identity_and_probe_groups(self):
        adapter = DockerEvidence('fixture', 'http://localhost', 'image', b'0' * 32)
        raw = ('/usr/local/bin/telegram-bot-api\nUid: 1000 1000 1000 1000\n'
               'Gid: 2000 2000 2000 2000\nGroups: 2000 3000\n\nBOTAPI_STAT\n'
               '1 (telegram-bot-api) ' + '0 '*19 + '123\nBOTAPI_ARGV\n'
               '/usr/local/bin/telegram-bot-api\x00--dir=/state\x00')
        with mock.patch.object(adapter, 'run', return_value=raw):
            process = adapter.process()
        self.assertEqual(process[:3], (1000, 2000, (2000, 3000)))
        with mock.patch.object(adapter, 'run', return_value='1000\n2000\n2000 3000\n'):
            self.assertEqual(adapter.probe_user(process), [])
        with mock.patch.object(adapter, 'run', return_value='1000\n2000\n2000\n'):
            with self.assertRaisesRegex(ValueError, 'supplementary_groups_mismatch'):
                adapter.probe_user(process)
        with mock.patch.object(adapter, 'run', side_effect=['0\n0\n0\n', '1000\n2000\n2000 3000\n']):
            self.assertEqual(adapter.probe_user(process), ['--user', '1000:2000'])
        with mock.patch.object(adapter, 'run', side_effect=['0\n0\n0\n', '1000\n2001\n2001 3000\n']):
            with self.assertRaises(ValueError):
                adapter.probe_user(process)
        for invalid in (raw.replace('1000 1000 1000 1000', '1000 101 1000 1000'),
                        raw.replace('/usr/local/bin/telegram-bot-api\n', '/bin/sh\n'),
                        raw.replace('Groups: 2000 3000', 'Groups: bad')):
            with mock.patch.object(adapter, 'run', return_value=invalid), self.assertRaises(ValueError):
                adapter.process()

    def test_empty_and_malformed_container_and_image_inspects_fail_closed(self):
        adapter = DockerEvidence('fixture', 'http://localhost', 'image', b'0' * 32)
        for args in (('inspect', 'fixture'), ('image', 'inspect', 'image')):
            for value in ('[]', '{}', '[null]', '[{}, {}]'):
                with self.subTest(args=args, value=value), mock.patch.object(adapter, 'run', return_value=value), self.assertRaises(ValueError):
                    adapter.inspect(*args)
