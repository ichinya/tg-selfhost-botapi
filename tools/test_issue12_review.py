"""Regression checks for release consumers."""
import re
import unittest
import copy
import json
import hashlib
from unittest.mock import patch

from check_release import validate_compose_config
from image_inputs import ROOT


class ReviewRegressionTests(unittest.TestCase):
    def test_component_image_rejects_shell_substitution(self):
        from release_contract import validate_receipt
        from test_issue12_contract import ReleaseManifestTest
        fixture = ReleaseManifestTest()
        fixture.setUp()
        receipt = fixture.fixture()
        for name in ('x$(touch t)', 'x$(id)', 'x"quoted'):
            receipt['components']['observer']['image'] = name + '@sha256:' + 'a' * 64
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'component reference'):
                validate_receipt(receipt, fixture.inputs)

    def test_second_patch_evidence_must_match_recipe(self):
        from check_release import image_evidence
        from image_inputs import resolve
        inputs = resolve()
        labels = {'org.opencontainers.image.revision': inputs['bot_api_revision'],
                  'io.tg-selfhost.bot-api-revision': inputs['bot_api_revision'],
                  'org.opencontainers.image.version': inputs['bot_api_version'],
                  'io.tg-selfhost.tdlib-revision': inputs['submodules']['td'],
                  'io.tg-selfhost.wrapper-revision': inputs['wrapper_revision'],
                  'io.tg-selfhost.build-key': inputs['build_key'],
                  'io.tg-selfhost.base': inputs['alpine_image'],
                  'io.tg-selfhost.platform': inputs['platform'],
                  'io.tg-selfhost.privacy-policy': 'issue17-v1',
                  'io.tg-selfhost.verification-contract': '1'}
        info = {'Os': 'linux', 'Architecture': 'amd64',
                'Config': {'Labels': labels, 'Entrypoint': ['/docker-entrypoint.sh']}}
        first = hashlib.sha256((ROOT / 'patches/webhook-user-agent.patch').read_bytes()).hexdigest()
        evidence = (first + '  /tmp/webhook-user-agent.patch\n' +
                    '0' * 64 + '  /tmp/botapi-secrets-redaction.patch\n').encode()

        def fake(*args):
            path = args[-1]
            if args[:3] == ('docker', 'image', 'inspect'):
                return json.dumps([info]).encode()
            if path == '--version':
                return inputs['bot_api_version'].encode()
            if path == '/usr/local/bin/telegram-bot-api':
                return b'\x7fELF\x02\x01' + b'\x00' * 12 + b'\x3e\x00WebhookDelivery/1.0'
            if path in ('/docker-entrypoint.sh', '/usr/local/bin/botapi-healthcheck'):
                return (ROOT / ('tools/botapi_healthcheck.sh' if path.endswith('botapi-healthcheck') else 'docker-entrypoint.sh')).read_bytes()
            if path.endswith('/patch.sha256'):
                return evidence
            if path.endswith('-repositories.txt'):
                return b'https://dl-cdn.alpinelinux.org/alpine/v3.22/main\n'
            if path.endswith('-apk.txt'):
                return (inputs['apk_refresh_id'] + '\n').encode()
            return b'inventory\n'

        with patch('check_release.command', side_effect=fake):
            with self.assertRaisesRegex(ValueError, 'Image patch evidence differs from recipe'):
                image_evidence('candidate:local', inputs, require_registry=False)

    def test_local_components_must_match_saved_inputs(self):
        from image_inputs import build_environment, resolve
        inputs = resolve()
        args = {k: v for k, v in build_environment(inputs).items() if k not in ('OBSERVER_BASE', 'PYTHON_IMAGE')}
        config = {'services': {
            'botapi': {'image': 'tg-selfhost-botapi:local', 'build': {'args': args},
                       'environment': {'TELEGRAM_API_ID': '123', 'TELEGRAM_API_HASH': 'synthetic'}},
            'gateway': {'image': inputs['nginx_image']},
            'observer': {'image': 'tg-selfhost-botapi-observer:local', 'build': {'args': {
                'OBSERVER_BASE': inputs['observer_base'], 'APK_REFRESH_ID': inputs['apk_refresh_id'],
                'BUILD_FINGERPRINT': inputs['build_key']}}},
            'downloads': {'image': 'tg-selfhost-botapi-downloads:local', 'build': {'args': {
                'PYTHON_IMAGE': inputs['python_image'], 'BUILD_FINGERPRINT': inputs['downloads_key']}}},
        }}
        self.assertTrue(validate_compose_config(config, inputs, local=True))
        for name in ('observer', 'downloads'):
            bad = copy.deepcopy(config)
            bad['services'][name]['image'] = 'foreign:latest'
            with self.subTest(component=name), self.assertRaises(ValueError):
                validate_compose_config(bad, inputs, local=True)
            for arg in config['services'][name]['build']['args']:
                bad = copy.deepcopy(config)
                bad['services'][name]['build']['args'][arg] = 'foreign'
                with self.subTest(component=name, arg=arg), self.assertRaises(ValueError):
                    validate_compose_config(bad, inputs, local=True)
            bad = copy.deepcopy(config)
            del bad['services'][name]['build']
            with self.assertRaises(ValueError):
                validate_compose_config(bad, inputs, local=True)

    def test_migration_build_passes_required_dockerfile_args(self):
        dockerfile = (ROOT / 'Dockerfile').read_text()
        workflow = (ROOT / '.github/workflows/migration-safety.yml').read_text()
        required = set(re.findall(r'test -n "\$([A-Z_]+)"', dockerfile))
        args = set(re.findall(r'^\s+([A-Z_]+)=\$\{\{ env\.\1 \}\}$', workflow, re.M))
        self.assertTrue(required)
        self.assertEqual(required - args, {'TARGETPLATFORM'})

    def test_effective_compose_port_must_match_gateway(self):
        ref = lambda name: name + '@sha256:' + 'a' * 64
        selected = {name + '_image': ref(name) for name in ('botapi', 'nginx')}
        env = {'TELEGRAM_API_ID': '123', 'TELEGRAM_API_HASH': 'synthetic'}
        config = {'services': {'botapi': {'image': selected['botapi_image'], 'environment': env},
                               'gateway': {'image': selected['nginx_image']}}}
        inputs = {'platform': 'linux/amd64'}
        for port in ('8081', 8081):
            env['TELEGRAM_HTTP_PORT'] = port
            self.assertTrue(validate_compose_config(config, inputs, selected=selected))
        for port in ('8082', '', None):
            env['TELEGRAM_HTTP_PORT'] = port
            with self.subTest(port=port), self.assertRaisesRegex(ValueError, 'TELEGRAM_HTTP_PORT'):
                validate_compose_config(config, inputs, selected=selected)
        env['TELEGRAM_HTTP_PORT'] = '8081'
        for address in ('127.0.0.1', '127.0.1.2', '::1', 'localhost', ''):
            env['TELEGRAM_HTTP_IP_ADDRESS'] = address
            with self.subTest(address=address), self.assertRaisesRegex(ValueError, 'TELEGRAM_HTTP_IP_ADDRESS'):
                validate_compose_config(config, inputs, selected=selected)
        env['TELEGRAM_HTTP_IP_ADDRESS'] = '0.0.0.0'
        self.assertTrue(validate_compose_config(config, inputs, selected=selected))

    def test_registry_rejects_foreign_or_missing_optional_images(self):
        ref = lambda name: name + '@sha256:' + 'a' * 64
        selected = {name + '_image': ref(name) for name in ('botapi', 'nginx', 'observer', 'downloads')}
        config = {'services': {'botapi': {'image': selected['botapi_image'], 'environment': {
            'TELEGRAM_API_ID': '123', 'TELEGRAM_API_HASH': 'synthetic'}},
            'gateway': {'image': selected['nginx_image']}}}
        inputs = {'platform': 'linux/amd64'}
        for name in ('observer', 'downloads'):
            config['services'][name] = {'image': selected[name + '_image']}
        self.assertTrue(validate_compose_config(config, inputs, selected=selected))
        for name in ('observer', 'downloads'):
            for bad in (ref('rogue'), name + ':latest', name + '@sha256:' + 'g' * 64):
                with self.subTest(name=name, bad=bad):
                    config['services'][name]['image'] = bad
                    with self.assertRaises(ValueError):
                        validate_compose_config(config, inputs, selected=selected)
            config['services'][name]['image'] = selected[name + '_image']
            incomplete = dict(selected)
            del incomplete[name + '_image']
            with self.assertRaises(ValueError):
                validate_compose_config(config, inputs, selected=incomplete)
            invalid = dict(selected)
            invalid[name + '_image'] = name + ':latest'
            config['services'][name]['image'] = invalid[name + '_image']
            with self.assertRaises(ValueError):
                validate_compose_config(config, inputs, selected=invalid)
            config['services'][name]['image'] = selected[name + '_image']
