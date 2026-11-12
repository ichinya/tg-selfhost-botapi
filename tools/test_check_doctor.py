import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import unittest
import contextlib
import io
import json
from check_doctor import assert_report, assert_commands, run_case, Harness
from doctor_checks import report, check
from unittest.mock import patch
import doctor
from doctor import parser
from doctor_runtime import collect, Budget
from doctor_mock import StackRunner, FakeHttp


class HarnessTests(unittest.TestCase):
    def test_private_runtime_values_never_reach_either_renderer(self):
        sentinel = "private-doctor-sentinel"
        class PrivateRunner(StackRunner):
            def run(self, argv):
                if any('test -f "$1"' in value for value in argv):
                    self.calls.append(list(argv))
                    return 0, b""
                code, raw = super().run(argv)
                if any("DOCTOR_ARGV" in value for value in argv):
                    raw += ("--api-hash=" + sentinel).encode() + b"\0"
                if any("nginx -T" in value for value in argv):
                    raw += ("\naccess_log /private/" + sentinel + ";").encode()
                return code, raw
        for fmt in ("text", "json"):
            runner = PrivateRunner()
            environment = runner.model["services"]["botapi"]["environment"]
            environment.update(TELEGRAM_API_HASH="", TELEGRAM_API_HASH_FILE="/private/" + sentinel)
            runner.containers[0]["Config"]["Env"] = runner.defaults + [k + "=" + v for k, v in environment.items()]
            http = FakeHttp([(404, "application/json; " + sentinel,
                              ('{"ok":false,"error_code":404,"description":"' + sentinel + '"}').encode())] * 2)
            def collector(args, runner, http, checks, images):
                args.migration_data = dict(schema_version=1, workflow_prepared=True, file_access="not_used",
                                           delivery_action="polling", drop_pending_updates=False)
                args.input_secure = True
                collect(args, runner, http, checks, images)
            out, err = io.StringIO(), io.StringIO()
            with patch("doctor_runtime.sys.platform", "linux"), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = doctor.main(["--scenario", "official-to-self", "--format", fmt], runner=runner, http=http, collector=collector)
            self.assertEqual(0, code, out.getvalue())
            self.assertNotIn(sentinel, out.getvalue() + err.getvalue())
            assert_commands(runner.calls)
            if fmt == "json":
                self.assertEqual(0, json.loads(out.getvalue())["exit_code"])

    def test_self_to_self_selected_subtree_capacity_and_compatibility(self):
        from types import SimpleNamespace
        metadata = b"directory|4096|1|10|10|1\nregular file|7|2|10|10|1\n"
        for condition, expected in (("safe", 0), ("shared", 1), ("low", 1),
                                    ("version", 3), ("symlink", 3), ("changed", 3), ("missing_subtree", 3),
                                    ("dedicated", 0), ("fresh", 0), ("occupied", 1)):
            with self.subTest(condition=condition):
                calls = []
                class InstallationDouble:
                    def __init__(self, args, runner, http, checks, images, source=False):
                        self.role = "source" if source else "target"
                        self.process = dict(uid=101, gid=101, flags={"local": True})
                        self.runner = runner
                        self.storage_data = {"work": dict(path="/data", inode="1:2" if source else "1:3", available_bytes=11000 if condition != "low" else 1, available_inodes=100)}
                        backing = "/same" if condition == "shared" else "/" + self.role
                        self.containers = {"botapi": {"Mounts": [{"Destination": "/data", "Source": backing}]}}
                        self.add = lambda name, status, reason, message: checks.append(check(self.role + "." + name, status, reason, message))
                        images.append(dict(role=self.role + ".botapi", version="2.0.0" if source and condition == "version" else "1.0.0"))
                    def configuration(self): pass
                    def runtime(self): pass
                    def storage(self): pass
                    def exposure(self): pass
                    def probes(self): pass
                    def unchanged(self): pass
                    def exec(self, *argv, **kwargs):
                        from doctor_runtime import TARGET_DESTINATION
                        if TARGET_DESTINATION in argv:
                            return b"OCCUPIED\n" if condition == "occupied" else b"EMPTY\n"
                        calls.append(argv)
                        if condition == "symlink":
                            return b"symbolic link|7|2|10|10|1\n"
                        return metadata + (b"regular file|1|3|10|10|1\n" if condition == "changed" and len(calls) == 2 else b"")
                args = parser().parse_args(["--scenario", "self-to-self", "--source-project-name", "source", "--min-free-bytes", "100", "--min-free-inodes", "10"])
                args.migration_data = dict(schema_version=1, delivery_action="polling", drop_pending_updates=False,
                                           file_access="not_used", workflow_prepared=True,
                                           transfer=dict(method="per-bot", state_subdir="private-selected", backup_prepared=True, exclusive_use_plan_prepared=True, backlog_policy="drain"))
                if condition == "missing_subtree":
                    del args.migration_data["transfer"]["state_subdir"]
                if condition in {"dedicated", "fresh"}:
                    args.migration_data["transfer"].update(method="dedicated-cold" if condition == "dedicated" else "fresh-login",
                        dedicated_source=True, target_empty_prepared=True, backlog_policy="accept-loss")
                    del args.migration_data["transfer"]["state_subdir"]
                args.input_secure = True
                checks, images = [], []
                with patch("doctor_runtime.Installation", InstallationDouble):
                    collect(args, SimpleNamespace(budget=Budget()), None, checks, images)
                result = report(args.scenario, checks)
                self.assertEqual(expected, result["exit_code"], result["readiness"])
                if calls:
                    self.assertEqual(("/data", "." if condition == "dedicated" else "private-selected"), calls[0][-2:])
                if condition == "fresh":
                    self.assertFalse(calls)
                self.assertNotIn("private-selected", str(result))

    def test_outbound_and_hook_scenarios_keep_infrastructure(self):
        for scenario, expected in (("self-to-official", 0), ("hook-only", 1)):
            args = parser().parse_args(["--scenario", scenario])
            args.migration_data = dict(schema_version=1, delivery_action="polling", drop_pending_updates=False,
                                       file_access="not_used", workflow_prepared=True, source_backup_prepared=True, source_backlog_policy="accept-loss")
            args.input_secure = True
            checks, images = [], []
            with patch("doctor_runtime.sys.platform", "linux"):
                collect(args, StackRunner(), FakeHttp([(404, "application/json", b'{"ok":false,"error_code":404}')] * 2), checks, images)
            result = report(scenario, checks)
            self.assertEqual(expected, result["exit_code"])
            self.assertEqual("READY", result["infrastructure"]["verdict"])
            self.assertTrue(result["images"] or images)

    def test_cleanup_is_scoped_to_owned_project_and_image(self):
        harness = Harness()
        harness.built = True
        with patch("check_doctor.subprocess.run") as run:
            harness.stop()
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(2, len(commands))
        self.assertIn(harness.project, commands[0])
        self.assertIn("--volumes", commands[0])
        self.assertEqual(["docker", "image", "rm", harness.project + ":synthetic", harness.project + ':observer'], commands[1])

    def test_full_pipeline_matrix_without_docker(self):
        data = dict(schema_version=1, workflow_prepared=True, file_access="not_used",
                    delivery_action="polling", drop_pending_updates=False)
        for options, no_write, expected in [({}, False, 0), ({"missing": True}, False, 1),
                ({"stopped": True}, False, 1), ({"unsafe": True}, False, 1), ({"drift": True}, False, 1),
                ({"changed": True}, False, 3), ({"pinned": True}, False, 3), ({}, True, 3)]:
            with self.subTest(options=options, no_write=no_write):
                args = parser().parse_args(["--scenario", "official-to-self"] + (["--no-write-probe"] if no_write else []))
                args.migration_data, args.input_secure = data, True
                checks, images = [], []
                runner = StackRunner(**options)
                http = FakeHttp([(404, "application/json", b'{"ok":false,"error_code":404}')] * 2)
                with patch("doctor_runtime.sys.platform", "linux"):
                    collect(args, runner, http, checks, images)
                result = report(args.scenario, checks)
                result["images"] = images
                from test_doctor import assert_contract_schema
                schema = json.loads(pathlib.Path(doctor.__file__).with_name("doctor.schema.json").read_text())
                assert_contract_schema(result, schema)
                self.assertEqual(expected, result["exit_code"], [(c["id"], c["reason_code"]) for c in checks if c["required"] and c["status"] != "pass"])
                assert_commands(runner.calls)
                self.assertTrue(all(url.endswith("/") for url in http.calls))
                if no_write:
                    from doctor_runtime import WRITE_PROBE
                    self.assertFalse(any(WRITE_PROBE in argv for argv in runner.calls))

    def test_report_consistency(self):
        assert_report(report("official-to-self", [check("a", "pass", "ok", "ok")]), 0)
        with self.assertRaises(AssertionError):
            assert_report(report(None, []), 2)

    def test_mutations_and_tokens_rejected(self):
        for argv in (["docker", "pull", "image"], ["docker", "compose", "up"],
                     ["docker", "exec", "selected", "sh", "-c", "rm -rf /data"],
                     ["python", "doctor_runtime.py", "--http-worker", "https://api.telegram.org/botx/getMe"]):
            with self.assertRaises(AssertionError):
                assert_commands([argv])
        assert_commands([["docker", "compose", "config", "--format", "json"]])
