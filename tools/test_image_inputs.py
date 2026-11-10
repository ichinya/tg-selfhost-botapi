from datetime import datetime, timezone, timedelta
import io
import json
import tempfile
from contextlib import redirect_stdout
import unittest
from unittest.mock import patch
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from image_inputs import build_key, digest, revision, resolve, validate_policy, check_generation, main


class BuildInputsTest(unittest.TestCase):
    def test_compose_optional_public_inputs(self):
        root = Path(__file__).resolve().parents[1]
        override = (root / 'docker-compose.build.yml').read_text()
        for key in ('APK_REFRESH_ID', 'BOT_API_REVISION', 'ALPINE_IMAGE', 'BUILD_FINGERPRINT', 'BUILD_PLATFORM'):
            self.assertIn('${' + key + ':-', override)
        self.assertNotIn('DEPENDENCY_EPOCH', override)
        self.assertNotIn('alpine:3.22', override)
        self.assertNotIn('APK_REFRESH_ID', (root / 'docker-compose.yml').read_text())
        self.assertIn('/.env.build', (root / '.gitignore').read_text())

    def test_cli_outputs_share_one_snapshot_and_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            output, env = Path(folder) / 'inputs.json', Path(folder) / 'build.env'
            env.write_text('OLD_SECRET=must-disappear')
            stdout = io.StringIO()
            with patch.object(sys, 'argv', ['image_inputs.py', '--json-out', str(output), '--build-env-out', str(env)]), patch('image_inputs.revision', return_value='a' * 40) as source, patch('image_inputs.digest', return_value='sha256:' + 'b' * 64) as base, redirect_stdout(stdout):
                main()
            snapshot = json.loads(output.read_text())
            self.assertEqual(dict(line.split('=', 1) for line in stdout.getvalue().splitlines()), {k: str(v) for k, v in snapshot.items()})
            values = dict(line.split('=', 1) for line in env.read_text().splitlines())
            mapping = {'APK_REFRESH_ID':'apk_refresh_id', 'BUILD_FINGERPRINT':'build_key',
                       'BOT_API_REVISION':'bot_api_revision', 'ALPINE_IMAGE':'alpine_image',
                       'APK_POLICY_VERSION':'policy_version', 'APK_REFRESH_WINDOW':'apk_refresh_window',
                       'APK_REFRESH_GENERATION':'generation', 'BUILD_PLATFORM':'platform'}
            self.assertEqual(values, {key: str(snapshot[value]) for key, value in mapping.items()})
            source.assert_called_once()
            base.assert_called_once()

    def test_cli_failure_emits_no_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'inputs.json'
            stdout = io.StringIO()
            with patch.object(sys, 'argv', ['image_inputs.py', '--json-out', str(output)]), patch('image_inputs.revision', side_effect=TimeoutError), redirect_stdout(stdout), self.assertRaises(TimeoutError):
                main()
            self.assertEqual(stdout.getvalue(), '')
            self.assertFalse(output.exists())

    @patch("image_inputs.digest", return_value="sha256:" + "a" * 64)
    @patch("image_inputs.revision", return_value="b" * 40)
    def test_refresh_identity_and_clock(self, revision_mock, digest_mock):
        policy = {"policy_version": 1, "refresh": "utc-day", "generation": 0}
        calls = []
        def clock():
            calls.append(1)
            return datetime(2026, 1, 2, 1, tzinfo=timezone(timedelta(hours=2)))
        first = resolve(clock, policy)
        self.assertEqual(len(calls), 1)
        self.assertEqual(first["apk_refresh_id"], "v1-2026-01-01-g0")
        same = resolve(lambda: datetime(2026, 1, 1, 23, tzinfo=timezone.utc), policy)
        self.assertEqual(first, same)
        for other in (resolve(lambda: datetime(2026, 1, 2, tzinfo=timezone.utc), policy),
                      resolve(clock, {**policy, "generation": 1}),
                      resolve(clock, policy, "linux/arm64")):
            self.assertNotEqual(first["build_key"], other["build_key"])
        with self.assertRaises(ValueError):
            resolve(lambda: datetime(2026, 1, 1), policy)

    def test_policy_validation_and_downgrade(self):
        good = {"policy_version": 1, "refresh": "utc-day", "generation": 0}
        for bad in ({}, {**good, "generation": True}, {**good, "generation": -1},
                    {**good, "policy_version": 2}, {**good, "extra": 1},
                    {**good, "refresh": "weekly"}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_policy(bad)
        check_generation(good, None)
        with self.assertRaises(ValueError):
            check_generation(good, {**good, "generation": 1})

    def test_any_upstream_change_invalidates_published_build(self):
        inputs = dict(source="a", base="b")
        files = {"Dockerfile": b"recipe", "patch": b"header"}
        original = build_key(inputs, files)
        for key in inputs:
            with self.subTest(key=key):
                self.assertNotEqual(original, build_key({**inputs, key: "changed"}, files))
        self.assertNotEqual(original, build_key(inputs, {**files, "patch": b"new header"}))

    def test_order_does_not_force_a_rebuild(self):
        self.assertEqual(build_key(dict(a=1, b=2), dict(x=b"x", y=b"y")),
                         build_key(dict(b=2, a=1), dict(y=b"y", x=b"x")))

    def test_recipe_file_boundaries_are_significant(self):
        self.assertNotEqual(build_key({}, {"a": b"bc"}), build_key({}, {"ab": b"c"}))

    def test_invalid_upstream_values_fail_closed(self):
        with patch("image_inputs.command", return_value="not-a-sha\trefs/heads/master"):
            with self.assertRaises(ValueError):
                revision("tdlib/telegram-bot-api")
        with patch("image_inputs.command", return_value='{"digest": "latest"}'):
            with self.assertRaises(ValueError):
                digest("alpine:3.22")

    def test_network_failure_does_not_produce_new_inputs(self):
        with patch("image_inputs.command", side_effect=TimeoutError("registry timeout")):
            with self.assertRaises(TimeoutError):
                digest("alpine:3.22")


if __name__ == "__main__":
    unittest.main()
