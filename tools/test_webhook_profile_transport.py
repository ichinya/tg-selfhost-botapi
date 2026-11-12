"""Real helper/export subprocess matrix. Explicit POSIX requirements; no network outside loopback."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from tools.webhook_profile_http_mock import MockAPI

ROOT = Path(__file__).resolve().parents[1]
TOKEN, SECRET = "123:synthetic_token_for_tests_only", "Synthetic_secret_7"


@unittest.skipIf(os.name == "nt", "Real Bash/permissions gate requires non-root POSIX; verification deferred to CI/gates")
class ProfileTransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="profile-test-")
        self.addCleanup(self.tmp.cleanup)
        self.private = Path(self.tmp.name)
        self.token = self.private / "token"
        self.token.write_text(TOKEN)
        self.token.chmod(0o600)
        self.secret = self.private / "secret"
        self.secret.write_text(SECRET + "\n")
        self.secret.chmod(0o600)
        self.env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "TMPDIR", "LANG")}
        self.env.update(BOT_TOKEN_FILE=str(self.token), WEBHOOK_SECRET_MODE="provided",
                        WEBHOOK_SECRET_TOKEN_FILE=str(self.secret), WEBHOOK_IP_MODE="pinned",
                        WEBHOOK_IP_ADDRESS="203.0.113.7", WEBHOOK_ALLOWED_UPDATES='["message","callback_query"]',
                        WEBHOOK_MAX_CONNECTIONS="7", WEBHOOK_CERTIFICATE_MODE="none", NO_PROXY="127.0.0.1", no_proxy="127.0.0.1")

    def run_surface(self, api, export=False, **env):
        # The helper keeps a persistent reconciliation lock next to itself.
        # Independent scenarios must not share that diagnostic root.
        run_dir = Path(tempfile.mkdtemp(prefix="surface-", dir=self.private))
        script = run_dir / "helper.sh"
        if export:
            result = subprocess.run(["node", "tools/webhook_profile_ui_harness.cjs", "--export"], cwd=ROOT,
                                    text=True, capture_output=True, check=True, timeout=10)
            self.assertNotIn(TOKEN, result.stdout)
            self.assertNotIn(SECRET, result.stdout)
            script.write_text(result.stdout)
        else:
            shutil.copyfile(ROOT / "migrate_off_to_self.sh", script)
        config = {**self.env, "OFFICIAL_BOT_URL": api.base + "/source", "SELF_BOT_URL": api.base + "/target", **env}
        return subprocess.run(["bash", "-x", str(script)], cwd=run_dir,
                              env={key: value for key, value in config.items() if value is not None},
                              input="y\n", text=True, capture_output=True, timeout=20)

    def with_api(self, **kwargs):
        api = MockAPI(**kwargs)
        thread = api.start()
        def cleanup():
            api.shutdown()
            thread.join(5)
            api.server_close()
        self.addCleanup(cleanup)
        return api

    def test_bash_and_export_full_profile_both_encodings_and_private_argv(self):
        for exported in (False, True):
            for cert in (False, True):
                with self.subTest(exported=exported, certificate=cert):
                    env = {}
                    if cert:
                        certificate, key = self.private / "public.pem", self.private / "test-only.key"
                        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=localhost", "-keyout", str(key), "-out", str(certificate)], capture_output=True, check=True, timeout=15)
                        certificate.chmod(0o600)
                        env.update(WEBHOOK_CERTIFICATE_MODE="provided", WEBHOOK_CERTIFICATE_FILE=str(certificate))
                    # Audit the real curl arguments without placing the secret in them.
                    bindir = self.private / "bin"
                    bindir.mkdir(exist_ok=True)
                    wrapper = bindir / "curl"
                    audit = self.private / f"argv-{int(exported)}-{int(cert)}"
                    self.assertFalse(audit.exists(), "Each scenario must have its own curl audit")
                    wrapper.write_text('#!/bin/sh\nprintf "%s\\0" "$@" >> "$WP_CURL_AUDIT"\nexec "' + shutil.which("curl") + '" "$@"\n')
                    wrapper.chmod(0o700)
                    api = self.with_api()
                    result = self.run_surface(api, exported, **env, PATH=str(bindir) + os.pathsep + self.env["PATH"], WP_CURL_AUDIT=str(audit))
                    self.assertEqual(result.returncode, 0, result.stderr)
                    call = next(c for c in api.calls if c["method"] == "setWebhook")
                    self.assertEqual(call["fields"]["secret_token"], SECRET)
                    self.assertEqual(call["fields"]["max_connections"], "7")
                    self.assertEqual(json.loads(call["fields"]["allowed_updates"]), ["message", "callback_query"])
                    self.assertEqual("certificate" in call["files"], cert)
                    if cert:
                        self.assertEqual(call["files"]["certificate"], certificate.read_bytes())
                    for content in (result.stdout, result.stderr, audit.read_text()):
                        self.assertNotIn(SECRET, content)
                        self.assertNotIn(TOKEN, content)
                        self.assertNotIn("BEGIN CERTIFICATE", content)
                    argv = [arg.decode() for arg in audit.read_bytes().split(b'\0')[:-1]]
                    for index, arg in enumerate(argv[:-1]):
                        if arg == "--config":
                            self.assertFalse(Path(argv[index + 1]).parent.exists(), "Private temp directory was not cleaned")
                    calls = [(c["role"], c["method"]) for c in api.calls]
                    self.assertLess(calls.index(("source", "logOut")), calls.index(("target", "getMe")))
                    self.assertFalse(any(c["role"] == "source" for c in api.calls[calls.index(("source", "logOut")) + 1:]))

    def test_preflight_no_mutation_and_no_target_token_requests(self):
        for env in ({"WEBHOOK_SECRET_MODE": "unknown"}, {"WEBHOOK_IP_MODE": "unknown"},
                    {"WEBHOOK_ALLOWED_UPDATES": "null"}, {"WEBHOOK_MAX_CONNECTIONS": "100000"},
                    {"WEBHOOK_CERTIFICATE_MODE": "provided"}, {"WEBHOOK_SECRET_TOKEN": SECRET},
                    {"WEBHOOK_SECRET_TOKEN_FILE": ""}, {"WEBHOOK_SECRET_MODE": "none"}):
            for exported in (False, True):
                with self.subTest(env=list(env), exported=exported):
                    api = self.with_api()
                    result = self.run_surface(api, exported, **env)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(any(c["method"] in ("deleteWebhook", "logOut", "setWebhook") for c in api.calls))
                    self.assertFalse(any(c["role"] == "target" and c["method"] != "probe" for c in api.calls))

    def test_http_api_unknown_stop_before_dependent_steps(self):
        for method in ("source:deleteWebhook", "source:logOut", "target:setWebhook"):
            for kind in ("http", "api", "false-result", "malformed", "lost"):
                with self.subTest(method=method, kind=kind):
                    api = self.with_api(failure=(method, kind))
                    result = self.run_surface(api)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn(SECRET, result.stdout + result.stderr)
                    calls = [(c["role"], c["method"]) for c in api.calls]
                    self.assertEqual(calls.count(tuple(method.split(":"))), 1)
                    if method.startswith("source:"):
                        self.assertFalse(any(r == "target" and m != "probe" for r, m in calls))

    def test_readback_each_field_and_errors(self):
        for patch in ({"url": "https://wrong.test/"}, {"max_connections": 8}, {"allowed_updates": []},
                      {"has_custom_certificate": True}, {"ip_address": "203.0.113.8"},
                      {"max_connections": None}, {"pending_update_count": None},
                      {"last_error_date": int(time.time()) + 60}, {"last_synchronization_error_date": 9999}):
            with self.subTest(patch=patch):
                api = self.with_api(readback=patch)
                result = self.run_surface(api)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(sum(c["method"] == "setWebhook" for c in api.calls), 1)
                self.assertIn("set_webhook_accepted=true", result.stdout)

    def test_same_second_error_is_new(self):
        bindir = self.private / "clock"
        bindir.mkdir()
        clock = bindir / "date"
        clock.write_text('#!/bin/sh\necho 1000\n')
        clock.chmod(0o700)
        for exported in (False, True):
            with self.subTest(exported=exported):
                api = self.with_api(readback={"last_error_date": 1000})
                api.source["last_error_date"] = 1000
                result = self.run_surface(api, exported, PATH=str(bindir) + os.pathsep + self.env["PATH"])
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('"new_error":true', result.stdout)
                self.assertIn('"delivery_observation":"degraded"', result.stdout)

    def test_env_file_pair_precedence_empty_override_and_private_key(self):
        settings = self.private / "settings"
        settings.write_text('WEBHOOK_SECRET_TOKEN=File_tier_placeholder\nWEBHOOK_ALLOWED_UPDATES=\'[]\'\n')
        for exported in (False, True):
            api = self.with_api()
            result = self.run_surface(api, exported, ENV_FILE=str(settings))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(next(c for c in api.calls if c["method"] == "setWebhook")["fields"]["secret_token"], SECRET)
            settings.write_text('WEBHOOK_SECRET_TOKEN_FILE=/outside/placeholder\nWEBHOOK_ALLOWED_UPDATES=\'[]\'\n')
            api = self.with_api()
            result = self.run_surface(api, exported, ENV_FILE=str(settings), WEBHOOK_SECRET_TOKEN=SECRET, WEBHOOK_SECRET_TOKEN_FILE=None)
            self.assertEqual(result.returncode, 0, result.stderr)
            api = self.with_api()
            result = self.run_surface(api, exported, ENV_FILE=str(settings), WEBHOOK_ALLOWED_UPDATES="")
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(any(c["method"] == "deleteWebhook" for c in api.calls))
        key = self.private / "private-key"
        key.write_text("-----BEGIN PRIVATE KEY-----\nPLACEHOLDER\n-----END PRIVATE KEY-----")
        api = self.with_api()
        result = self.run_surface(api, WEBHOOK_CERTIFICATE_MODE="provided", WEBHOOK_CERTIFICATE_FILE=str(key))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(c["method"] == "deleteWebhook" for c in api.calls))

    def test_unreadable_secret_is_preflight_failure(self):
        if os.geteuid() == 0:
            self.skipTest("Permission case requires non-root POSIX")
        self.secret.chmod(0)
        try:
            api = self.with_api()
            result = self.run_surface(api)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(any(c["method"] in ("deleteWebhook", "setWebhook", "logOut") for c in api.calls))
        finally:
            self.secret.chmod(0o600)


if __name__ == "__main__":
    unittest.main()
