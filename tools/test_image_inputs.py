import unittest
from unittest.mock import patch
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from image_inputs import RECIPE, ROOT, build_key, digest, revision


class BuildInputsTest(unittest.TestCase):
    def test_acceptance_inputs_invalidate_old_qualification(self):
        required = {"docker-compose.nonroot.yml", "docker-compose.files.yml",
                    "tools/check_nonroot.py", "tools/check_nonroot_compose.py",
                    "tools/test_check_nonroot.py", "tools/test_nonroot_compose.py"}
        required.update(p.relative_to(ROOT).as_posix() for p in (ROOT / "tools/fixtures/nonroot").rglob("*") if p.is_file())
        self.assertTrue(required <= set(RECIPE))
        files = {name: (ROOT / name).read_bytes() for name in RECIPE}
        original = build_key({}, files)
        for name in required:
            with self.subTest(name=name):
                self.assertNotEqual(original, build_key({}, {**files, name: files[name] + b"\nchanged"}))

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
