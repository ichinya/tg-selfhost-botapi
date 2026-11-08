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


class MigrationRequestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.name != 'posix':
            raise unittest.SkipTest('POSIX transport acceptance: NOTRUN on Windows; verification deferred to CI/gates')
        for tool in ('bash', 'curl', 'jq', 'stat', 'python3'):
            if not shutil.which(tool):
                raise RuntimeError(tool + ' is required for Linux acceptance (no silent skip)')

    def test_bash_syntax(self):
        result = subprocess.run([bash_binary(), '-n', str(self.script)], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.work = self.root / 'work'
        self.work.mkdir()
        self.script = self.work / 'helper.sh'
        shutil.copyfile(SCRIPT, self.script)
        self.cwd = self.root / 'caller'
        self.cwd.mkdir()
        self.home = self.root / 'home'
        self.home.mkdir()
        self.sequence = 0
        self.mock = MockAPI(self.root / 'remote-state.json')
        self.addCleanup(self.mock.close)
        (self.bin / 'curl').write_text(CURL_WRAPPER)
        (self.bin / 'curl').chmod(0o700)

    def environment(self, **extra):
        # Do not inherit credentials, proxy settings, curl homes or timeout values.
        env = dict(PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                   HOME=str(self.home), LANG='C.UTF-8', LC_ALL='C.UTF-8',
                   REAL_CURL=REAL_CURL, SOURCE_URL=self.mock.source_url, OFFICIAL_BOT_URL=self.mock.source_url,
                   TARGET_URL=self.mock.target_url, SELF_URL=self.mock.target_url,
                   ARGLOG=str(self.root / 'args'), MIGRATION_CONNECT_TIMEOUT='1',
                   MIGRATION_REQUEST_DEADLINE='1', NO_PROXY='*', no_proxy='*')
        env.update(extra)
        return env

    def run_script(self, confirmation='y\n', third=None, fallback=False, **extra):
        env = self.environment(**extra)
        args = [bash_binary(), str(self.script), TOKEN]
        if fallback:
            env['SELF_BOT_URL'] = self.mock.target_url
            if third is not None:
                env['WEBHOOK_URL'] = third
        else:
            args.append(self.mock.target_url)
            if third is not None:
                args.append(third)
        return subprocess.run(args, input=confirmation, text=True, capture_output=True,
                              cwd=self.cwd, env=env, timeout=15)

    def run_directory(self):
        run, = (self.work / 'logs/migration').glob('run.*')
        return run

    def attempt_directory(self, number):
        path, = self.run_directory().glob('request-%d.*' % number)
        return path

    def records(self):
        run = self.run_directory()
        for path in run.rglob('*'):
            if path.is_file():
                content = path.read_text()
                for secret in (TOKEN, WEBHOOK, 'test-configuration-secret'):
                    self.assertNotIn(secret, content, str(path))
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            else:
                self.assertEqual(path.stat().st_mode & 0o777, 0o700)
        self.assertEqual(run.stat().st_mode & 0o777, 0o700)
        self.assertFalse(list(run.rglob('.raw-*')))
        records = [json.loads(p.read_text()) for p in run.glob('*/receipt.json')]
        required = {'schema_version', 'operation_id', 'step_id', 'attempt_id', 'method',
                    'endpoint_role', 'endpoint_identifier', 'bot_id', 'mutating',
                    'session_effect_possible', 'started_at', 'finished_at', 'connect_timeout',
                    'request_deadline', 'http_status', 'curl_exit_code', 'api_error_code',
                    'description', 'retry_after', 'response_complete',
                    'outcome', 'reason', 'body', 'transport_stderr', 'parse_status', 'duration',
                    'retry_after_status'}
        for record in records:
            self.assertLessEqual(required, record.keys())
            self.assertEqual(record['schema_version'], 1)
            self.assertEqual(record['operation_id'], run.name)
            self.assertTrue((run / record['body']).is_file())
            self.assertTrue((run / record['transport_stderr']).is_file())
        return records

    def record(self, method, role=None):
        return next(r for r in self.records() if r['method'] == method and
                    (role is None or r['endpoint_role'] == role))

    def summary(self):
        return json.loads((self.run_directory() / 'summary.json').read_text())

    def reset_run(self):
        self.sequence += 1
        self.work = self.root / ('work-%d' % self.sequence)
        self.work.mkdir()
        self.script = self.work / 'helper.sh'
        shutil.copyfile(SCRIPT, self.script)
        self.mock.calls.clear()
        self.mock.effects.clear()
        self.mock.entered.clear()
        self.mock.release.clear()
        self.mock.persist()

    def assert_stopped(self, method):
        self.assertFalse(any(role == 'sink' for role, _ in self.mock.calls))
        self.assertEqual(sum(m == method for _, m in self.mock.calls), 1)
        if method == 'deleteWebhook':
            self.assertNotIn(('source', 'logOut'), self.mock.calls)
        if method in ('deleteWebhook', 'logOut'):
            self.assertNotIn(('target', 'setWebhook'), self.mock.calls)
            self.assertNotIn(('target', 'getMe'), self.mock.calls)

    def test_success_webhook_and_schema(self):
        result = self.run_script(third=WEBHOOK)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Webhook OK', result.stdout)
        self.assertNotIn(TOKEN, result.stdout + result.stderr)
        self.assertNotIn(WEBHOOK, result.stdout + result.stderr)
        self.assertEqual([m for _, m in self.mock.calls],
                         ['probe', 'getMe', 'getWebhookInfo', 'deleteWebhook',
                          'logOut', 'getMe', 'setWebhook', 'getWebhookInfo'])
        self.assertEqual(len(self.records()), 8)
        summary = self.summary()
        self.assertTrue(summary['completed'])
        self.assertFalse(summary['continuation_requires_reconciliation'])
        intent = json.loads((self.attempt_directory(1) / 'intent.json').read_text())
        self.assertIsNone(intent['bot_id'])
        self.assertIsNone(intent['finished_at'])
        self.assertFalse(intent['effect_possible'])

    def test_polling_and_operator_cancel(self):
        self.mock.webhook = False
        result = self.run_script(fallback=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('DONE polling mode', result.stdout)
        self.assertNotIn(('target', 'setWebhook'), self.mock.calls)
        self.reset_run()
        result = self.run_script(confirmation='n\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.mock.effects)
        self.assertEqual(self.mock.calls, [('target', 'probe')])

    def test_http_errors_for_each_mutation(self):
        for method in MUTATIONS:
            for code in (400, 429, 500):
                with self.subTest(method=method, code=code):
                    role = 'target' if method == 'setWebhook' else 'source'
                    self.mock.scenario, self.mock.target = 'http%d' % code, (role, method)
                    result = self.run_script()
                    self.assertEqual(result.returncode, 3 if code == 500 else 1, result.stderr)
                    self.assertNotIn('DONE', result.stdout)
                    self.assertNotIn(TOKEN, result.stdout + result.stderr)
                    self.assertNotIn('\x1b', result.stderr)
                    self.assertIn('useful diagnostic', result.stderr)
                    record = self.record(method)
                    self.assertEqual(record['http_status'], code)
                    self.assertEqual(record['curl_exit_code'], 0)
                    self.assertEqual(record['api_error_code'], code)
                    self.assertEqual(record['retry_after'], 7)
                    self.assertTrue(record['response_complete'])
                    self.assertEqual(record['parse_status'], 'valid')
                    self.assertEqual(record['schema_status'], 'valid')
                    self.assertIn('http_error', record['observations'])
                    self.assertIn('api_error', record['observations'])
                    self.assert_stopped(method)
                    self.reset_run()

    def test_http_and_api_codes_are_independent(self):
        self.mock.scenario = 'http400'
        self.mock.different_code = True
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stderr)
        record = self.record('deleteWebhook')
        self.assertEqual((record['http_status'], record['api_error_code']), (400, 401))
        self.assertEqual(record['outcome'], 'CONFIRMED_REJECTION')

    def test_http400_identity_retains_the_regression_description(self):
        self.mock.target, self.mock.scenario = ('source', 'getMe'), 'http400'
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('useful diagnostic', result.stderr)
        self.assertIn('error_code=400', result.stderr)
        self.assertNotIn(TOKEN, result.stdout + result.stderr)
        receipt = self.record('getMe', 'source')
        self.assertEqual(receipt['http_status'], 400)
        self.assertEqual(receipt['curl_exit_code'], 0)
        self.assertIn('useful diagnostic', (self.run_directory() / receipt['body']).read_text())
        self.assertFalse(self.mock.effects)

    def test_retry_after_validation(self):
        self.mock.scenario = 'http429'
        for retry in (0, 7, 'absent', None, '7', -1, 1.5, True, {}, 10 ** 100):
            with self.subTest(retry=retry):
                self.mock.retry = retry
                result = self.run_script()
                self.assertEqual(result.returncode, 1 if type(retry) is int and retry in (0, 7) or retry == 'absent' else 3, result.stderr)
                record = self.record('deleteWebhook')
                valid = type(retry) is int and retry in (0, 7)
                self.assertEqual(record['reason'], 'rate_limited' if valid or retry == 'absent' else 'invalid_response')
                self.assertEqual(record['retry_after_status'], 'valid' if valid else
                                 'absent' if retry == 'absent' else 'invalid')
                self.assertEqual(record['outcome'], 'CONFIRMED_REJECTION' if valid or retry == 'absent' else 'UNKNOWN')
                if not valid:
                    self.assertIsNone(record['retry_after'])
                self.assert_stopped('deleteWebhook')
                self.reset_run()

    def test_invalid_or_contradictory_responses_are_unknown(self):
        for scenario in ('malformed', 'empty', 'array', 'scalar', 'null', 'multiple', 'string_ok', 'missing_ok',
                         'bad_result', 'false200', 'contradictory', 'missing_description', 'html500', 'redirect'):
            with self.subTest(scenario=scenario):
                self.mock.scenario = scenario
                result = self.run_script()
                self.assertEqual(result.returncode, 3, result.stderr)
                self.assertEqual(self.record('deleteWebhook')['outcome'], 'UNKNOWN')
                self.assert_stopped('deleteWebhook')
                self.assertTrue(self.summary()['continuation_requires_reconciliation'])
                self.reset_run()

    def test_rejection_requires_numeric_error_code(self):
        self.mock.scenario, self.mock.invalid_error_code = 'http400', True
        result = self.run_script()
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIsNone(self.record('deleteWebhook')['api_error_code'])

    def test_method_specific_identity_and_webhook_results(self):
        for method, body in [('getMe', '{"ok":true,"result":{"id":"123"}}'),
                             ('getWebhookInfo', '{"ok":true,"result":{"url":false}}')]:
            with self.subTest(method=method):
                result = self.run_script(FAKE_METHOD='source:' + method, FAKE_EXIT='0',
                                         FAKE_STATUS='200', FAKE_BODY=body)
                self.assertEqual(result.returncode, 3, result.stderr)
                record = self.record(method, 'source')
                self.assertEqual(record['outcome'], 'UNKNOWN')
                self.assertEqual(record['parse_status'], 'valid')
                self.assertEqual(record['schema_status'], 'invalid')
                self.assertIn('invalid_schema', record['observations'])
                self.assertFalse(self.mock.effects)
                self.reset_run()

    def test_complete_rejection_with_http_200_is_a_failure(self):
        self.mock.scenario = 'rejection200'
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stderr)
        record = self.record('deleteWebhook')
        self.assertEqual(record['http_status'], 200)
        self.assertEqual(record['api_error_code'], 401)
        self.assertEqual(record['description'], 'useful rejection')
        self.assertEqual(record['outcome'], 'CONFIRMED_REJECTION')
        self.assert_stopped('deleteWebhook')

    def test_observation_failure_stops_before_mutation(self):
        self.mock.target, self.mock.scenario = ('source', 'getWebhookInfo'), 'malformed'
        result = self.run_script()
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertFalse(self.mock.effects)
        self.assertEqual(self.record('getWebhookInfo')['outcome'], 'UNKNOWN')

    def test_ambiguous_getme_stops_with_session_effect(self):
        for role in ('source', 'target'):
            with self.subTest(role=role):
                self.mock.target, self.mock.scenario = (role, 'getMe'), 'malformed'
                result = self.run_script()
                self.assertEqual(result.returncode, 3, result.stderr)
                self.assertEqual(self.mock.calls.count((role, 'getMe')), 1)
                record = self.record('getMe', role)
                self.assertTrue(record['session_effect_possible'])
                self.assertFalse(record['mutating'])
                self.assertEqual(record['outcome'], 'UNKNOWN')
                if role == 'source':
                    self.assertFalse(self.mock.effects)
                else:
                    self.assertIn(('source', 'logOut'), self.mock.effects)
                self.reset_run()

    def test_probe_and_redirect_do_not_send_token(self):
        result = self.run_script(confirmation='n\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.record('probe')['outcome'], 'CONFIRMED_SUCCESS')
        self.assertFalse(self.record('probe')['effect_possible'])
        self.assertEqual(self.mock.calls, [('target', 'probe')])
        self.reset_run()
        self.mock.target, self.mock.scenario = ('target', 'probe'), 'redirect'
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(self.mock.calls, [('target', 'probe')])
        self.assertFalse(any(role == 'sink' for role, _ in self.mock.calls))

    def test_consent_preview_shows_authority_and_hides_secret_path(self):
        hook = 'https://example.invalid/' + TOKEN + '?secret=test-configuration-secret'
        result = self.run_script(confirmation='n\n', third=hook)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Source: "' + self.mock.source_url + '"', result.stdout)
        self.assertIn('Target: "' + self.mock.target_url + '"', result.stdout)
        self.assertIn('Webhook: "https://example.invalid"', result.stdout)
        for value in (TOKEN, 'test-configuration-secret', '?secret='):
            self.assertNotIn(value, result.stdout + result.stderr)
        self.assertEqual(self.mock.calls, [('target', 'probe')])

    def test_ambiguous_target_identity_after_logout_marks_partial_migration(self):
        self.mock.target, self.mock.scenario = ('target', 'getMe'), 'malformed'
        self.mock.occurrence = 1
        result = self.run_script()
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn(('source', 'logOut'), self.mock.effects)
        self.assertNotIn(('target', 'setWebhook'), self.mock.calls)
        self.assertEqual(self.mock.calls.count(('target', 'getMe')), 1)
        self.assertTrue(self.summary()['partial_migration'])
        self.assertTrue(self.summary()['continuation_requires_reconciliation'])

    def test_loss_with_and_without_effect_remains_unknown(self):
        for scenario in ('lost', 'lost_no_effect', 'delayed', 'partial'):
            for method in MUTATIONS:
                with self.subTest(scenario=scenario, method=method):
                    role = 'target' if method == 'setWebhook' else 'source'
                    self.mock.target, self.mock.scenario = (role, method), scenario
                    result = self.run_script()
                    self.assertEqual(result.returncode, 3, result.stderr)
                    self.assertEqual(self.mock.effects.count((role, method)), int(scenario != 'lost_no_effect'))
                    remote = json.loads(self.mock.state_path.read_text())
                    self.assertEqual(remote['effects'].count([role, method]), int(scenario != 'lost_no_effect'))
                    self.assertEqual(self.record(method)['outcome'], 'UNKNOWN')
                    self.assert_stopped(method)
                    self.reset_run()

    def test_lost_setwebhook_does_not_drop_new_updates_on_restart(self):
        self.mock.target, self.mock.scenario = ('target', 'setWebhook'), 'lost'
        result = self.run_script(DROP_PENDING_UPDATES='true')
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(self.mock.drop_count, 1)
        self.assertEqual(self.mock.target_webhook, WEBHOOK)
        self.mock.pending_updates.append('new-after-loss')
        self.mock.persist()
        self.assert_restart_blocked()
        self.assertEqual(self.mock.drop_count, 1)
        self.assertEqual(self.mock.pending_updates, ['new-after-loss'])

    def test_confirmed_logout_survives_later_rejection(self):
        self.mock.target, self.mock.scenario = ('target', 'getMe'), 'http400'
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stderr)
        summary = self.summary()
        self.assertIn('logout', summary['confirmed_effects'])
        self.assertEqual(summary['last_confirmed_step'], 'logout')
        self.assertTrue(summary['partial_migration'])
        self.assertTrue(summary['continuation_requires_reconciliation'])
        self.assert_restart_blocked()

    def test_real_deadline_covers_delayed_headers_and_continuous_body(self):
        for scenario in ('delayed', 'slow', 'partial', 'headers_only'):
            with self.subTest(scenario=scenario):
                self.mock.scenario = scenario
                start = time.monotonic()
                result = self.run_script()
                self.assertEqual(result.returncode, 3, result.stderr)
                self.assertLess(time.monotonic() - start, 6)
                record = self.record('deleteWebhook')
                self.assertEqual(record['curl_exit_code'], 18 if scenario in ('partial', 'headers_only') else 28)
                self.assertFalse(record['response_complete'])
                if scenario != 'delayed':
                    self.assertEqual(record['http_status'], 200)
                    body = (self.run_directory() / record['body']).read_text()
                    self.assertEqual(bool(body), scenario != 'headers_only')
                self.assert_stopped('deleteWebhook')
                self.reset_run()

    def test_stalled_tls_connect_timeout_on_loopback(self):
        stalled = StalledTLS()
        self.addCleanup(stalled.close)
        start = time.monotonic()
        result = self.run_script(TARGET_URL='https://127.0.0.1:%d' % stalled.port,
                                 MIGRATION_REQUEST_DEADLINE='3')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertLess(time.monotonic() - start, 4)
        record = self.record('probe', 'target')
        self.assertEqual(record['curl_exit_code'], 28)
        self.assertIsNone(record['http_status'])
        self.assertFalse(self.mock.calls)

    def test_real_connection_refused(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        result = self.run_script(TARGET_URL='http://127.0.0.1:%d' % port)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(self.record('probe')['curl_exit_code'], 7)
        self.assertFalse(self.mock.calls)

    def test_fake_transport_preserves_status_body_and_stderr_independently(self):
        for code in ('6', '7', '28', '35', '60'):
            with self.subTest(code=code):
                result = self.run_script(FAKE_METHOD='source:getMe', FAKE_EXIT=code)
                self.assertEqual(result.returncode, 3, result.stderr)
                record = self.record('getMe')
                self.assertEqual(record['curl_exit_code'], int(code))
                self.assertIsNone(record['http_status'])
                self.assertEqual(record['reason'], 'transport_unknown')
                self.assertEqual(self.mock.calls, [('target', 'probe')])
                self.assertIn('transport failure', (self.run_directory() / record['transport_stderr']).read_text())
                self.reset_run()
        result = self.run_script(FAKE_METHOD='source:deleteWebhook', FAKE_EXIT='28',
                                 FAKE_STATUS='200', FAKE_BODY='{"ok":true,"result":true}\n\n')
        self.assertEqual(result.returncode, 3, result.stderr)
        record = self.record('deleteWebhook')
        self.assertEqual(record['http_status'], 200)
        self.assertFalse(record['response_complete'])
        self.assertEqual(record['outcome'], 'UNKNOWN')
        self.assertIn('transport_error', record['observations'])

    def test_malformed_body_and_secret_encodings(self):
        self.mock.scenario = 'secrets'
        result = self.run_script(API_HASH='test-configuration-secret')
        self.assertEqual(result.returncode, 3, result.stderr)
        record = self.record('deleteWebhook')
        body = (self.run_directory() / record['body']).read_text()
        self.assertIn('useful', body)
        self.assertNotIn('\x1b', body)
        self.assertNotIn('\r', body)
        self.assertNotIn('%3a', body)
        self.assertNotIn('\\u0031', body)
        self.assertNotIn(TOKEN, result.stdout + result.stderr)

    def test_large_body_is_not_console_preview(self):
        body = 'full-body-' + 'x' * 12000 + '\n\n'
        result = self.run_script(FAKE_METHOD='source:deleteWebhook', FAKE_EXIT='0',
                                 FAKE_STATUS='500', FAKE_BODY=body)
        self.assertEqual(result.returncode, 3, result.stderr)
        record = self.record('deleteWebhook')
        self.assertEqual(json.loads(chr(34) + (self.run_directory() / record['body']).read_text() + chr(34)), body)
        self.assertNotIn('full-body-', result.stdout + result.stderr)

    def test_curlrc_and_arguments(self):
        (self.home / '.curlrc').write_text('proxy = "http://127.0.0.1:1"\nretry = 9\nlocation\nverbose\n')
        result = self.run_script(CURL_HOME=str(self.home))
        self.assertEqual(result.returncode, 0, result.stderr)
        records = [json.loads(line) for line in (self.root / 'args').read_text().splitlines()]
        self.assertEqual(len(records), 8)
        for record in records:
            args = record['args']
            self.assertEqual(args[0], '-q')
            self.assertEqual(args[args.index('--retry') + 1], '0')
            self.assertEqual(args[args.index('--connect-timeout') + 1], '1')
            self.assertEqual(args[args.index('--max-time') + 1], '1')
            self.assertEqual(args[args.index('--write-out') + 1], '%{http_code}')
            for forbidden in ('--fail', '--fail-with-body', '-L', '--location', '-k'):
                self.assertNotIn(forbidden, args)
        self.assertEqual(self.mock.calls.count(('source', 'logOut')), 1)

    def test_wrapper_rejects_unknown_endpoints_before_network(self):
        for url in ('https://unexpected.invalid/bot' + TOKEN + '/getMe',
                    'https://api.telegram.org/botNON_SYNTHETIC_TOKEN/getMe',
                    self.mock.target_url + '/bot' + TOKEN + '/unknownMethod'):
            with self.subTest(url=url):
                result = subprocess.run([str(self.bin / 'curl'), '-q', '--retry', '0', url],
                                        env=self.environment(), text=True, capture_output=True, timeout=5)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('unexpected endpoint or token', result.stderr)
                self.assertFalse(self.mock.calls)

    def test_invalid_timeouts_before_network(self):
        for name in ('MIGRATION_CONNECT_TIMEOUT', 'MIGRATION_REQUEST_DEADLINE'):
            for value in ('', '0', '-1', '1.5', 'abc', '301', '999999999999999999999'):
                with self.subTest(name=name, value=value):
                    result = self.run_script(**{name: value})
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertFalse(self.mock.calls)
                    self.assertFalse((self.root / 'args').exists())

    def test_timeout_bounds_and_decimal_normalization(self):
        for connect, deadline, valid in (('1', '1', True), ('60', '300', True),
                                         ('0005', '0030', True), ('2', '1', False)):
            with self.subTest(connect=connect, deadline=deadline):
                result = self.run_script(confirmation='n\n', MIGRATION_CONNECT_TIMEOUT=connect,
                                         MIGRATION_REQUEST_DEADLINE=deadline)
                self.assertEqual(result.returncode, 0 if valid else 1, result.stderr)
                self.assertEqual(bool(self.mock.calls), valid)
                self.reset_run()

    def test_dotenv_precedence_and_defaults(self):
        settings = self.work / '.env'
        settings.write_text('MIGRATION_CONNECT_TIMEOUT=2\nMIGRATION_REQUEST_DEADLINE=3\n')
        result = self.run_script(confirmation='n\n', MIGRATION_CONNECT_TIMEOUT='invalid')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(self.mock.calls)
        self.assertFalse((self.work / 'logs').exists())
        env = self.environment()
        del env['MIGRATION_CONNECT_TIMEOUT'], env['MIGRATION_REQUEST_DEADLINE']
        result = subprocess.run([bash_binary(), str(self.script), TOKEN, self.mock.target_url], input='n\n',
                                text=True, capture_output=True, cwd=self.cwd, env=env, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.record('probe')['connect_timeout'], 2)
        self.assertEqual(self.record('probe')['request_deadline'], 3)
        self.reset_run()
        settings.unlink()
        result = subprocess.run([bash_binary(), str(self.script), TOKEN, self.mock.target_url], input='y\n',
                                text=True, capture_output=True, cwd=self.cwd, env=env, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.record('probe')['request_deadline'], 10)
        self.assertEqual(self.record('getMe', 'source')['connect_timeout'], 5)
        self.assertEqual(self.record('getMe', 'source')['request_deadline'], 30)

    def test_unsafe_existing_directories_are_not_modified(self):
        for mode in (0o755, 0o500):
            logs = self.work / 'logs'
            logs.mkdir(mode=mode)
            result = self.run_script()
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(logs.stat().st_mode & 0o777, mode)
            self.assertFalse(self.mock.calls)
            logs.chmod(0o700)
            logs.rmdir()
        (self.work / 'logs').symlink_to(self.root, target_is_directory=True)
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('symlink', result.stderr)
        self.assertFalse(self.mock.calls)

    def test_intent_and_receipt_write_failures(self):
        actual = shutil.which('mv')
        for phase, expected in (('intent', 1), ('receipt', 3)):
            with self.subTest(phase=phase):
                wrapper = self.bin / 'mv'
                wrapper.write_text('#!/usr/bin/env bash\nfor arg in "$@"; do\n'
                                   '  if [[ "$arg" == */request-4.*/.' + phase + '.tmp ]]; then exit 1; fi\n'
                                   'done\nexec "' + actual + '" "$@"\n')
                wrapper.chmod(0o700)
                result = self.run_script()
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual(self.mock.calls.count(('source', 'deleteWebhook')), int(phase == 'receipt'))
                self.assertNotIn(('source', 'logOut'), self.mock.calls)
                run = self.run_directory()
                self.assertEqual((self.attempt_directory(4) / 'intent.json').exists(), phase == 'receipt')
                self.assertFalse((self.attempt_directory(4) / 'receipt.json').exists())
                if phase == 'receipt':
                    self.assertTrue(list(run.rglob('.raw-body')))
                if phase == 'receipt':
                    self.assertTrue(self.summary()['continuation_requires_reconciliation'])
                    self.assert_restart_blocked()
                wrapper.unlink()
                self.reset_run()

    def assert_restart_blocked(self):
        calls = list(self.mock.calls)
        args = (self.root / 'args').read_text()
        result = self.run_script()
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn('reconciliation', result.stderr)
        self.assertEqual(self.mock.calls, calls)
        self.assertEqual((self.root / 'args').read_text(), args)
        self.assertNotIn('Preflight', result.stdout)

    def test_unknown_dossier_blocks_restart_before_preflight(self):
        self.mock.target, self.mock.scenario = ('source', 'logOut'), 'lost'
        result = self.run_script()
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(self.mock.effects.count(('source', 'logOut')), 1)
        self.assert_restart_blocked()

    def test_sanitization_failure_after_effect_retains_private_raw_and_stops(self):
        actual = shutil.which('jq')
        wrapper = self.bin / 'jq'
        wrapper.write_text('#!/usr/bin/env bash\n'
                           'if [[ "$*" == *"def clean_text"* && "$*" == *"/request-4."* ]]; then exit 1; fi\n'
                           'exec "' + actual + '" "$@"\n')
        wrapper.chmod(0o700)
        result = self.run_script()
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(self.mock.effects.count(('source', 'deleteWebhook')), 1)
        self.assertNotIn(('source', 'logOut'), self.mock.calls)
        self.assertNotIn(TOKEN, result.stdout + result.stderr)
        attempt = self.attempt_directory(4)
        self.assertTrue((attempt / '.raw-body').is_file())
        self.assertEqual((attempt / '.raw-body').stat().st_mode & 0o777, 0o600)
        self.assertFalse((attempt / 'receipt.json').exists())
        self.assertTrue(self.summary()['raw_capture_may_remain'])
        self.assert_restart_blocked()

    def test_summary_failure_after_effect_preserves_receipt_and_partial_run(self):
        actual = shutil.which('mv')
        wrapper = self.bin / 'mv'
        wrapper.write_text(f'''#!/usr/bin/env bash
for arg in "$@"; do
  if [[ "$arg" == */.summary.tmp ]] && jq -e '.confirmed_effects | index("delete_webhook") != null' "$arg" >/dev/null; then exit 1; fi
done
exec "{actual}" "$@"
''')
        wrapper.chmod(0o700)
        result = self.run_script()
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(self.mock.effects.count(('source', 'deleteWebhook')), 1)
        self.assertNotIn(('source', 'logOut'), self.mock.calls)
        record = self.record('deleteWebhook')
        self.assertEqual(record['outcome'], 'CONFIRMED_SUCCESS')
        self.assertTrue(self.summary()['partial_migration'])
        self.assertTrue(self.summary()['continuation_requires_reconciliation'])
        self.assert_restart_blocked()

    def test_foreign_receipt_cannot_resolve_current_attempt(self):
        self.mock.scenario = 'malformed'
        result = self.run_script()
        self.assertEqual(result.returncode, 3, result.stderr)
        run = self.run_directory()
        summary = self.summary()
        summary['continuation_requires_reconciliation'] = False
        (run / 'summary.json').write_text(json.dumps(summary))
        path = self.attempt_directory(4) / 'receipt.json'
        record = json.loads(path.read_text())
        record.update(operation_id='another-operation', outcome='CONFIRMED_SUCCESS')
        path.write_text(json.dumps(record))
        self.assert_restart_blocked()

    def test_confirmed_cancelled_run_allows_new_unique_dossier(self):
        result = self.run_script(confirmation='n\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        first = self.run_directory().name
        result = self.run_script(confirmation='n\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        runs = list((self.work / 'logs/migration').glob('run.*'))
        self.assertEqual(len(runs), 2)
        self.assertEqual(len({run.name for run in runs}), 2)
        self.assertTrue(any(run.name == first for run in runs))
        for run in runs:
            self.assertRegex(run.name, r'^run\.\d{8}T\d{6}Z\.\d+\.')

    def test_unfinished_non_effectful_probe_without_lock_allows_new_run(self):
        result = self.run_script(confirmation='n\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        run = self.run_directory()
        (self.attempt_directory(1) / 'receipt.json').unlink()
        summary = self.summary()
        summary['attempts'][0].update(receipt=None, outcome='in_flight')
        summary['continuation_requires_reconciliation'] = True
        (run / 'summary.json').write_text(json.dumps(summary))
        result = self.run_script(confirmation='n\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.mock.calls, [('target', 'probe'), ('target', 'probe')])

    def test_stale_lock_blocks_even_after_cancelled_probe(self):
        result = self.run_script(confirmation='n\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        (self.work / 'logs/migration/.lock').mkdir(mode=0o700)
        self.assert_restart_blocked()

    def test_missing_summary_does_not_hide_unfinished_effectful_intent(self):
        self.mock.scenario = 'lost'
        result = self.run_script()
        self.assertEqual(result.returncode, 3, result.stderr)
        (self.run_directory() / 'summary.json').unlink()
        (self.attempt_directory(4) / 'receipt.json').unlink()
        self.assert_restart_blocked()

    def test_lost_deletewebhook_does_not_drop_new_source_updates_on_restart(self):
        self.mock.scenario = 'lost'
        result = self.run_script(DROP_PENDING_UPDATES='true')
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(self.mock.source_drop_count, 1)
        self.mock.source_pending_updates.append('new-after-loss')
        self.mock.persist()
        self.assert_restart_blocked()
        self.assertEqual(self.mock.source_drop_count, 1)
        self.assertEqual(self.mock.source_pending_updates, ['new-after-loss'])

    def test_active_lock_blocks_parallel_request_before_network(self):
        self.mock.scenario = 'barrier'
        proc = subprocess.Popen([bash_binary(), str(self.script), TOKEN, self.mock.target_url],
                                cwd=self.cwd, env=self.environment(MIGRATION_REQUEST_DEADLINE='10'),
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, start_new_session=True)
        try:
            proc.stdin.write('y\n')
            proc.stdin.flush()
            self.assertTrue(self.mock.entered.wait(8))
            self.assert_restart_blocked()
        finally:
            self.mock.release.set()
            proc.communicate(timeout=5)

    def test_interruptions_keep_intent_without_retry(self):
        for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
            with self.subTest(signal=signum):
                self.mock.scenario = 'barrier'
                proc = subprocess.Popen([bash_binary(), str(self.script), TOKEN, self.mock.target_url],
                                        cwd=self.cwd, env=self.environment(MIGRATION_REQUEST_DEADLINE='10'),
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, start_new_session=True)
                try:
                    proc.stdin.write('y\n')
                    proc.stdin.flush()
                    self.assertTrue(self.mock.entered.wait(8))
                    # Kill the entire process group for SIGKILL; SIGTERM must
                    # exercise the script trap that terminates its own curl.
                    if signum == signal.SIGKILL:
                        os.killpg(proc.pid, signum)
                    else:
                        proc.send_signal(signum)
                    out, err = proc.communicate(timeout=5)
                    self.assertEqual(proc.returncode, -signal.SIGKILL if signum == signal.SIGKILL else 3, err)
                    self.assertNotIn('DONE', out)
                    self.assertEqual(self.mock.calls.count(('source', 'deleteWebhook')), 1)
                    self.assertNotIn(('source', 'logOut'), self.mock.calls)
                    self.assertTrue((self.attempt_directory(4) / 'intent.json').exists())
                    self.assertTrue(self.summary()['continuation_requires_reconciliation'])
                    if signum != signal.SIGKILL:
                        record = self.record('deleteWebhook')
                        self.assertEqual(record['reason'], 'interrupted')
                        self.assertEqual(record['outcome'], 'UNKNOWN')
                    else:
                        self.assertFalse((self.attempt_directory(4) / 'receipt.json').exists())
                    self.assert_restart_blocked()
                finally:
                    if proc.poll() is None:
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.communicate()
                    self.mock.release.set()
                self.reset_run()


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
        self.source = SCRIPT.read_text(encoding='utf-8')

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
        self.assertEqual(record['description'], 'safe reason')
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
