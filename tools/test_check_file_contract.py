from copy import deepcopy
import json
import unittest
from unittest.mock import patch
from tools import check_file_contract as checker


class FileGateTests(unittest.TestCase):
    def test_pinned_writer_source_drift_is_rejected(self):
        source = {
            'FileLoaderUtils.cpp': 'FileFd::open(name, FileFd::Read | FileFd::Write | FileFd::CreateNew, 0640); mkdir(path, 0750); rename(temp_path, perm_path);',
            'FileFd.cpp': '::open(filepath.c_str(), native_flags, static_cast<mode_t>(mode))',
            'path.cpp': '::rename(from.c_str(), to.c_str())',
        }
        checker.validate_writer_sources(source)
        for key in source:
            changed = {**source, key: ''}
            with self.subTest(key=key), self.assertRaises(ValueError):
                checker.validate_writer_sources(changed)
        with self.assertRaises(ValueError):
            checker.validate_writer_sources({**source, 'FileLoaderUtils.cpp': source['FileLoaderUtils.cpp'].replace('0640', '0600')})

    def test_base_state_isolation_does_not_require_split_storage(self):
        model = {'services': {
            'botapi': {'environment': {}, 'volumes': [{'target': '/var/lib/telegram-bot-api'}]},
            'gateway': {'ports': [{'host_ip': '127.0.0.1'}],
                        'volumes': [{'target': '/etc/nginx/conf.d/default.conf', 'read_only': True}]}}}
        checker.validate_state_isolation(model)
        for mutation in ('storage', 'backend-port', 'downloads'):
            item = deepcopy(model)
            if mutation == 'storage':
                item['services']['gateway']['volumes'].append({'target': '/private-state'})
            elif mutation == 'backend-port':
                item['services']['botapi']['ports'] = [8081]
            else:
                item['services']['downloads'] = {}
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                checker.validate_state_isolation(item)

    def test_nginx_mutation_controls(self):
        config = 'server { listen 80; location / { proxy_pass http://botapi:8081; } }'
        checker.validate_state_nginx(config)
        for addition in ('location /file { alias /private-state/; }',
                         'location /file { proxy_pass http://botapi:8081; }',
                         'root /private-state;', 'include private.conf;'):
            with self.subTest(addition=addition), self.assertRaises(ValueError):
                checker.validate_state_nginx(config + addition)

    def test_environment_drops_operator_credentials_and_paths(self):
        with patch.dict(checker.os.environ, {'API_HASH': 'PRIVATE', 'BOT_A_ROOT': '/private',
                                           'COMPOSE_FILE': 'live.yml', 'DOWNLOADS_IMAGE': 'live',
                                           'GATEWAY_BIND': '0.0.0.0'}, clear=True):
            env = checker.environment('fixture-botapi', 'fixture-downloads')
        self.assertNotIn('COMPOSE_FILE', env)
        self.assertNotIn('PRIVATE', json.dumps(env))
        self.assertEqual(env['DOWNLOADS_IMAGE'], 'fixture-downloads')
        self.assertEqual(env['GATEWAY_BIND'], '127.0.0.1')

    def test_project_scope_cannot_target_production(self):
        for project in ('live', '', 'filecontract../live', 'filecontract' + '0' * 13):
            with self.assertRaises(ValueError):
                checker.compose_prefix(project)
        self.assertIn('filecontract' + '0' * 12, checker.compose_prefix('filecontract' + '0' * 12))

    def test_missing_runtime_is_not_a_green_gate(self):
        with patch.object(checker.shutil, 'which', return_value=None):
            self.assertEqual(checker.main([]), 2)

    def test_profile_rejects_parent_mount_and_backend_publication(self):
        model = {'services': {
            'botapi': {'environment': {'TELEGRAM_FILES_DIR': checker.MEDIA},
                       'volumes': [{'target': '/var/lib/telegram-bot-api'}, {'target': checker.MEDIA}]},
            'gateway': {'ports': [{'host_ip': '127.0.0.1'}],
                        'volumes': [{'target': '/etc/nginx/conf.d/default.conf'}]},
            'downloads': {'user': '10001:101', 'read_only': True, 'cap_drop': ['ALL'],
                          'security_opt': ['no-new-privileges:true'], 'cpus': 1, 'mem_limit': 100,
                          'pids_limit': 64, 'volumes': [{'target': checker.MEDIA + '/' + checker.TOKENS[0],
                          'read_only': True, 'bind': {'create_host_path': False}}]},
            'downloads-gateway': {'ports': [{'host_ip': '127.0.0.1', 'published': '18082'}],
                                 'volumes': [{'target': '/etc/nginx/conf.d/default.conf'}]}}}
        checker.validate_profiles(model, 'remote')
        for kind in ('parent', 'published', 'auto-create', 'writable'):
            item = deepcopy(model)
            if kind == 'parent':
                item['services']['downloads']['volumes'][0]['target'] = checker.MEDIA
            elif kind == 'published':
                item['services']['botapi']['ports'] = [8081]
            elif kind == 'auto-create':
                item['services']['downloads']['volumes'][0]['bind']['create_host_path'] = True
            else:
                item['services']['downloads']['volumes'][0]['read_only'] = False
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                checker.validate_profiles(item, 'remote')


if __name__ == '__main__':
    unittest.main()
