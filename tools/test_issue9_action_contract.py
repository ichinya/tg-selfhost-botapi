"""Executed parity gate: actual Bash helper, exported Bash, actual inline HTML."""
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from issue10_test_support import bash_binary, posix_path
from issue9_action_support import State, mock_api

ROOT = Path(__file__).resolve().parents[1]
MATRIX = json.loads((ROOT / 'tools/fixtures/issue9_action_contract.json').read_text())


class ActionContract(unittest.TestCase):
    def env(self, base):
        env = {k: v for k, v in os.environ.items()
               if k.upper() in ('PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'COMSPEC', 'ISSUE10_BASH')}
        return dict(env, OFFICIAL_BOT_URL=base + '/source', SELF_BOT_URL=base + '/target',
                    SOURCE_API=base + '/source', TARGET_API=base + '/target', BOT_TOKEN='123:synthetic',
                    WEBHOOK_TARGET_LOCAL='true', WEBHOOK_SECRET_MODE='none', WEBHOOK_IP_MODE='dns',
                    WEBHOOK_CERTIFICATE_MODE='none', NO_PROXY='127.0.0.1', no_proxy='127.0.0.1')

    def bash(self, script, env, args=()):
        result = subprocess.run([bash_binary(), posix_path(script), *args], env=env, cwd=ROOT,
                                input=b'y\ny\n', capture_output=True, timeout=15)
        result.stdout = result.stdout.decode('utf-8', errors='replace')
        result.stderr = result.stderr.decode('utf-8', errors='replace')
        return result

    def assert_effect(self, state, action, old, drop, role='target', noop=False):
        mutations = [c for c in state.calls if c['role'] == role and c['method'] in ('setWebhook', 'deleteWebhook')]
        self.assertEqual(len(mutations), 0 if noop else 1, state.calls)
        expected = MATRIX['setUrl'] if action == 'set' else old if action == 'preserve' else ''
        self.assertEqual(state.hooks[role], expected)
        if not noop:
            self.assertEqual(mutations[0]['method'], 'setWebhook' if expected else 'deleteWebhook')
        initial = 5 if role == 'target' else 3
        self.assertEqual(state.queues[role], 0 if drop and not noop else initial)
        if role == 'target':
            self.assertEqual(state.queues['source'], 3)
            detach = next(c for c in state.calls if c['role'] == 'source' and c['method'] == 'deleteWebhook')
            self.assertEqual(detach['data']['drop_pending_updates'], 'false')
            logout = next(i for i, c in enumerate(state.calls) if c['method'] == 'logOut')
            login = next(i for i, c in enumerate(state.calls) if c['role'] == 'target' and c['method'] == 'getMe')
            self.assertLess(logout, login)

    def test_actual_inline_html(self):
        subprocess.run(['node', str(ROOT / 'tools/issue9_action_contract.cjs')], check=True, timeout=40)

    def test_helper_matrix(self):
        for old, target, action, drop in itertools.product(MATRIX['sourceUrls'], MATRIX['targetUrls'], MATRIX['actions'], MATRIX['drop']):
            with self.subTest(old=bool(old), target=bool(target), action=action, drop=drop):
                state = State(old, target)
                with mock_api(state) as base:
                    env = self.env(base)
                    env['DROP_PENDING_UPDATES'] = str(drop).lower()
                    result = self.bash(ROOT / 'migrate_off_to_self.sh', env,
                                       ('123:synthetic', base + '/target', MATRIX['setUrl'], action))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assert_effect(state, action, old, drop)

    def test_export_matrix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['node', str(ROOT / 'tools/issue9_action_contract.cjs'), '--exports', tmp], check=True, timeout=10)
            rows = json.loads((root / 'rows.json').read_text())
            for i, row in enumerate(rows):
                with self.subTest(row=row):
                    script = root / f'{i}.sh'
                    subprocess.run([bash_binary(), '-n', posix_path(script)], check=True, timeout=5)
                    state = State(row['oldHook'], row['targetHook'])
                    with mock_api(state) as base:
                        env = self.env(base)
                        env['WEBHOOK_URL'] = row['hook']
                        result = self.bash(script, env)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    hook_only = row['mode'] == 'hook-only'
                    self.assert_effect(state, row['action'], row['oldHook'], row['drop'],
                                       role='source' if hook_only else 'target', noop=hook_only and row['action'] == 'preserve')

    def test_helper_faults_stop_without_retry(self):
        for fault in MATRIX['faults']:
            action = 'set' if fault == 'profile-mismatch' else 'polling'
            state = State(MATRIX['sourceUrls'][1], MATRIX['targetUrls'][1], fault)
            with self.subTest(fault=fault), mock_api(state) as base:
                result = self.bash(ROOT / 'migrate_off_to_self.sh', self.env(base),
                                   ('123:synthetic', base + '/target', MATRIX['setUrl'], action))
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertNotIn('DONE', result.stdout)
            calls = [c for c in state.calls if c['role'] == 'target' and c['method'] in ('deleteWebhook', 'setWebhook')]
            self.assertEqual(len(calls), 1)
            if fault == 'lost-before': self.assertEqual(state.hooks['target'], MATRIX['targetUrls'][1])
            if fault == 'lost-after': self.assertEqual(state.hooks['target'], '')

    def test_export_faults_stop_without_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['node', str(ROOT / 'tools/issue9_action_contract.cjs'), '--exports', tmp], check=True, timeout=10)
            rows = json.loads((root / 'rows.json').read_text())
            for fault in MATRIX['faults']:
                action = 'set' if fault == 'profile-mismatch' else 'polling'
                index = next(i for i, r in enumerate(rows) if r['mode'] == 'official-to-self' and r['action'] == action)
                state = State(MATRIX['sourceUrls'][1], MATRIX['targetUrls'][1], fault)
                with self.subTest(fault=fault), mock_api(state) as base:
                    env = dict(self.env(base), WEBHOOK_URL=MATRIX['setUrl'])
                    result = self.bash(root / f'{index}.sh', env)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertNotIn('DONE', result.stdout)
                self.assertEqual(len([c for c in state.calls if c['role'] == 'target' and c['method'] in ('setWebhook', 'deleteWebhook')]), 1)

    def test_private_profile_preserve_helper_and_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cert, key, export = root / 'public.pem', root / 'private-key.pem', root / 'export.sh'
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                            '-subj', '/CN=synthetic.invalid', '-keyout', str(key), '-out', str(cert)],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
            subprocess.run(['node', str(ROOT / 'tools/issue9_action_contract.cjs'), '--profile-export', str(export)], check=True, timeout=10)
            for surface in ('helper', 'export'):
                state = State(MATRIX['sourceUrls'][1], MATRIX['targetUrls'][1])
                state.profiles['source'].update(allowed_updates=['message'], max_connections=23,
                                                has_custom_certificate=True, ip_address='192.0.2.1')
                with self.subTest(surface=surface), mock_api(state) as base:
                    env = dict(self.env(base), WEBHOOK_SECRET_MODE='provided', WEBHOOK_SECRET_TOKEN='synthetic_private_canary',
                               WEBHOOK_IP_MODE='fixed', WEBHOOK_IP_ADDRESS='192.0.2.1', WEBHOOK_CERTIFICATE_FILE=posix_path(cert))
                    args = ('123:synthetic', base + '/target', '', 'preserve') if surface == 'helper' else ()
                    result = self.bash(ROOT / 'migrate_off_to_self.sh' if surface == 'helper' else export, env, args)
                self.assertEqual(result.returncode, 0, result.stderr)
                call = next(c for c in state.calls if c['role'] == 'target' and c['method'] == 'setWebhook')
                self.assertEqual(call['data']['secret_token'], 'synthetic_private_canary')
                self.assertEqual(call['data']['certificate'].replace('\r\n', '\n'), cert.read_text())
                self.assertEqual(state.profiles['target'], state.profiles['source'])
                for private in ('synthetic_private_canary', str(cert), MATRIX['sourceUrls'][1]):
                    self.assertNotIn(private, result.stdout + result.stderr)

    def test_helper_preflight_rejects_invalid_actions_and_empty_set(self):
        for action in ('', 'bad', 'set'):
            state = State(MATRIX['sourceUrls'][1], MATRIX['targetUrls'][1])
            with self.subTest(action=action), mock_api(state) as base:
                result = self.bash(ROOT / 'migrate_off_to_self.sh', self.env(base),
                                   ('123:synthetic', base + '/target', '', action))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(state.calls, [])


if __name__ == '__main__':
    unittest.main()
