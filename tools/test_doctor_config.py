import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import unittest
from doctor import parser
from doctor_checks import settings_checks, runtime_identity
from doctor_runtime import compose_argv, Installation
import contextlib
import io
import json
import doctor


class ConfigTests(unittest.TestCase):
    def test_files_directory_must_come_from_observed_flags(self):
        from doctor_checks import process_flags
        self.assertNotIn('files-dir', process_flags(['--dir=/state']))
        with self.assertRaises(ValueError):
            process_flags(['--files-dir=/a', '--files-dir=/b'])

    def test_unsupported_compose_json_is_invocation_error(self):
        class Runner:
            def run(self, argv):
                return 1, b"private runtime output"
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = doctor.main(["--scenario", "official-to-self", "--format=json"], runner=Runner())
        self.assertEqual(2, code)
        self.assertEqual(2, json.loads(output.getvalue())["exit_code"])
        self.assertNotIn("private runtime output", output.getvalue())

    def env(self):
        return dict(TELEGRAM_API_ID="12345", TELEGRAM_API_HASH="synthetic-test-value",
                    TELEGRAM_WORK_DIR="/data", TELEGRAM_TEMP_DIR="/tmp", TELEGRAM_LOCAL="true")

    def test_credentials_boolean_and_port(self):
        env = self.env()
        self.assertTrue(all(c["status"] == "pass" for c in settings_checks(env)))
        for changes, reason in [({"TELEGRAM_API_ID": ""}, "missing_setting"),
                                ({"TELEGRAM_API_HASH_FILE": "/secret"}, "conflicting_secret_sources"),
                                ({"TELEGRAM_HTTP_PORT": "65536"}, "invalid_port"),
                                ({"TELEGRAM_LOCAL": "yes"}, "invalid_boolean"),
                                ({"TELEGRAM_API_ID": "3000..."}, "placeholder_setting")]:
            self.assertIn(reason, [c["reason_code"] for c in settings_checks(env | changes)])

    def test_file_and_explicit_command(self):
        env = self.env() | {"TELEGRAM_API_HASH": "", "TELEGRAM_API_HASH_FILE": "/secret"}
        self.assertIn("secret_file_unverified", [c["reason_code"] for c in settings_checks(env)])
        self.assertFalse(any(c["status"] == "fail" for c in settings_checks({}, explicit=True)))

    def test_compose_order_and_source(self):
        args = parser().parse_args(["--scenario", "self-to-self", "-f", "base", "-f", "build",
                                   "--env-file", "first", "--env-file", "second", "--source-file", "source",
                                   "--profile", "test", "-p", "target"])
        self.assertEqual(["docker", "compose", "--file", "base", "--file", "build", "--env-file", "first",
                          "--env-file", "second", "--profile", "test", "--project-name", "target"], compose_argv(args))
        self.assertEqual(["docker", "compose", "--file", "source"], compose_argv(args, True))

    def test_snapshot_changes(self):
        self.assertNotEqual(runtime_identity({"State": {"Pid": 1}}), runtime_identity({"State": {"Pid": 2}}))
        self.assertNotEqual(runtime_identity({"RestartCount": 1}), runtime_identity({"RestartCount": 2}))
        self.assertEqual(runtime_identity({"State": {"Health": {"Status": "healthy", "Log": [1]}}}),
                         runtime_identity({"State": {"Health": {"Status": "healthy", "Log": [2]}}}))

    def test_unexpected_runtime_configuration_and_label_selection(self):
        from doctor_mock import StackRunner
        for condition in ("extra_env", "extra_mount", "extra_port", "oneoff", "wrong_project"):
            with self.subTest(condition=condition):
                runner = StackRunner()
                container = runner.containers[0]
                if condition == "extra_env":
                    container["Config"]["Env"].append("UNEXPECTED=synthetic")
                elif condition == "extra_mount":
                    container["Mounts"].append(dict(Destination="/extra", Source="/synthetic/extra", RW=True))
                elif condition == "extra_port":
                    container["NetworkSettings"]["Ports"]["8082/tcp"] = [dict(HostIp="127.0.0.1", HostPort="18082")]
                else:
                    labels = container["Config"]["Labels"]
                    labels["com.docker.compose.oneoff" if condition == "oneoff" else "com.docker.compose.project"] = "True" if condition == "oneoff" else "another"
                obj = Installation(parser().parse_args(["--scenario", "official-to-self"]), runner, None, [], [])
                obj.configuration()
                self.assertTrue(any(c["status"] == "fail" for c in obj.checks), obj.checks)
