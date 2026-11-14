import subprocess
import unittest
from unittest import mock
import check_file_contract as checker


class CheckerTests(unittest.TestCase):
    def test_full_consumer_topology_mutants_fail(self):
        root = '/var/lib/telegram-bot-api-files/12345:SYNTHETIC_A'
        def consumer():
            return {'user': '101:101', 'read_only': True, 'volumes': [
                {'source': 'media', 'target': root, 'read_only': True,
                 'volume': {'subpath': '12345:SYNTHETIC_A'}}]}
        model = {'services': {'reader': consumer(), 'downloads': consumer(),
                             'gateway': {}, 'tls': {}, 'mountcheck': {'privileged': True}}}
        checker.validate_full(model)
        model['services']['downloads']['volumes'][0]['read_only'] = False
        with self.assertRaises(ValueError): checker.validate_full(model)

    def test_split_cannot_alias_private_backing(self):
        model = {'services': {'botapi': {'environment': {'TELEGRAM_FILES_DIR': '/var/lib/telegram-bot-api-files'},
                 'volumes': [{'target': '/var/lib/telegram-bot-api-files', 'source': '/same'},
                             {'target': '/var/lib/telegram-bot-api', 'source': '/same'}]}}}
        with self.assertRaises(ValueError): checker.validate_split(model)

    def test_full_runtime_requires_exact_pair(self):
        with self.assertRaises(checker.NotRun): checker.exercise(None, None, {})

    def test_recipe_hashes_cover_runtime_sources(self):
        hashes = checker.source_hashes()
        for name in ('tools/file_access.py', 'tools/file_contract.py', 'tools/download_server.py',
                     'tools/fixtures/files/runtime.py', 'Dockerfile.downloads'):
            self.assertEqual(64, len(hashes[name]))

    def test_project_name_restricts_cleanup(self):
        with self.assertRaises(ValueError):
            checker.prefix('production')
        self.assertIn('filecontract012345abcdef', checker.prefix('filecontract012345abcdef'))

    def test_unavailable_and_timeout_are_notrun(self):
        with mock.patch.object(checker.shutil, 'which', return_value=None):
            self.assertEqual(2, checker.main(['--state-isolation-only']))
        with mock.patch.object(checker.subprocess, 'run', side_effect=subprocess.TimeoutExpired('docker', 1)):
            with self.assertRaises(checker.NotRun): checker.command(['docker'], {})

    def test_daemon_denial_is_not_a_pass(self):
        with mock.patch.object(checker.shutil, 'which', return_value='docker'), \
             mock.patch.object(checker, 'command', side_effect=subprocess.CalledProcessError(1, ['docker', 'info'])):
            self.assertEqual(2, checker.main(['--state-isolation-only']))

    def test_nginx_fixture_must_have_immutable_identity(self):
        digest = 'nginx@sha256:' + 'a' * 64
        with mock.patch.object(checker, 'command', side_effect=['', '[{"RepoDigests":["' + digest + '"]}]']):
            self.assertEqual(digest, checker.pin_nginx({'FILE_NGINX_IMAGE': digest}))
        with mock.patch.object(checker, 'command', side_effect=['', '[{"RepoDigests":[]}]']):
            with self.assertRaises(ValueError): checker.pin_nginx({})
        with self.assertRaises(ValueError): checker.pin_nginx({'FILE_NGINX_IMAGE': 'other.invalid/nginx:latest'})

    def test_unsafe_mount_and_alias_are_rejected(self):
        safe = {'services': {'botapi': {}, 'gateway': {'volumes': [
            {'type': 'bind', 'source': str(checker.ROOT / 'nginx.conf'),
             'target': '/etc/nginx/conf.d/default.conf', 'read_only': True},
            {'type': 'bind', 'source': str(checker.ROOT / 'nginx-main.conf'),
             'target': '/etc/nginx/nginx.conf', 'read_only': True},
            {'type': 'volume', 'source': 'gateway_client_temp',
             'target': '/var/cache/nginx/client_temp'}]}}}
        nginx = 'location = /file { return 404; } location /file/ { return 404; }'
        checker.validate(safe, nginx)
        with self.assertRaises(ValueError): checker.validate(safe, nginx + ' alias /data;')
        safe['services']['gateway']['volumes'].append({'target': '/state'})
        with self.assertRaises(ValueError): checker.validate(safe, nginx)

    def test_runtime_gateway_mounts_must_match_shipped_config(self):
        def bind(target, source):
            return {'Destination': target, 'Source': str(checker.ROOT / source), 'RW': False}
        mounts = [bind('/etc/nginx/nginx.conf', 'nginx-main.conf'),
                  bind('/etc/nginx/conf.d/default.conf', 'nginx.conf'),
                  {'Destination': '/var/cache/nginx/client_temp', 'Type': 'volume', 'RW': True}]
        checker.validate_gateway_runtime({'Mounts': mounts})
        management = bind('/etc/nginx/conf.d/observability.conf', 'nginx.observability.conf')
        checker.validate_gateway_runtime({'Mounts': mounts + [management]})
        for bad in ([], mounts[:-1], mounts + [{'Destination': '/state', 'RW': False}],
                    mounts + [dict(management, RW=True)]):
            with self.subTest(mounts=bad), self.assertRaises(ValueError):
                checker.validate_gateway_runtime({'Mounts': bad})



if __name__ == '__main__': unittest.main()
