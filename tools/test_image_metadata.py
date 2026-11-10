import unittest
from image_metadata import parse_installed, validate_packages


class InventoryTests(unittest.TestCase):
    def test_inventory_and_architecture(self):
        packages = parse_installed('P:zlib\nV:1.3.1-r2\nA:x86_64\no:zlib\n\nP:base\nV:1-r0\nA:noarch\n')
        self.assertEqual(packages[1]['version'], '1.3.1-r2')
        validate_packages(packages, {'zlib'}, 'x86_64')
        with self.assertRaises(ValueError):
            validate_packages(packages, {'zlib'}, 'aarch64')
        with self.assertRaises(ValueError):
            validate_packages(packages, {'absent'}, 'x86_64')

    def test_rejects_bad_inventory(self):
        for text in ('', 'P:x\nV:1\nA:x86_64', 'P:x\nV:1-r0',
                     'P:x\nV:1-r0\nA:x86_64\n\nP:x\nV:1-r0\nA:x86_64', 'bad'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_installed(text)


if __name__ == '__main__':
    unittest.main()

class ReceiptTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.inputs = {'build_key': 'key', 'bot_api_revision': 'rev', 'apk_refresh_id': 'refresh',
                       'alpine_image': 'alpine:3.22@sha256:' + 'a' * 64,
                       'policy_version': 1, 'apk_refresh_window': '2026-11-05',
                       'generation': 0, 'platform': 'linux/amd64'}
        names = [('build-key', 'build_key'), ('bot-api-revision', 'bot_api_revision'),
                 ('apk-refresh-id', 'apk_refresh_id'), ('apk-policy-version', 'policy_version'),
                 ('apk-refresh-window', 'apk_refresh_window'), ('apk-refresh-generation', 'generation'),
                 ('platform', 'platform')]
        self.labels = {'io.tg-selfhost.' + label: str(self.inputs[key]) for label, key in names}
        self.inspect = {'Config': {'Labels': self.labels}, 'Os': 'linux', 'Architecture': 'amd64', 'Id': 'config'}
        for stage, packages in [('build', ['alpine-sdk', 'linux-headers', 'git', 'zlib-dev', 'openssl-dev', 'gperf', 'cmake']),
                                ('runtime', ['openssl', 'libstdc++'])]:
            path = self.root / stage
            path.mkdir()
            for name, contents in [('refresh-id', 'refresh'), ('repositories', 'repo'), ('apk-version', 'apk 2'),
                                   ('installed', '\n\n'.join(f'P:{n}\nV:1-r0\nA:x86_64' for n in packages))]:
                (path / name).write_text(contents)
            (path / 'schema').write_text('1')
            (path / 'arch').write_text('x86_64')
            (path / 'world').write_text('openssl\n')
            (path / 'alpine-release').write_text('3.22.0\n')
            (path / 'repositories').write_text('https://dl-cdn.alpinelinux.org/alpine/v3.22/main\nhttps://dl-cdn.alpinelinux.org/alpine/v3.22/community\n')
        (self.root / 'actual-installed').write_bytes((self.root / 'runtime/installed').read_bytes())
        import hashlib
        (self.root / 'telegram-bot-api').write_bytes(b'binary')
        for name, contents in [('binary.sha256', hashlib.sha256(b'binary').hexdigest()),
                               ('link-commands.txt', 'cc /lib/archive.a'), ('dynamic.txt', '(NEEDED) libc'),
                               ('static-archives.txt', '[{"path":"/lib/archive.a","sha256":"' + 'a' * 64 + '","owner":"git-1-r0"}]')]:
            (self.root / 'build' / name).write_text(contents)
        (self.root / 'build/pre-strip.sha256').write_text('c' * 64 + '  /usr/local/bin/telegram-bot-api')
        (self.root / 'build/link-map.txt').write_text('/lib/archive.a(object.o)')
        (self.root / 'build/build-facts.json').write_text('{"source_revision":"rev","compiler":"cc","cmake":"cmake","linker":"ld","cmake_cache":"Release"}')
        self.write_compile_record()
        import hashlib
        from image_metadata import library_capture_name
        (self.root / 'runtime-libraries').mkdir()
        (self.root / 'runtime-libraries' / library_capture_name('/lib/test.so')).write_bytes(b'library')

    def write_compile_record(self):
        import json
        import hashlib
        stage = self.root / 'build'
        if not (stage / 'dynamic-owners.json').exists():
            (stage / 'dynamic-owners.json').write_text('[{"path":"/lib/test.so","sha256":"' + hashlib.sha256(b'library').hexdigest() + '","owner":"openssl-1-r0"}]')
        # The runtime closure must also be present in the build inventory.
        installed = stage / 'installed'
        if 'P:openssl\n' not in installed.read_text():
            installed.write_text(installed.read_text() + '\n\nP:openssl\nV:1-r0\nA:x86_64\n')
        record = {'schema': 1, 'binary_sha256': hashlib.sha256(b'binary').hexdigest(),
                  'source_submodules': 'abc td', 'inputs': dict(BOT_API_REVISION='rev',
                  ALPINE_IMAGE=self.inputs['alpine_image'], BUILD_FINGERPRINT='key', APK_REFRESH_ID='refresh', TARGETPLATFORM='linux/amd64'),
                  'hashes': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in stage.iterdir() if p.name != 'compile-receipt.json'}}
        (stage / 'compile-receipt.json').write_text(json.dumps(record))

    def check_receipt(self):
        import json
        from unittest.mock import patch
        from image_metadata import receipt
        with patch('image_metadata.docker', return_value=json.dumps([self.inspect])), patch('image_metadata.extract_image'):
            return receipt('candidate', self.inputs, self.root)

    def test_archive_link_input_and_map(self):
        import json
        stage = self.root / 'build'
        archive = '/usr/lib/libdl.a'
        (stage / 'static-archives.txt').write_text(json.dumps([{'path': archive, 'sha256': 'a' * 64, 'owner': 'git-1-r0'}]))
        (stage / 'link-map.txt').write_text(archive + '(object.o)')
        for command in ('cc -ldl -o telegram-bot-api', 'cc ' + archive + ' -o telegram-bot-api'):
            with self.subTest(command=command):
                (stage / 'link-commands.txt').write_text(command)
                self.write_compile_record()
                self.assertEqual(self.check_receipt()['static_ownership'][0]['path'], archive)
        (stage / 'link-commands.txt').write_text('cc -lother -o telegram-bot-api')
        self.write_compile_record()
        with self.assertRaisesRegex(ValueError, 'Archive is not tied'):
            self.check_receipt()

    def test_negative_evidence(self):
        self.assertEqual('/lib/archive.a', self.check_receipt()['static_ownership'][0]['path'])
        for label in ('io.tg-selfhost.build-key', 'io.tg-selfhost.apk-refresh-id', 'io.tg-selfhost.apk-refresh-window', 'io.tg-selfhost.apk-refresh-generation'):
            original = self.labels[label]
            self.labels[label] = 'wrong'
            with self.assertRaises(ValueError): self.check_receipt()
            self.labels[label] = original
        self.inspect['Architecture'] = 'arm64'
        with self.assertRaises(ValueError): self.check_receipt()
        self.inspect['Architecture'] = 'amd64'
        (self.root / 'build' / 'refresh-id').write_text('wrong')
        with self.assertRaises(ValueError): self.check_receipt()
        (self.root / 'build' / 'refresh-id').write_text('refresh')
        (self.root / 'telegram-bot-api').write_bytes(b'changed')
        with self.assertRaises(ValueError): self.check_receipt()
        (self.root / 'telegram-bot-api').write_bytes(b'binary')
        (self.root / 'build' / 'link-commands.txt').unlink()
        with self.assertRaises(FileNotFoundError): self.check_receipt()

    def test_cleanup_failure_is_not_suppressed(self):
        import subprocess
        from unittest.mock import patch
        from image_metadata import extract_image
        with patch('image_metadata.docker', return_value='a' * 64), patch('image_metadata.subprocess.run', side_effect=[None, None, None, None, subprocess.CalledProcessError(1, 'rm')]):
            with self.assertRaises(subprocess.CalledProcessError):
                extract_image('candidate', self.root)

    def test_rejects_runtime_database_tampering(self):
        (self.root / 'actual-installed').write_text('changed')
        with self.assertRaises(ValueError): self.check_receipt()

    def test_rejects_compile_hash_tampering(self):
        (self.root / 'build/dynamic.txt').write_text('(NEEDED) changed')
        with self.assertRaises(ValueError): self.check_receipt()

    def test_rejects_legacy_missing_inventory(self):
        (self.root / 'build/installed').unlink()
        with self.assertRaises(FileNotFoundError): self.check_receipt()

    def test_rejects_unstable_repository(self):
        (self.root / 'runtime/repositories').write_text('https://dl-cdn.alpinelinux.org/alpine/edge/main')
        with self.assertRaises(ValueError): self.check_receipt()

    def test_rejects_unowned_archive_even_with_consistent_hashes(self):
        (self.root / 'build/static-archives.txt').write_text('[{"path":"/lib/x.a","sha256":"' + 'a' * 64 + '","owner":"UNKNOWN"}]')
        self.write_compile_record()
        with self.assertRaises(ValueError): self.check_receipt()

    def test_rejects_final_library_hash_mismatch(self):
        from image_metadata import library_capture_name
        (self.root / 'runtime-libraries' / library_capture_name('/lib/test.so')).write_bytes(b'changed')
        with self.assertRaises(ValueError): self.check_receipt()
