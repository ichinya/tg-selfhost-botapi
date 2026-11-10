import unittest
from unittest.mock import patch
import check_apk_refresh as refresh


class RefreshTests(unittest.TestCase):
    def test_fixture_repository_layout(self):
        script = (refresh.FIXTURE / 'package.sh').read_text()
        repo = '/work/repo-v$version/x86_64'
        self.assertIn('mkdir -p ' + repo, script)
        self.assertIn(' -o ' + repo + '/APKINDEX.tar.gz ' + repo + '/*.apk', script)
        self.assertIn('abuild-sign -k /work/issue23.rsa ' + repo + '/APKINDEX.tar.gz', script)
        self.assertIn('issue23-fixture-$version-r0.apk ' + repo + '/', script)

    def test_fixture_hashes(self):
        self.assertEqual(len(refresh.verify_fixture()), 5)

    def test_transformation_preserves_keyed_production_run(self):
        recipe = (refresh.ROOT / 'Dockerfile').read_text()
        fixture = refresh.transform(recipe, 'http://host.docker.internal:12345/current')
        self.assertEqual(fixture.count('apk upgrade --no-cache'), 2)
        self.assertEqual(fixture.count('apk add --no-cache issue23-fixture'), 2)
        for stage in ('build-deps', 'runtime-deps'):
            section = fixture.split(' AS ' + stage + '\n')[1]
            self.assertLess(section.index('apk add --no-cache issue23-fixture'), section.index('ARG APK_REFRESH_ID'))
        self.assertNotIn('--allow-untrusted', fixture)
        self.assertIn('cc -static', fixture)
        self.assertIn('COPY --from=build-deps /tmp/issue23-dynamic', fixture)
        for line in recipe.splitlines():
            if 'apk add --no-cache' in line:
                self.assertNotIn('issue23-fixture', line)

    def test_structure_drift_fails_closed(self):
        with self.assertRaises(ValueError): refresh.transform('FROM alpine', 'http://example.invalid')

    def test_cache_log_must_identify_both_result_and_stage(self):
        prefix = '#12 [build-deps 3/5] RUN --mount=type=bind,target=/tmp/capture_apk_metadata.sh command\n'
        self.assertTrue(refresh.installation_cached(prefix + '#12 CACHED\n', 'build-deps'))
        self.assertFalse(refresh.installation_cached(prefix + '#12 DONE 1.0s\n', 'build-deps'))
        with self.assertRaises(ValueError): refresh.installation_cached(prefix, 'build-deps')
        with self.assertRaises(ValueError): refresh.installation_cached(prefix + '#12 CACHED\n', 'runtime-deps')

    def test_each_negative_control_removes_only_its_own_refresh_consumption(self):
        recipe = refresh.transform((refresh.ROOT / 'Dockerfile').read_text(), 'http://host.docker.internal:12345/current')
        for stage in ('build-deps', 'runtime-deps'):
            broken = refresh.remove_refresh_consumption(recipe, stage, 'v1-2026-11-10-g0')
            self.assertEqual(broken.count('ARG APK_REFRESH_ID\n'), recipe.count('ARG APK_REFRESH_ID\n') - 1)
            section = broken.split(' AS ' + stage + '\n')[1].split('\nFROM ')[0]
            self.assertNotIn('$APK_REFRESH_ID', section)
            self.assertIn('apk upgrade --no-cache', section)

    def test_import_has_no_docker_side_effects(self):
        import importlib
        with patch('subprocess.run') as command:
            importlib.reload(refresh)
            command.assert_not_called()


if __name__ == '__main__':
    unittest.main()
