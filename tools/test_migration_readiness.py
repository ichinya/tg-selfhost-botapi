"""Offline tests for the target probe response contract."""
import unittest
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
