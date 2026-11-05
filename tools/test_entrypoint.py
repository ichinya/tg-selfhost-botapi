import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ENTRYPOINT = Path(__file__).resolve().parents[1] / "docker-entrypoint.sh"


@unittest.skipUnless(os.name == "posix", "entrypoint contract requires POSIX")
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
        chown.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CHOWN_LOG"\n'
                         '[ "$TEST_UID" = 0 ]\n')
        chown.chmod(0o755)
        identity = self.root / "id"
        identity.write_text('#!/bin/sh\ncase "$1" in -u) echo "$TEST_UID" ;; '
                            '-g) echo "$TEST_GID" ;; *) exit 1 ;; esac\n')
        identity.chmod(0o755)
        self.env = {**os.environ, "PATH": f"{self.root}:{os.environ['PATH']}",
                    "TEST_UID": "0", "TEST_GID": "0", "CHOWN_LOG": str(self.root / "chown.log"),
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

    def test_identity_branch_and_chown(self):
        for uid, gid in (("0", "0"), ("101", "101"), ("1000", "1000"), ("1000", "2000")):
            with self.subTest(uid=uid, gid=gid):
                self.env.update(TEST_UID=uid, TEST_GID=gid)
                log = Path(self.env["CHOWN_LOG"])
                log.unlink(missing_ok=True)
                result = self.run_script()
                self.assertEqual(result.returncode, 0, result.stderr)
                args = json.loads(result.stdout)["args"]
                self.assertEqual("--username=telegram-bot-api" in args, uid == "0")
                self.assertEqual("--groupname=telegram-bot-api" in args, uid == "0")
                if uid == "0":
                    self.assertEqual(log.read_text().splitlines(), [
                        "telegram-bot-api:telegram-bot-api " + self.env["TELEGRAM_WORK_DIR"],
                        "telegram-bot-api:telegram-bot-api " + self.env["TELEGRAM_TEMP_DIR"]])
                else:
                    self.assertFalse(log.exists())

    def test_cli_bypasses_preparation(self):
        self.env.pop("TELEGRAM_API_ID")
        self.env.pop("TELEGRAM_API_HASH")
        for flag in ("--version", "--help"):
            result = self.run_script(flag)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(Path(self.env["TELEGRAM_WORK_DIR"]).exists())
            self.assertFalse(Path(self.env["CHOWN_LOG"]).exists())

    def test_directory_creation_failure_names_path_and_identity(self):
        self.env.update(TEST_UID="1000", TEST_GID="2000")
        for key in ("TELEGRAM_WORK_DIR", "TELEGRAM_TEMP_DIR"):
            with self.subTest(path=key):
                parent = self.root / (key + " file")
                parent.write_text("not a directory")
                self.env[key] = str(parent / "child")
                result = self.run_script()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(self.env[key], result.stderr)
                self.assertIn("1000:2000", result.stderr)
                self.env[key] = str(self.root / (key + " restored"))


if __name__ == "__main__":
    unittest.main()
