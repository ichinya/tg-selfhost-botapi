import unittest

from migration_contract import Outcome
from migration_preflight import protocol_probe, readiness


class PreflightTests(unittest.TestCase):
    def test_probe_requires_token_free_bot_api_shaped_response(self):
        body = b'{"ok":false,"error_code":404,"description":"ignored"}'
        self.assertTrue(protocol_probe(404, 'application/json; charset=utf-8', body))
        for status, content_type, candidate in ((200, 'application/json', body),
                                               (404, 'text/html', body),
                                               (404, 'application/json', b'{}'),
                                               (404, 'application/json', b'{')):
            self.assertFalse(protocol_probe(status, content_type, candidate))

    def test_protocol_alone_does_not_authorize_mutation(self):
        evidence = dict(protocol_ok=True, deployment_verified=True,
                        credentials_ready=True, state_ready=True)
        self.assertEqual(readiness(**evidence), Outcome.CONFIRMED)
        for name in evidence:
            self.assertEqual(readiness(**{**evidence, name: False}), Outcome.BLOCKED)
        with self.assertRaises(ValueError):
            readiness(**{**evidence, 'deployment_verified': 1})
