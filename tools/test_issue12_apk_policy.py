import copy
import unittest
from unittest.mock import patch
from image_inputs import ROOT, build_key, resolve, read_policy


class ApkPolicyTest(unittest.TestCase):
    def test_cleanup_failure_does_not_mask_stale_layer(self):
        from subprocess import CalledProcessError, CompletedProcess
        from check_apk_refresh import check
        def run(args, **kwargs):
            code = 1 if args[:3] == ['docker', 'image', 'rm'] else 0
            if code and kwargs.get('check'):
                raise CalledProcessError(code, args)
            return CompletedProcess(args, code)
        with patch('check_apk_refresh.subprocess.run', side_effect=run), \
             patch('check_apk_refresh.run', side_effect=[b'config', b'stale']):
            with self.assertRaisesRegex(ValueError, 'Stale warm-cache apk layer'):
                check(resolve())

    def test_locked_replay_ignores_clock(self):
        with patch('image_inputs.datetime') as clock:
            self.assertEqual(resolve(), resolve())
            clock.now.assert_not_called()

    def test_refresh_changes_identity_with_same_source_and_base(self):
        original = resolve()
        identity = {k: v for k, v in original.items() if k not in ('build_key', 'submodules_arg')}
        before = build_key(identity, {})
        for field, new in (('apk_refresh_window', '2026-11-09'), ('apk_refresh_generation', 1)):
            self.assertNotEqual(before, build_key({**identity, field: new}, {}))
        policy = copy.deepcopy(identity)
        policy['apk_policy']['generation'] += 1
        self.assertNotEqual(before, build_key(policy, {}))

    def test_package_layers_consume_refresh_before_apk(self):
        text = (ROOT / 'Dockerfile').read_text()
        layers = [part for part in text.split('\nRUN ') if 'apk upgrade' in part]
        self.assertEqual(len(layers), 2)
        for layer in layers:
            self.assertLess(layer.index('$APK_REFRESH_ID'), layer.index('apk upgrade'))
            self.assertIn('apk add --no-cache', layer)
            self.assertIn('apk --version', layer)
            self.assertIn('apk --print-arch', layer)
        self.assertEqual(read_policy()['stable_branch'], '3.22')


if __name__ == '__main__':
    unittest.main()
