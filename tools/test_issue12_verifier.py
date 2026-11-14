import json
import subprocess
import unittest
import io
from email.message import Message
import urllib.error
from unittest.mock import patch

from check_release import check_gateway, image_evidence, registry_lookup, verify_reuse
from image_inputs import ROOT, resolve


class ReleaseCheckTest(unittest.TestCase):
    def test_image_negative_matrix(self):
        inputs = resolve()
        labels = {'org.opencontainers.image.revision': inputs['bot_api_revision'],
                  'io.tg-selfhost.bot-api-revision': inputs['bot_api_revision'],
                  'org.opencontainers.image.version': inputs['bot_api_version'],
                  'io.tg-selfhost.tdlib-revision': inputs['submodules']['td'],
                  'io.tg-selfhost.wrapper-revision': inputs['wrapper_revision'],
                  'io.tg-selfhost.build-key': inputs['build_key'],
                  'io.tg-selfhost.base': inputs['alpine_image'],
                  'io.tg-selfhost.platform': inputs['platform'], 'io.tg-selfhost.verification-contract': '1'}
        labels['io.tg-selfhost.privacy-policy'] = 'issue17-v1'
        info = {'Os': 'linux', 'Architecture': 'amd64', 'Config': {'Labels': labels, 'Entrypoint': ['/docker-entrypoint.sh']},
                'Id': 'sha256:' + 'b' * 64}
        info['Config']['Healthcheck'] = {
            'Test': ['CMD', '/botapi-healthcheck.sh'], 'Interval': 10000000000,
            'Timeout': 5000000000, 'StartPeriod': 30000000000, 'Retries': 6}
        binary = b'\x7fELF\x02\x01' + b'\x00' * 12 + b'\x3e\x00WebhookDelivery/1.0'
        packages = [b'libssl3-3.5.4-r0\n', b'libssl3-3.5.4-r0\n']
        registry_manifest = {'manifests': [
            {'digest': 'sha256:'+'c'*64, 'platform': {'os':'linux', 'architecture':'amd64'}},
            {'digest': 'sha256:'+'d'*64, 'platform': {'os':'linux', 'architecture':'arm64'}}]}
        read_overrides = {}

        def fake(*args):
            if args[-1] in read_overrides:
                return read_overrides[args[-1]]
            if args[:4] == ('docker', 'buildx', 'imagetools', 'inspect'):
                return json.dumps(registry_manifest).encode()
            if args[:3] == ('docker', 'image', 'inspect'):
                return json.dumps([info]).encode()
            if args[-1] == '--version':
                return ('telegram-bot-api ' + inputs['bot_api_version']).encode()
            if args[-1] == '/usr/local/bin/telegram-bot-api':
                return binary
            if args[-1].endswith('/runtime-packages.txt'):
                return packages[0]
            if args[-1] == 'apk info -vv | sort':
                return packages[1]
            if args[-1] in ('/docker-entrypoint.sh', '/usr/local/bin/botapi-healthcheck'):
                return (ROOT / ('tools/botapi_healthcheck.sh' if args[-1].endswith('botapi-healthcheck') else 'docker-entrypoint.sh')).read_bytes()
            if args[-1].endswith('/patch.sha256'):
                import hashlib
                return (hashlib.sha256((ROOT / 'patches/webhook-user-agent.patch').read_bytes()).hexdigest() + '  patch\n').encode()
            if args[-1].endswith('/source.txt'):
                return (inputs['bot_api_revision'] + '\n' + ''.join(' ' + sha + ' ' + path + '\n' for path, sha in inputs['submodules'].items()) + inputs['bot_api_version'] + '\n').encode()
            if args[-1].endswith('-repositories.txt'):
                return b'https://dl-cdn.alpinelinux.org/alpine/v3.22/main\n'
            if args[-1].endswith('-apk.txt'):
                return ('apk-tools\nx86_64\n'+inputs['apk_refresh_id']+'\n').encode()
            if args[-1].endswith('/binary.sha256'):
                import hashlib
                return (hashlib.sha256(binary).hexdigest() + '  binary\n').encode()
            if args[-1].endswith('/adapter.sha256'):
                import hashlib
                return ''.join(hashlib.sha256((ROOT / ('tools/' + p)).read_bytes()).hexdigest() + '  ' + p + '\n'
                    for p in ('webhook_sender/CMakeLists.txt', 'webhook_sender/webhook_sender_test.cpp')).encode()
            if args[-1].endswith('/installed'):
                stage = 'build' if '/build/' in args[-1] else 'runtime'
                return ('\n\n'.join('P:' + p + '\nV:1-r0\nA:x86_64' for p in inputs['apk_policy']['packages'][stage]) + '\n').encode()
            return b'inventory-or-linkage\n'

        with patch('check_release.command', side_effect=fake):
            evidence = image_evidence('candidate:local', inputs, require_registry=False)
            self.assertEqual(evidence['config_id'], info['Id'])
            read_overrides['/usr/share/tg-selfhost-botapi/build/binary.sha256'] = b'wrong-binary-hash  binary\n'
            with self.assertRaisesRegex(ValueError, 'binary hash'):
                image_evidence('candidate:local', inputs, require_registry=False)
            read_overrides.clear()
            read_overrides['/usr/local/bin/botapi-healthcheck'] = b'wrong probe'
            with self.assertRaisesRegex(ValueError, 'recipe files'):
                image_evidence('candidate:local', inputs, require_registry=False)
            read_overrides.clear()
            ref = 'example:v1@sha256:' + 'a'*64
            # Docker RepoDigests omits the tag even when pulled as version@digest.
            info['RepoDigests'] = ['example@sha256:' + 'a'*64]
            with self.assertRaisesRegex(ValueError, 'Unqualified platform'):
                image_evidence(ref, inputs)
            packages[1] = b'libssl3-3.5.4-r1\n'
            with self.assertRaisesRegex(ValueError, 'runtime packages'):
                image_evidence('candidate:local', inputs, require_registry=False)
            packages[0] = packages[1]
            refreshed = image_evidence('candidate:local', inputs, require_registry=False)
            self.assertNotEqual(evidence['inventories_sha256']['runtime-packages.txt'],
                                refreshed['inventories_sha256']['runtime-packages.txt'])
            for name, bad in [('org.opencontainers.image.revision', 'a' * 40),
                              ('org.opencontainers.image.version', '0.0'),
                              ('io.tg-selfhost.privacy-policy', 'missing'),
                              ('io.tg-selfhost.tdlib-revision', 'a' * 40),
                              ('io.tg-selfhost.wrapper-revision', 'a' * 40)]:
                old = labels[name]
                labels[name] = bad
                with self.subTest(name=name), self.assertRaises(ValueError):
                    image_evidence('candidate:local', inputs, require_registry=False)
                labels[name] = old
            info['Architecture'] = 'arm64'
            with self.assertRaises(ValueError):
                image_evidence('candidate:local', inputs, require_registry=False)

    def test_gateway_strict_root_contract(self):
        def response(code, media, body):
            headers = Message()
            headers['Content-Type'] = media
            return urllib.error.HTTPError('http://localhost/', code, 'synthetic', headers, io.BytesIO(body))

        for code, media, body, passes in [
                (404, 'application/json; charset=utf-8', b'{"ok":false,"error_code":404,"description":"Not Found"}', True),
                (404, 'application/json', b'{"ok":false,"error_code":404}', True),
                (200, 'application/json', b'{"ok":false,"error_code":404}', False),
                (302, 'application/json', b'{}', False), (404, 'text/html', b'404', False),
                (404, 'application/json', b'{"ok":false,"error_code":"404"}', False),
                (404, 'application/json', b'[]', False),
                (404, 'application/json', b' ' * 16385, False)]:
            with self.subTest(code=code, media=media, passes=passes), patch('check_release.urllib.request.build_opener') as opener:
                opener.return_value.open.side_effect = response(code, media, body)
                if passes:
                    check_gateway('http://localhost/')
                else:
                    with self.assertRaises(ValueError):
                        check_gateway('http://localhost/')
        for url in ('http://localhost/botSECRET/getMe', 'http://user:secret@localhost/', 'http://localhost/?token=x'):
            with self.assertRaises(ValueError):
                check_gateway(url)

    def test_registry_not_found_is_not_an_auth_or_transport_error(self):
        for error in ('denied', 'unauthorized: manifest unknown', 'timeout', 'connection refused', 'invalid json',
                      'manifest unknown: deadline exceeded', 'manifest unknown: 429 rate limit'):
            result = subprocess.CompletedProcess([], 1, '', error)
            with self.subTest(error=error), patch('check_release.subprocess.run', return_value=result), self.assertRaises(ValueError):
                registry_lookup('example:build')
        result = subprocess.CompletedProcess([], 1, '', 'manifest unknown')
        with patch('check_release.subprocess.run', return_value=result):
            self.assertIsNone(registry_lookup('example:build'))
        digest = 'sha256:' + 'a' * 64
        with patch('check_release.subprocess.run', return_value=subprocess.CompletedProcess([], 0, json.dumps({'digest': digest}), '')):
            self.assertEqual(registry_lookup('example:build'), digest)

    def test_incomplete_or_foreign_receipt_prevents_reuse_before_docker(self):
        with patch('check_release.image_evidence') as inspect:
            with self.assertRaises(ValueError):
                verify_reuse('example@sha256:' + 'a' * 64, {}, b'{}')
            inspect.assert_not_called()
