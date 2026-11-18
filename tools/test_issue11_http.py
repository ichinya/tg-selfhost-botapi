"""Offline acceptance of the public Bash CLI, independent of untracked backends."""
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import unittest
import sys
import http.client
from urllib.request import Request, ProxyHandler, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parent))
from issue10_test_support import bash_binary

from issue11_http_mock import CURL_WRAPPER, METHODS, MUTATIONS, MockAPI, StalledTLS, TOKEN, WEBHOOK

SCRIPT = Path(__file__).resolve().parents[1] / 'migrate_off_to_self.sh'
REAL_CURL = shutil.which('curl')




class StatefulFixtureContract(unittest.TestCase):
    """Verify fixture effects actually precede response loss; no Bash acceptance claim."""

    def test_remote_effect_precedes_disconnection(self):
        mock = MockAPI()
        self.addCleanup(mock.close)
        mock.target, mock.scenario = ('target', 'setWebhook'), 'lost'
        request = Request(mock.target_url + '/bot' + TOKEN + '/setWebhook',
                          data=('url=' + WEBHOOK + '&drop_pending_updates=true').encode())
        with self.assertRaises(http.client.RemoteDisconnected):
            build_opener(ProxyHandler({})).open(request, timeout=3)
        self.assertEqual(mock.effects, [('target', 'setWebhook')])
        self.assertEqual(mock.target_webhook, WEBHOOK)
        self.assertEqual(mock.drop_count, 1)
        self.assertEqual(mock.pending_updates, [])


class NativeDiagnosticFilters(unittest.TestCase):
    """Run the actual shipped jq programs even when Bash cannot run locally."""

    def setUp(self):
        self.jq = shutil.which('jq')
        if not self.jq:
            self.fail('jq is required for diagnostic filter verification')
        self.source = (SCRIPT.parent/'tools/migration_diagnostics_main.sh').read_text(encoding='utf-8')

    def sanitize(self, value):
        start = self.source.index('  jq -Rs --rawfile secrets "$API_TMP/.raw-secrets"')
        start = self.source.index("'\n", start) + 2
        end = self.source.index('\n  \' "$input"', start)
        program = self.source[start:end]
        secrets = TOKEN + '\0' + WEBHOOK + '\0test-configuration-secret\0'
        # JSON transports the NUL-delimited secret list without argv NUL bytes.
        program = '($secrets_json|fromjson) as $secrets | false as $authority_preview | ' + program
        result = subprocess.run([self.jq, '-Rs', '--arg', 'secrets_json', json.dumps(secrets), program],
                                input=value, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_decoded_json_and_malformed_text_redact_all_secret_forms(self):
        forms = [TOKEN, TOKEN.replace(':', '%3a'), ''.join('%%%02X' % ord(c) for c in TOKEN),
                 ''.join('\\u%04x' % ord(c) for c in TOKEN), WEBHOOK, 'test-configuration-secret']
        text = 'useful ' + ' '.join(forms) + '\x1b[31m\r\n'
        for value in (text, json.dumps({'ok': False, 'description': text})):
            with self.subTest(json=value.startswith('{')):
                safe = self.sanitize(value)
                for secret in forms:
                    self.assertNotIn(secret, safe)
                self.assertNotIn('\x1b', safe)
                self.assertNotIn('\r', safe)
                self.assertIn('useful', safe)

    def test_receipt_preserves_typed_independent_channels(self):
        marker = '--rawfile safe_body "$REQUEST_DIR/body.txt" \'\n'
        start = self.source.index(marker) + len(marker)
        end = self.source.index('\n    \' > "$REQUEST_DIR/.$phase.tmp"', start)
        program = self.source[start:end]
        body = '{"ok":false,"error_code":401,"description":"safe reason","parameters":{"retry_after":7}}'
        args = [self.jq, '-n']
        for name, value in dict(phase='receipt', operation='run.test', step='identity', attempt='request-1.test',
                                method='getMe', role='source', verb='GET', started='2026-11-08T00:00:00Z',
                                finished='2026-11-08T00:00:01Z', bot='', code='400', outcome='CONFIRMED_REJECTION',
                                reason='api_rejected', parse='valid', schema='valid', last='').items():
            args.extend(['--arg', name, value])
        for name, value in dict(elapsed=1, curl_exit=0, mutating=False, effect=True, connect=5,
                                deadline=30, drop=False, observations=['http_error', 'api_error']).items():
            args.extend(['--argjson', name, json.dumps(value)])
        args.extend(['--arg', 'safe_body', body, program])
        result = subprocess.run(args, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads(result.stdout)
        self.assertEqual((record['http_status'], record['api_error_code'], record['curl_exit_code']), (400, 401, 0))
        self.assertIsNone(record['description'])
        self.assertEqual(record['retry_after'], 7)
        self.assertEqual(record['observations'], ['http_error', 'api_error'])
        self.assertEqual(record['outcome'], 'CONFIRMED_REJECTION')

    def test_observations_preserve_simultaneous_failures(self):
        marker = '--rawfile text "$REQUEST_DIR/.raw-body" \'\n'
        start = self.source.index(marker) + len(marker)
        end = self.source.index('\n    2>/dev/null)', start)
        program = self.source[start:end].rstrip()[:-1]
        cases = [(0, '400', 'valid', 'valid', '{"ok":false}', ['http_error', 'api_error']),
                 (28, '200', 'valid', 'valid', '{"ok":true}', ['transport_error']),
                 (0, '200', 'valid', 'invalid', '42', ['invalid_schema']),
                 (6, '', 'invalid_json', 'invalid', '', ['transport_error', 'invalid_json', 'invalid_schema'])]
        for rc, code, parse, schema, text, expected in cases:
            with self.subTest(rc=rc, code=code):
                args = [self.jq, '-n', '--argjson', 'rc', str(rc)]
                for name, value in dict(code=code, parse=parse, schema=schema, method='getMe', text=text).items():
                    args.extend(['--arg', name, value])
                result = subprocess.run(args + [program], capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), expected)


if __name__ == '__main__':
    unittest.main()
