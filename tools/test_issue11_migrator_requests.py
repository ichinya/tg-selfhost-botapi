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

from issue11_migrator_mock import CURL_WRAPPER, METHODS, MUTATIONS, MockAPI, StalledTLS, TOKEN, WEBHOOK

SCRIPT = Path(__file__).resolve().parents[1] / 'migrate_off_to_self.sh'
REAL_CURL = shutil.which('curl')


class MigrationRequestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.name != 'posix':
            raise unittest.SkipTest('POSIX acceptance requires Linux/WSL; Windows skips are not acceptance')
        for tool in ('bash', 'curl', 'jq', 'stat', 'python3'):
            if not shutil.which(tool):
                raise RuntimeError(tool + ' is required for Linux acceptance (no silent skip)')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.work = self.root / 'work'
        self.work.mkdir()
        self.home = self.root / 'home'
        self.home.mkdir()
        self.mock = MockAPI()
        self.addCleanup(self.mock.close)
        (self.bin / 'curl').write_text(CURL_WRAPPER)
        (self.bin / 'curl').chmod(0o700)

    def environment(self, **extra):
        # Do not inherit credentials, proxy settings, curl homes or timeout values.
        env = dict(PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                   HOME=str(self.home), LANG='C.UTF-8', LC_ALL='C.UTF-8',
                   REAL_CURL=REAL_CURL, SOURCE_URL=self.mock.source_url,
                   TARGET_URL=self.mock.target_url, SELF_URL=self.mock.target_url,
                   ARGLOG=str(self.root / 'args'), MIGRATION_CONNECT_TIMEOUT='1',
                   MIGRATION_REQUEST_DEADLINE='1', NO_PROXY='*', no_proxy='*')
        env.update(extra)
        return env

    def run_script(self, confirmation='y\n', third=None, fallback=False, **extra):
        env = self.environment(**extra)
        args = ['bash', str(SCRIPT), TOKEN]
        if fallback:
            env['SELF_BOT_URL'] = self.mock.target_url
            if third is not None:
                env['WEBHOOK_URL'] = third
        else:
            args.append(self.mock.target_url)
            if third is not None:
                args.append(third)
        return subprocess.run(args, input=confirmation, text=True, capture_output=True,
                              cwd=self.work, env=env, timeout=15)

    def run_directory(self):
        run, = (self.work / 'logs/migration').iterdir()
        return run

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
                    'description', 'retry_after', 'not_before', 'response_complete',
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
        if (self.work / 'logs').exists():
            shutil.rmtree(self.work / 'logs')
        self.mock.calls.clear()
        self.mock.effects.clear()
        self.mock.entered.clear()
        self.mock.release.clear()

    def assert_stopped(self, method):
        self.assertEqual(sum(m == method for _, m in self.mock.calls), 1)
        if method == 'deleteWebhook':
            self.assertNotIn(('source', 'logOut'), self.mock.calls)
        if method in ('deleteWebhook', 'logOut'):
            self.assertNotIn(('target', 'setWebhook'), self.mock.calls)

    def test_success_webhook_and_schema(self):
        result = self.run_script(third=WEBHOOK)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Webhook OK', result.stdout)
        self.assertNotIn(TOKEN, result.stdout + result.stderr)
        self.assertNotIn(WEBHOOK, result.stdout + result.stderr)
        self.assertEqual([m for _, m in self.mock.calls],
                         ['getMe', 'getMe', 'getWebhookInfo', 'deleteWebhook',
                          'logOut', 'getMe', 'setWebhook', 'getWebhookInfo'])
        self.assertEqual(len(self.records()), 8)
        summary = self.summary()
        self.assertTrue(summary['completed'])
        self.assertFalse(summary['continuation_requires_reconciliation'])
        intent = json.loads((self.run_directory() / 'request-1/intent.json').read_text())
        self.assertIsNone(intent['bot_id'])
        self.assertIsNone(intent['finished_at'])
        self.assertTrue(intent['session_effect_possible'])

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
        self.assertEqual(len(self.mock.calls), 3)

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

    def test_retry_after_validation(self):
        self.mock.scenario = 'http429'
        for retry in (0, 7, 'absent', None, '7', -1, 1.5, True, {}, 10 ** 100):
            with self.subTest(retry=retry):
                self.mock.retry = retry
                result = self.run_script()
                self.assertEqual(result.returncode, 1, result.stderr)
                record = self.record('deleteWebhook')
                valid = type(retry) is int and retry in (0, 7)
                self.assertEqual(record['reason'], 'rate_limited' if valid else
                                 'api_rejected' if retry == 'absent' else 'invalid_retry_after')
                self.assertEqual(record['retry_after_status'], 'valid' if valid else
                                 'absent' if retry == 'absent' else 'invalid')
                self.assertEqual(record['outcome'], 'WAITING' if valid else 'CONFIRMED_REJECTION')
                self.assertEqual(record['not_before'] is not None, valid)
                if valid:
                    self.assertRegex(record['not_before'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$')
                else:
                    self.assertIsNone(record['retry_after'])
                self.assert_stopped('deleteWebhook')
                self.reset_run()

    def test_invalid_or_contradictory_responses_are_unknown(self):
        for scenario in ('malformed', 'empty', 'array', 'null', 'multiple', 'string_ok', 'missing_ok',
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
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(self.mock.effects)
        self.assertEqual(self.record('getWebhookInfo')['outcome'], 'FAILED')

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
                self.assertFalse(self.mock.effects)
                self.reset_run()

    def test_definite_preflight_rejection_keeps_warning(self):
        self.mock.target, self.mock.scenario = ('target', 'getMe'), 'http400'
        result = self.run_script(confirmation='n\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Warning: self API reachable but not ready', result.stdout)
        self.assertIn(('source', 'getMe'), self.mock.calls)

    def test_ambiguous_target_identity_after_logout_marks_partial_migration(self):
        self.mock.target, self.mock.scenario = ('target', 'getMe'), 'malformed'
        self.mock.occurrence = 2
        result = self.run_script()
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn(('source', 'logOut'), self.mock.effects)
        self.assertNotIn(('target', 'setWebhook'), self.mock.calls)
        self.assertEqual(self.mock.calls.count(('target', 'getMe')), 2)
        self.assertTrue(self.summary()['partial_migration'])
        self.assertTrue(self.summary()['continuation_requires_reconciliation'])

    def test_loss_with_and_without_effect_remains_unknown(self):
        for scenario in ('lost', 'lost_no_effect'):
            for method in MUTATIONS:
                with self.subTest(scenario=scenario, method=method):
                    role = 'target' if method == 'setWebhook' else 'source'
                    self.mock.target, self.mock.scenario = (role, method), scenario
                    result = self.run_script()
                    self.assertEqual(result.returncode, 3, result.stderr)
                    self.assertEqual(self.mock.effects.count((role, method)), int(scenario == 'lost'))
                    self.assertEqual(self.record(method)['outcome'], 'UNKNOWN')
                    self.assert_stopped(method)
                    self.reset_run()

    def test_real_deadline_covers_delayed_headers_and_continuous_body(self):
        for scenario in ('delayed', 'slow', 'partial'):
            with self.subTest(scenario=scenario):
                self.mock.scenario = scenario
                start = time.monotonic()
                result = self.run_script()
                self.assertEqual(result.returncode, 3, result.stderr)
                self.assertLess(time.monotonic() - start, 6)
                record = self.record('deleteWebhook')
                self.assertEqual(record['curl_exit_code'], 18 if scenario == 'partial' else 28)
                self.assertFalse(record['response_complete'])
                if scenario != 'delayed':
                    self.assertEqual(record['http_status'], 200)
                    body = (self.run_directory() / record['body']).read_text()
                    self.assertIn('true', body)
                self.assert_stopped('deleteWebhook')
                self.reset_run()

    def test_stalled_tls_connect_timeout_on_loopback(self):
        stalled = StalledTLS()
        self.addCleanup(stalled.close)
        start = time.monotonic()
        result = self.run_script(TARGET_URL='https://127.0.0.1:%d' % stalled.port,
                                 MIGRATION_REQUEST_DEADLINE='3')
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertLess(time.monotonic() - start, 4)
        record = self.record('getMe', 'target')
        self.assertEqual(record['curl_exit_code'], 28)
        self.assertIsNone(record['http_status'])
        self.assertFalse(self.mock.calls)

    def test_real_connection_refused(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        result = self.run_script(TARGET_URL='http://127.0.0.1:%d' % port)
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(self.record('getMe')['curl_exit_code'], 7)
        self.assertFalse(self.mock.calls)

    def test_fake_transport_preserves_status_body_and_stderr_independently(self):
        for code in ('6', '7', '28', '35', '60'):
            with self.subTest(code=code):
                result = self.run_script(FAKE_METHOD='target:getMe', FAKE_EXIT=code)
                self.assertEqual(result.returncode, 3, result.stderr)
                record = self.record('getMe')
                self.assertEqual(record['curl_exit_code'], int(code))
                self.assertIsNone(record['http_status'])
                self.assertEqual(record['reason'], 'transport_unknown')
                self.assertFalse(self.mock.calls)
                self.assertIn('transport failure', (self.run_directory() / record['transport_stderr']).read_text())
                self.reset_run()
        result = self.run_script(FAKE_METHOD='source:deleteWebhook', FAKE_EXIT='28',
                                 FAKE_STATUS='200', FAKE_BODY='{"ok":true,"result":true}\n\n')
        self.assertEqual(result.returncode, 3, result.stderr)
        record = self.record('deleteWebhook')
        self.assertEqual(record['http_status'], 200)
        self.assertFalse(record['response_complete'])
        self.assertEqual(record['outcome'], 'UNKNOWN')

    def test_malformed_body_and_secret_encodings(self):
        self.mock.scenario = 'secrets'
        result = self.run_script(API_HASH='test-configuration-secret')
        self.assertEqual(result.returncode, 3, result.stderr)
        record = self.record('deleteWebhook')
        body = (self.run_directory() / record['body']).read_text()
        self.assertIn('useful', body)
        self.assertTrue(body.endswith('\n\n'))
        self.assertNotIn('%3a', body)
        self.assertNotIn('\\u0031', body)
        self.assertNotIn(TOKEN, result.stdout + result.stderr)

    def test_large_body_is_not_console_preview(self):
        body = 'full-body-' + 'x' * 12000 + '\n\n'
        result = self.run_script(FAKE_METHOD='source:deleteWebhook', FAKE_EXIT='0',
                                 FAKE_STATUS='500', FAKE_BODY=body)
        self.assertEqual(result.returncode, 3, result.stderr)
        record = self.record('deleteWebhook')
        self.assertEqual((self.run_directory() / record['body']).read_text(), body)
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
        for connect, deadline, valid in (('1', '1', True), ('300', '300', True),
                                         ('0005', '0030', True), ('2', '1', False)):
            with self.subTest(connect=connect, deadline=deadline):
                result = self.run_script(confirmation='n\n', MIGRATION_CONNECT_TIMEOUT=connect,
                                         MIGRATION_REQUEST_DEADLINE=deadline)
                self.assertEqual(result.returncode, 0 if valid else 1, result.stderr)
                self.assertEqual(bool(self.mock.calls), valid)
                self.reset_run()

    def test_dotenv_precedence_and_defaults(self):
        (self.work / '.env').write_text('MIGRATION_CONNECT_TIMEOUT=2\nMIGRATION_REQUEST_DEADLINE=3\n')
        result = self.run_script(confirmation='n\n', MIGRATION_CONNECT_TIMEOUT='invalid')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(all(r['connect_timeout'] == 2 and r['request_deadline'] == 3 for r in self.records()))
        self.reset_run()
        (self.work / '.env').unlink()
        env = self.environment()
        del env['MIGRATION_CONNECT_TIMEOUT'], env['MIGRATION_REQUEST_DEADLINE']
        result = subprocess.run(['bash', str(SCRIPT), TOKEN, self.mock.target_url], input='n\n',
                                text=True, capture_output=True, cwd=self.work, env=env, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(all(r['connect_timeout'] == 5 and r['request_deadline'] == 30 for r in self.records()))

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
                                   '  if [[ "$arg" == */request-4/.' + phase + '.tmp ]]; then exit 1; fi\n'
                                   'done\nexec "' + actual + '" "$@"\n')
                wrapper.chmod(0o700)
                result = self.run_script()
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual(self.mock.calls.count(('source', 'deleteWebhook')), int(phase == 'receipt'))
                self.assertNotIn(('source', 'logOut'), self.mock.calls)
                run = self.run_directory()
                self.assertEqual((run / 'request-4/intent.json').exists(), phase == 'receipt')
                self.assertFalse((run / 'request-4/receipt.json').exists())
                self.assertFalse(list(run.rglob('.raw-*')))
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

    def test_foreign_receipt_cannot_resolve_current_attempt(self):
        self.mock.scenario = 'malformed'
        result = self.run_script()
        self.assertEqual(result.returncode, 3, result.stderr)
        run = self.run_directory()
        summary = self.summary()
        summary['continuation_requires_reconciliation'] = False
        (run / 'summary.json').write_text(json.dumps(summary))
        path = run / 'request-4/receipt.json'
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
        runs = list((self.work / 'logs/migration').iterdir())
        self.assertEqual(len(runs), 2)
        self.assertEqual(len({run.name for run in runs}), 2)
        self.assertTrue(any(run.name == first for run in runs))
        for run in runs:
            self.assertRegex(run.name, r'^run\.\d{8}T\d{6}Z\.\d+\.')

    def test_parallel_admitted_runs_get_distinct_dossiers(self):
        # Both invocations pass the conservative startup gate before creating
        # their run. This tests namespace isolation, not a cross-run lock.
        (self.work / 'logs').mkdir(mode=0o700)
        (self.work / 'logs/migration').mkdir(mode=0o700)
        barrier = self.root / 'run-barrier'
        barrier.mkdir()
        real_mktemp = shutil.which('mktemp')
        wrapper = self.bin / 'mktemp'
        wrapper.write_text(
            '#!/usr/bin/env python3\nimport os, sys, time\nfrom pathlib import Path\n'
            'root = Path(' + repr(str(barrier)) + ')\n'
            '(root / str(os.getpid())).touch()\n'
            'deadline = time.monotonic() + 5\n'
            'while len(list(root.iterdir())) < 2:\n'
            '    if time.monotonic() > deadline: raise SystemExit("run barrier timeout")\n'
            '    time.sleep(.01)\n'
            'os.execv(' + repr(real_mktemp) + ', [' + repr(real_mktemp) + '] + sys.argv[1:])\n')
        wrapper.chmod(0o700)
        processes = []
        try:
            for _ in range(2):
                proc = subprocess.Popen(['bash', str(SCRIPT), TOKEN, self.mock.target_url],
                                        cwd=self.work, env=self.environment(), stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                        start_new_session=True)
                processes.append(proc)
                proc.stdin.write('n\n')
                proc.stdin.flush()
            for proc in processes:
                _, err = proc.communicate(timeout=15)
                self.assertEqual(proc.returncode, 0, err)
        finally:
            for proc in processes:
                if proc.poll() is None:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.communicate()
        runs = list((self.work / 'logs/migration').iterdir())
        self.assertEqual(len(runs), 2)
        self.assertEqual(len({run.name for run in runs}), 2)
        self.assertFalse(self.mock.effects)

    def test_interruptions_keep_intent_without_retry(self):
        for signum in (signal.SIGTERM, signal.SIGKILL):
            with self.subTest(signal=signum):
                self.mock.scenario = 'barrier'
                proc = subprocess.Popen(['bash', str(SCRIPT), TOKEN, self.mock.target_url],
                                        cwd=self.work, env=self.environment(MIGRATION_REQUEST_DEADLINE='10'),
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
                    self.assertEqual(proc.returncode, -signal.SIGKILL if signum == signal.SIGKILL else 143, err)
                    self.assertNotIn('DONE', out)
                    self.assertEqual(self.mock.calls.count(('source', 'deleteWebhook')), 1)
                    self.assertNotIn(('source', 'logOut'), self.mock.calls)
                    self.assertTrue((self.run_directory() / 'request-4/intent.json').exists())
                    self.assertTrue(self.summary()['continuation_requires_reconciliation'])
                    if signum == signal.SIGTERM:
                        record = self.record('deleteWebhook')
                        self.assertEqual(record['reason'], 'interrupted')
                        self.assertEqual(record['outcome'], 'UNKNOWN')
                    else:
                        self.assertFalse((self.run_directory() / 'request-4/receipt.json').exists())
                    self.assert_restart_blocked()
                finally:
                    if proc.poll() is None:
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.communicate()
                    self.mock.release.set()
                self.reset_run()


if __name__ == '__main__':
    unittest.main()
