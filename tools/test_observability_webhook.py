import unittest
from observability.webhook import project, category


class WebhookTests(unittest.TestCase):
    def test_allowlist_and_historical_error(self):
        data = project('public', dict(ok=True, result=dict(url='https://SECRET.invalid/token', pending_update_count=0,
                       last_error_date=1, last_error_message='timeout SECRET', ip_address='private')))
        self.assertEqual(data['pending_update_count'], 0)
        self.assertEqual(data['state'], 'last_error_recorded')
        self.assertEqual(data['delivery_evidence'], 'not_observed')
        self.assertNotIn('SECRET', repr(data))
        self.assertEqual(project('public', dict(ok=True, result=dict(url='', pending_update_count=2)))['mode'], 'polling')

    def test_invalid_types_and_categories(self):
        for value in [True, -1, None]:
            with self.assertRaises(ValueError): project('a', dict(ok=True, result=dict(url='', pending_update_count=value)))
        for message, expected in [('TLS certificate', 'tls'), ('HTTP 401', 'http_4xx'), ('HTTP 502', 'http_5xx'), ('connection refused', 'connect')]:
            self.assertEqual(category(message), expected)
