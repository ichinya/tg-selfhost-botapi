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
                          "assert sys.argv[1:] in (['--version'], ['--help']) or (os.getenv('TELEGRAM_API_ID') == os.getenv('EXPECTED_ID') and os.getenv('TELEGRAM_API_HASH') == os.getenv('EXPECTED_HASH'))\n"
                          "print(json.dumps(dict(args=sys.argv[1:], checked=True)))\n")
        binary.chmod(0o755)
        # Avoid real ownership changes; verify only the entrypoint's invocation contract.
        chown = self.root / "chown"
        chown.write_text("#!/bin/sh\necho chown >> \"$CALL_LOG\"\n[ \"${FAKE_UID:-1000}\" = 0 ]\n")
        chown.chmod(0o755)
        identity = self.root / "id"
        identity.write_text('#!/bin/sh\ncase "$1" in -u) echo "${FAKE_UID:-1000}";; -g) echo "${FAKE_GID:-1000}";; *) exit 1;; esac\n')
        identity.chmod(0o755)
        drop = self.root / "su-exec"
        drop.write_text('#!/bin/sh\necho su-exec >> "$CALL_LOG"\n[ "${FAKE_UID:-1000}" = 0 ] && [ "$1" = 101:101 ] && [ "$2" = /docker-entrypoint.sh ] && [ "$#" = 2 ] || exit 1\nexport FAKE_UID=101 FAKE_GID=101\nexec sh "$ENTRYPOINT"\n')
        drop.chmod(0o755)
        self.env = {**os.environ, "PATH": f"{self.root}:{os.environ['PATH']}",
                    "ENTRYPOINT": str(ENTRYPOINT), "CALL_LOG": str(self.root / "calls"),
                    "TELEGRAM_WORK_DIR": str(self.root / "state with spaces"),
                    "TELEGRAM_TEMP_DIR": str(self.root / "temp"),
                    "TELEGRAM_API_ID": "12345", "TELEGRAM_API_HASH": "synthetic-secret",
                    "EXPECTED_ID": "12345", "EXPECTED_HASH": "synthetic-secret"}

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
        self.assertFalse(any(arg.startswith(("--username=", "--groupname=")) for arg in actual["args"]))
        self.assertFalse((self.root / "calls").exists())
        self.assertFalse(marker.exists())

    def test_file_secret_is_read_without_logging_it(self):
        secret = self.root / "hash secret"
        secret.write_text("secret from file\n")
        self.env.pop("TELEGRAM_API_HASH")
        self.env["TELEGRAM_API_HASH_FILE"] = str(secret)
        self.env["EXPECTED_HASH"] = "secret from file"
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["checked"])
        self.assertNotIn("secret from file", result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")

    def test_conflicting_secret_and_invalid_boolean_fail(self):
        self.env["TELEGRAM_API_HASH_FILE"] = "/unused"
        self.assertNotEqual(self.run_script().returncode, 0)
        self.env.pop("TELEGRAM_API_HASH_FILE")
        self.env["TELEGRAM_LOCAL"] = "invalid"
        self.assertNotEqual(self.run_script().returncode, 0)

    def test_both_files_and_file_errors(self):
        for name, value in (("ID", "12345"), ("HASH", "synthetic-secret")):
            path = self.root / name
            path.write_text(value + "\n")
            self.env.pop("TELEGRAM_API_" + name)
            self.env["TELEGRAM_API_" + name + "_FILE"] = str(path)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("synthetic-secret", result.stdout + result.stderr)
        (self.root / "ID").write_text("")
        self.assertNotEqual(self.run_script().returncode, 0)
        self.env["TELEGRAM_API_ID_FILE"] = str(self.root / "missing-private-path")
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("missing-private-path", result.stderr)

    def test_version_runs_without_api_credentials(self):
        self.env.pop("TELEGRAM_API_HASH")
        self.env.pop("TELEGRAM_API_ID")
        result = self.run_script("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["args"], ["--version"])

    def test_help_ignores_credentials_and_unsafe_storage(self):
        for name in ('TELEGRAM_API_HASH', 'TELEGRAM_API_ID', 'TELEGRAM_WORK_DIR', 'TELEGRAM_TEMP_DIR'):
            self.env.pop(name)
        self.env['TELEGRAM_FILES_DIR'] = '/'
        result = self.run_script('--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['args'], ['--help'])

    def test_nonregular_secret_fails_without_reading_or_disclosing_path(self):
        fifo = self.root / "private-fifo-canary"
        os.mkfifo(fifo)
        self.env.pop("TELEGRAM_API_ID")
        for path in (fifo, self.root):
            self.env["TELEGRAM_API_ID_FILE"] = str(path)
            result = self.run_script()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("TELEGRAM_API_ID_FILE", result.stderr)
            self.assertNotIn(str(path), result.stdout + result.stderr)
            self.assertNotIn('"checked"', result.stdout)

    def test_root_reexec_and_existing_contents(self):
        self.env['FAKE_UID'] = '0'
        state = Path(self.env['TELEGRAM_WORK_DIR'])
        state.mkdir()
        (state / '.existing').write_text('keep')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((state / '.existing').read_text(), 'keep')
        self.assertEqual((self.root / 'calls').read_text().splitlines(), ['chown', 'su-exec'])

    def test_files_dir_and_overlapping_roots(self):
        media = str(self.root / 'media with spaces')
        self.env['TELEGRAM_FILES_DIR'] = media
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--files-dir=' + media, json.loads(result.stdout)['args'])
        self.env['TELEGRAM_FILES_DIR'] = self.env['TELEGRAM_WORK_DIR'] + '/nested'
        self.assertNotEqual(self.run_script().returncode, 0)
    def test_statistics_loopback_and_port_conflicts(self):
        self.env['TELEGRAM_STAT'] = 'true'
        result = self.run_script()
        self.assertEqual(result.returncode, 0)
        self.assertIn('--http-stat-ip-address=127.0.0.1', json.loads(result.stdout)['args'])
        for port in ['8082', '8090', '08082', '08090', '65536', 'invalid']:
            self.env['TELEGRAM_HTTP_PORT'] = port
            self.assertNotEqual(self.run_script().returncode, 0)
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
