"""Offline guards for both independent production installation layers."""
from pathlib import Path
import unittest
import tempfile
from capture_link_metadata import link_inputs

ROOT = Path(__file__).resolve().parents[1]


class DockerContractTests(unittest.TestCase):
    def test_only_final_executable_inputs_count_as_used_archives(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            final = root / 'build/CMakeFiles/telegram-bot-api.dir/link.txt'
            unrelated = root / 'build/CMakeFiles/unused.dir/link.txt'
            final.parent.mkdir(parents=True)
            unrelated.parent.mkdir(parents=True)
            (root / 'build/used.a').write_bytes(b'used')
            (root / 'build/unused.a').write_bytes(b'unused')
            final.write_text('cc -o telegram-bot-api used.a')
            unrelated.write_text('ar qc unused.a unused.o')
            commands, archives = link_inputs(root)
            self.assertEqual(len(commands), 2)
            self.assertEqual([p.name for p in archives.values()], ['used.a'])
            final.write_text('cc -o telegram-bot-api missing.a')
            with self.assertRaises(ValueError): link_inputs(root)

    def test_both_installations_use_refresh_and_upgrade(self):
        dockerfile = (ROOT / 'Dockerfile').read_text()
        for stage, following in [('build-deps', 'source'), ('runtime-deps', 'runtime')]:
            section = dockerfile.split(' AS ' + stage + '\n', 1)[1].split(' AS ' + following + '\n', 1)[0]
            self.assertLess(section.index('ARG APK_REFRESH_ID'), section.index('RUN '))
            self.assertNotIn('DEPENDENCY_EPOCH', section)
            self.assertLess(section.index('apk upgrade --no-cache'), section.index('apk add --no-cache'))
            self.assertIn('apk upgrade --no-cache', section)
            self.assertIn('sh /tmp/capture_apk_metadata.sh', section)
            self.assertNotIn('--allow-untrusted', section)
        self.assertIn('FROM build-deps AS source', dockerfile)
        self.assertIn('FROM runtime-deps AS runtime', dockerfile)

    def test_capture_keeps_base_packages_and_no_script_in_runtime(self):
        script = (ROOT / 'tools/capture_apk_metadata.sh').read_text()
        for value in ('/lib/apk/db/installed', '/etc/apk/repositories', 'apk --print-arch', 'apk --version'):
            self.assertIn(value, script)
        dockerfile = (ROOT / 'Dockerfile').read_text()
        self.assertIn('strip /usr/local/bin/telegram-bot-api', dockerfile)
        self.assertIn('capture_link_metadata.py', dockerfile)
        self.assertNotIn('COPY tools/', dockerfile)


if __name__ == '__main__':
    unittest.main()
