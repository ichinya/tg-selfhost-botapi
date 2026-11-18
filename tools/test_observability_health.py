import time
import unittest
from unittest.mock import patch
from observability.probes import root_response, target
from observability.server import Collector


class HealthTests(unittest.TestCase):
    def test_contract_shared_with_doctor(self):
        from doctor_checks import root_response as doctor
        for status, mime, body in [(404, 'application/json', b'{"ok":false,"error_code":404}'),
             (404, 'application/json', b'{"ok":false,"error_code":true}'), (404, 'text/html', b'404'),
             (302, 'application/json', b'{"ok":false,"error_code":404}'), (404, 'application/json', b'{')]:
            self.assertEqual(root_response(status, mime, body), doctor(status, mime, body))

    @patch('observability.probes.probe', return_value=True)
    def test_expiry_failure_recovery_stats_depth(self, probe):
        c = Collector()
        self.assertFalse(c.snapshot()['process']['ready'])
        c.collect(); self.assertTrue(c.snapshot()['process']['ready'])
        self.assertFalse(c.snapshot(time.monotonic()+16)['process']['live'])
        probe.return_value = False
        c.collect(); self.assertFalse(c.snapshot()['process']['ready'])
        probe.return_value = True
        c.collect(); self.assertTrue(c.snapshot()['process']['live'])
        c = Collector(stats_enabled=True)
        with patch('observability.stats.fetch', side_effect=ValueError('Closing')): c.collect()
        self.assertTrue(c.snapshot()['process']['live'])
        self.assertFalse(c.snapshot()['process']['ready'])

    def test_target_normalization(self):
        self.assertEqual(target('::', '8081'), ('::1', 8081))
        self.assertEqual(target('0.0.0.0'), ('127.0.0.1', 8081))
        for host, port in [('example.com', 8081), ('127.0.0.1', True), ('127.0.0.1', '0')]:
            with self.assertRaises(ValueError): target(host, port)
