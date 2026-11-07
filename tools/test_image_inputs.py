import unittest
from unittest.mock import patch
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from image_inputs import build_key, digest, revision, downloads_key, python_image, RECIPE, DOWNLOADS_RECIPE, ROOT


class BuildInputsTest(unittest.TestCase):
    def test_fingerprints_cover_existing_inputs_and_the_gate(self):
        for recipe in (RECIPE, DOWNLOADS_RECIPE):
            self.assertEqual(len(recipe), len(set(recipe)))
            for name in recipe:
                with self.subTest(name=name):
                    self.assertTrue((ROOT / name).is_file())
            for name in ('docker-entrypoint.sh', '.github/workflows/file-contract.yml',
                         'tools/file_access.py', 'tools/fixtures/files/mock_botapi.py',
                         'tools/check_docs.py', '.dockerignore'):
                self.assertIn(name, recipe)

    def test_downloads_key_and_python_base_are_fail_closed(self):
        self.assertNotEqual(downloads_key({}, {'a': b'1'}), downloads_key({}, {'a': b'2'}))
        self.assertNotEqual(build_key({}, {}), downloads_key({}, {}))
        with patch('image_inputs.digest', return_value='sha256:' + 'a' * 64):
            self.assertEqual(python_image(), 'python:3.12-alpine@sha256:' + 'a' * 64)
        with self.assertRaises(ValueError):
            python_image('python:3.12-alpine@sha256:invalid')

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
