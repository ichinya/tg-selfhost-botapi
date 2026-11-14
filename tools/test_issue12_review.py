"""Regression checks for release consumers."""
import re
import unittest

from check_release import validate_compose_config
from image_inputs import ROOT


class ReviewRegressionTests(unittest.TestCase):
    def test_migration_build_passes_required_dockerfile_args(self):
        dockerfile = (ROOT / 'Dockerfile').read_text()
        workflow = (ROOT / '.github/workflows/migration-safety.yml').read_text()
        required = set(re.findall(r'test -n "\$([A-Z_]+)"', dockerfile))
        args = set(re.findall(r'^\s+([A-Z_]+)=\$\{\{ env\.\1 \}\}$', workflow, re.M))
        self.assertTrue(required)
        self.assertEqual(required - args, set())

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
