import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ENTRYPOINT = Path(__file__).resolve().parents[1] / "docker-entrypoint.sh"


@unittest.skipIf(os.name == "nt", "POSIX entrypoint tests require WSL or CI")
class EntrypointTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        binary = self.root / "telegram-bot-api"
        binary.write_text("#!/usr/bin/env python3\nimport json, os, sys\n"
                          "print(json.dumps(dict(args=sys.argv[1:], api_id=os.getenv('TELEGRAM_API_ID'), "
                          "api_hash=os.getenv('TELEGRAM_API_HASH'))))\n")
        binary.chmod(0o755)
        # Avoid real ownership changes; verify only the entrypoint's invocation contract.
        chown = self.root / "chown"
        chown.write_text("#!/bin/sh\nexit 0\n")
        chown.chmod(0o755)
        self.env = {**os.environ, "PATH": f"{self.root}:{os.environ['PATH']}",
                    "TELEGRAM_WORK_DIR": str(self.root / "state with spaces"),
                    "TELEGRAM_TEMP_DIR": str(self.root / "temp"),
                    "TELEGRAM_API_ID": "12345", "TELEGRAM_API_HASH": "synthetic-secret"}

    def run_script(self, *args):
        return subprocess.run(["sh", str(ENTRYPOINT), *args], env=self.env,
                              text=True, capture_output=True, timeout=10)

    def test_flags_and_paths_are_separate_arguments(self):
        marker = self.root / "injected"
        value = str(self.root / f"log $(touch {marker}).txt")
        self.env.update(TELEGRAM_LOCAL="true", TELEGRAM_STAT="false", TELEGRAM_LOG_FILE=value)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        actual = json.loads(result.stdout)
        self.assertIn("--local", actual["args"])
        self.assertNotIn("--http-stat-port=8082", actual["args"])
        self.assertIn(f"--log={value}", actual["args"])
        self.assertIn(f"--dir={self.env['TELEGRAM_WORK_DIR']}", actual["args"])
        self.assertFalse(marker.exists())

    def test_file_secret_is_read_without_logging_it(self):
        secret = self.root / "hash secret"
        secret.write_text("secret from file\n")
        self.env.pop("TELEGRAM_API_HASH")
        self.env["TELEGRAM_API_HASH_FILE"] = str(secret)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["api_hash"], "secret from file")
        self.assertEqual(result.stderr, "")

    def test_conflicting_secret_and_invalid_boolean_fail(self):
        self.env["TELEGRAM_API_HASH_FILE"] = "/unused"
        self.assertNotEqual(self.run_script().returncode, 0)
        self.env.pop("TELEGRAM_API_HASH_FILE")
        self.env["TELEGRAM_LOCAL"] = "invalid"
        self.assertNotEqual(self.run_script().returncode, 0)

    def test_version_runs_without_api_credentials(self):
        self.env.pop("TELEGRAM_API_HASH")
        self.env.pop("TELEGRAM_API_ID")
        result = self.run_script("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["args"], ["--version"])

    def test_split_storage_and_unsafe_overrides(self):
        media = str(self.root / "media with spaces")
        self.env["TELEGRAM_FILES_DIR"] = media
        result = self.run_script()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(1, json.loads(result.stdout)["args"].count("--files-dir=" + media))
        for name, value in (("TELEGRAM_FILES_DIR", self.env["TELEGRAM_WORK_DIR"] + "/nested"),
                            ("TELEGRAM_FILES_DIR", str(self.root) + "/../escape"),
                            ("TELEGRAM_TEMP_DIR", media + "/temp"),
                            ("TELEGRAM_LOG_FILE", "relative.log"),
                            ("TELEGRAM_API_HASH_FILE", media + "/secret")):
            before = self.env.copy(); self.env[name] = value
            self.assertNotEqual(0, self.run_script().returncode, name)
            self.env = before
        self.assertNotEqual(0, self.run_script("--local").returncode)
        self.assertNotEqual(0, self.run_script("--files-dir=" + media, "--files-dir=" + media).returncode)
        self.assertEqual(0, self.run_script("--version").returncode)
        self.env.pop("TELEGRAM_FILES_DIR")
        self.assertNotEqual(0, self.run_script("-f", media).returncode)
        self.assertNotEqual(0, self.run_script("-f" + media).returncode)

    def test_split_rejects_symlink_ancestor(self):
        link = self.root / "link"; link.symlink_to(self.root, target_is_directory=True)
        self.env["TELEGRAM_FILES_DIR"] = str(link / "media")
        self.assertNotEqual(0, self.run_script().returncode)


if __name__ == "__main__":
    unittest.main()
