import unittest
from datetime import datetime, timezone

from migration_contract import Outcome
from migration_transport import classify_failure, classify_response


class TransportClassificationTests(unittest.TestCase):
    def test_ambiguous_mutations_never_become_retryable_failures(self):
        for status, body in ((302, b''), (500, b'{}'), (200, b'not-json'),
                             (200, b'{"ok":true' ), (400, b'{}')):
            with self.subTest(status=status, body=body):
                self.assertEqual(classify_response(status, body, mutation=True).outcome,
                                 Outcome.UNKNOWN)
        self.assertEqual(classify_failure(mutation=True, sent_possible=True).outcome,
                         Outcome.UNKNOWN)
        self.assertEqual(classify_failure(mutation=True, sent_possible=False).outcome,
                         Outcome.FAILED)

    def test_api_rejection_rate_limit_and_redaction(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        limited = classify_response(429, b'{"ok":false,"error_code":429,"description":"secret-canary","parameters":{"retry_after":10}}', mutation=True, now=now)
        self.assertEqual(limited.outcome, Outcome.WAITING)
        self.assertEqual((limited.not_before - now).total_seconds(), 10)
        self.assertNotIn('secret-canary', repr(limited))
        rejected = classify_response(400, b'{"ok":false,"error_code":400,"description":"secret-canary"}', mutation=True)
        self.assertEqual(rejected.outcome, Outcome.FAILED)
        self.assertNotIn('secret-canary', repr(rejected))
        self.assertEqual(classify_response(429, b'{"ok":false,"error_code":429}', mutation=True).outcome,
                         Outcome.UNKNOWN)

    def test_consistent_success_only(self):
        self.assertEqual(classify_response(200, b'{"ok":true,"result":{}}', mutation=True).outcome,
                         Outcome.CONFIRMED)
        self.assertEqual(classify_response(400, b'{"ok":true}', mutation=True).outcome,
                         Outcome.UNKNOWN)
