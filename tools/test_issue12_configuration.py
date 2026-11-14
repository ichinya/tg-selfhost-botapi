"""Credential regressions execute only a fake server; never contact Telegram."""
import os
from pathlib import Path
import unittest
import test_entrypoint


@unittest.skipIf(os.name == 'nt', 'POSIX entrypoint execution deferred to CI/gates')
class ConfigurationTests(unittest.TestCase):
    setUp = test_entrypoint.EntrypointTest.setUp
    run_script = test_entrypoint.EntrypointTest.run_script

    def test_each_missing_empty_or_conflicting_source_prevents_invocation(self):
        original = self.env.copy()
        for name in ('TELEGRAM_API_ID', 'TELEGRAM_API_HASH'):
            for missing in (True, False):
                self.env = original.copy()
                if missing:
                    self.env.pop(name)
                else:
                    self.env[name] = ''
                result = self.run_script()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(name, result.stderr)
                self.assertNotIn('"checked"', result.stdout)
            self.env = original.copy()
            self.env[name + '_FILE'] = '/private/credential-canary'
            result = self.run_script()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(name, result.stderr)
            self.assertNotIn('credential-canary', result.stdout + result.stderr)

    def test_mixed_sources_and_unreadable_regular_file(self):
        secret = self.root / 'secret-canary'
        secret.write_text(self.env['TELEGRAM_API_ID'])
        self.env.pop('TELEGRAM_API_ID')
        self.env['TELEGRAM_API_ID_FILE'] = str(secret)
        self.assertEqual(self.run_script().returncode, 0)
        if os.getuid() == 0:
            self.skipTest('Unreadability requires a real non-root test runner')
        secret.chmod(0)
        self.addCleanup(secret.chmod, 0o600)
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('TELEGRAM_API_ID_FILE', result.stderr)
        self.assertNotIn(str(secret), result.stdout + result.stderr)


class ComposeCredentialTests(unittest.TestCase):
    def test_effective_credentials_require_one_source_per_parameter(self):
        from check_release import validate_compose_config
        ref = lambda name: name + '@sha256:' + 'a' * 64
        selected = {'botapi_image': ref('botapi'), 'nginx_image': ref('gateway')}
        env = {'TELEGRAM_API_ID': '123', 'TELEGRAM_API_HASH': 'synthetic-hash-canary'}
        config = {'services': {'botapi': {'image': selected['botapi_image'], 'environment': env},
                               'gateway': {'image': selected['nginx_image']}}}
        for name in ('TELEGRAM_API_ID', 'TELEGRAM_API_HASH'):
            saved = env.copy()
            for value, file in (('', ''), (None, None), ('inline-canary', '/private/path-canary')):
                env[name], env[name + '_FILE'] = value, file
                with self.subTest(name=name, value=value), self.assertRaises(ValueError) as error:
                    validate_compose_config(config, {'platform': 'linux/amd64'}, selected=selected)
                self.assertIn(name, str(error.exception))
                for canary in ('inline-canary', 'path-canary', 'synthetic-hash-canary'):
                    self.assertNotIn(canary, str(error.exception))
            env.clear(); env.update(saved)
            env[name] = ''
            env[name + '_FILE'] = '/private/placeholder'
            self.assertTrue(validate_compose_config(config, {'platform': 'linux/amd64'}, selected=selected))

    def test_secrets_overlay_clears_inline_values(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / 'docker-compose.secrets.yml').read_text()
        for name in ('TELEGRAM_API_ID', 'TELEGRAM_API_HASH'):
            self.assertIn(name + ': ""', text)
            self.assertIn(name + '_FILE:', text)
