import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import unittest


class FileContractBoundaryTests(unittest.TestCase):
    def test_remote_claim_remains_unknown(self):
        from doctor_checks import migration_checks
        checks = migration_checks('official-to-self', {'schema_version': 1, 'file_access': 'remote_authenticated'})
        item = next(c for c in checks if c['id'] == 'migration.file_access')
        self.assertEqual('unknown', item['status'])
        self.assertIn('check_file_contract.py', item['remediation'])

import contextlib
import io
import json
import os
import tempfile
from doctor_checks import migration_checks, validate_migration_input, report, pending_actions
from doctor_runtime import load_migration_input, parse_migration_input, transfer_metadata
from unittest.mock import patch
import doctor
import doctor_runtime


class MigrationTests(unittest.TestCase):
    def test_v1_input_and_remote_boundary(self):
        data = dict(schema_version=1, delivery_action="polling", drop_pending_updates=False,
                    file_access="remote_authenticated", workflow_prepared=True)
        self.assertEqual(data, validate_migration_input(data))
        result = report("official-to-self", migration_checks("official-to-self", data))
        self.assertEqual(3, result["exit_code"])
        self.assertIn("migration.file_access", result["readiness"]["unknowns"])

    def complete(self):
        return dict(schema_version=1, workflow_prepared=True, file_access="not_used",
                    delivery_action="polling", drop_pending_updates=False, source_backup_prepared=True, source_backlog_policy="accept-loss")

    def test_matrix_and_false_queue(self):
        data = self.complete()
        for scenario in ("official-to-self", "self-to-official", "self-to-self"):
            data["transfer"] = dict(method="per-bot", state_subdir="synthetic-state", backup_prepared=True, exclusive_use_plan_prepared=True, backlog_policy="drain")
            checks = migration_checks(scenario, data)
            self.assertTrue(all(c["status"] == "pass" for c in checks if c["required"]))
            result = report(scenario, checks)
            self.assertTrue(result["migration"]["pending_actions"])
            self.assertTrue(result["migration"]["unverified_session_facts"])
        self.assertEqual(1, report("hook-only", migration_checks("hook-only", {}))["exit_code"])

    def test_missing_false_and_profile(self):
        self.assertEqual(3, report("official-to-self", migration_checks("official-to-self", {}))["exit_code"])
        self.assertEqual(1, report("official-to-self", migration_checks("official-to-self", self.complete() | {"workflow_prepared": False}))["exit_code"])
        for action in ("preserve", "set"):
            checks = migration_checks("official-to-self", self.complete() | {"delivery_action": action})
            self.assertTrue(any(c["reason_code"] == "missing_prerequisite" for c in checks))

    def test_strict_input(self):
        for invalid in ({"token": "private"}, self.complete() | {"workflow_prepared": 1},
                        self.complete() | {"delivery_action": ""},
                        self.complete() | {"transfer_metadata": {"bytes": True}},
                        self.complete() | {"transfer": {"state_subdir": "../escape"}},
                        self.complete() | {"transfer": {"state_subdir": "/absolute"}},
                        self.complete() | {"transfer": {"backup_prepared": 1}},
                        self.complete() | {"schema_version": True}):
            with self.assertRaises(ValueError):
                validate_migration_input(invalid)
        self.assertEqual(self.complete(), validate_migration_input(self.complete()))

    def test_helpers_are_not_certified(self):
        result = report("self-to-official", migration_checks("self-to-official", self.complete()))
        self.assertEqual("not_certified", result["migration"]["executor_support"]["helpers"])
        self.assertIn("authorize_cloud", pending_actions("self-to-official"))

    def test_private_json_errors_are_usage_errors_and_redacted(self):
        for raw in ('{"schema_version":1,"schema_version":1}',
                    '{"schema_version":1,"transfer_metadata":{"bytes":NaN}}',
                    '{"schema_version":1,"token":"private-sentinel"}'):
            output = io.StringIO()
            def load(path):
                return parse_migration_input(raw), True
            with patch.object(doctor, "load_migration_input", load), contextlib.redirect_stdout(output):
                code = doctor.main(["--scenario", "official-to-self", "--format=json", "--migration-input", "/private/input.json"],
                                   collector=lambda *args: self.fail("invalid input reached runtime"))
            self.assertEqual(2, code)
            self.assertNotIn("private-sentinel", output.getvalue())
            self.assertEqual(2, json.loads(output.getvalue())["exit_code"])

    def test_input_rejects_checkout_and_symlink(self):
        with self.assertRaises(ValueError):
            load_migration_input(str(pathlib.Path(__file__)))
        if os.name != "posix":
            return
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "private.json"
            path.write_text('{"schema_version":1}')
            os.chmod(path, 0o600)
            link = pathlib.Path(directory) / "link.json"
            link.symlink_to(path)
            with self.assertRaises(ValueError):
                load_migration_input(str(link))
            os.chmod(path, 0o644)
            self.assertEqual(({}, False), load_migration_input(str(path)))

    def test_input_rejects_exported_project_without_git(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory) / "export"
            (root / "tools").mkdir(parents=True)
            candidate = root / "private.json"
            candidate.write_text('{"schema_version":1}')
            with patch.object(doctor_runtime, "__file__", str(root / "tools" / "doctor_runtime.py")):
                with self.assertRaises(ValueError):
                    load_migration_input(str(candidate))

    def test_transfer_metadata_rejects_links_and_special_files(self):
        self.assertEqual((4103, 2), transfer_metadata(b"directory|4096|1|10|10|1\nregular file|7|2|10|10|1\n"))
        for kind in (b"symbolic link", b"fifo", b"socket"):
            with self.assertRaises(ValueError):
                transfer_metadata(kind + b"|7|2|10|10|1\n")

    def test_hardlinks_do_not_double_copy_bytes(self):
        raw = b"directory|4096|1|10|10|1\nregular file|7|2|10|10|1\nregular file|7|2|10|10|1\n"
        self.assertEqual((4103, 3), transfer_metadata(raw))

    def test_transfer_methods_and_missing_preparation(self):
        for method in ("per-bot", "dedicated-cold", "fresh-login"):
            transfer = dict(method=method, backup_prepared=True, exclusive_use_plan_prepared=True,
                            backlog_policy="accept-loss", dedicated_source=True, target_empty_prepared=True)
            if method == "per-bot":
                transfer["state_subdir"] = "private-state"
            data = self.complete() | {"transfer": transfer}
            validate_migration_input(data)
            self.assertEqual(0, report("self-to-self", migration_checks("self-to-self", data))["exit_code"])
            transfer.pop("backlog_policy")
            self.assertEqual(3, report("self-to-self", migration_checks("self-to-self", data))["exit_code"])
        for transfer in ({"method": "unsupported"}, {"dedicated_source": 1},
                         {"method": "fresh-login", "state_subdir": "private-state"}):
            with self.assertRaises(ValueError):
                validate_migration_input(self.complete() | {"transfer": transfer})
        data = self.complete() | {"transfer": {"method": "fresh-login", "backup_prepared": True,
            "exclusive_use_plan_prepared": True, "backlog_policy": "drain"}}
        self.assertEqual(1, report("self-to-self", migration_checks("self-to-self", data))["exit_code"])
