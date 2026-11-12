import json
import subprocess
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_nonroot import Acceptance, CheckError, Commands, LABEL, WORK, TEMP, MEDIA, identity, validate_effective_mounts


class RunnerTests(unittest.TestCase):
    def test_workflow_gates_publication_for_new_and_reused_images(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/image.yml").read_text(encoding="utf-8")
        gate = workflow.index("- name: Qualify non-root storage before publication")
        publish = workflow.index("- name: Publish tested build then promote latest")
        self.assertLess(workflow.index("- name: Load existing immutable candidate"), gate)
        self.assertLess(gate, publish)
        self.assertNotIn("        if:", workflow[gate:publish])
        self.assertIn('tools/check_nonroot.py --image "$candidate_id"', workflow[gate:publish])
        self.assertIn('docker tag "$(cat qualified-image-id.txt)" "$IMAGE:latest"', workflow[publish:])

    def test_numeric_identity_is_required(self):
        self.assertEqual((1000, 2000), identity("1000:2000"))
        for value in ("", "root:root", "0:0", "1000:", "1000:abc", "-1:2000", "1000:2147483648"):
            with self.subTest(value=value), self.assertRaises(CheckError):
                identity(value)

    def test_effective_mount_alias_is_rejected_before_server_start(self):
        for source in ("/host/state", "/host/state/media"):
            with self.assertRaisesRegex(CheckError, "effective_backing_alias"):
                validate_effective_mounts([
                    dict(Destination=WORK, Source="/host/state"),
                    dict(Destination=TEMP, Source="/host/temp"),
                    dict(Destination=MEDIA, Source=source)])

    def test_deadline_limits_subprocess_and_propagates_failure(self):
        with patch("check_nonroot.time.monotonic", side_effect=[100, 105]), patch("check_nonroot.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, "ok", "")
            self.assertEqual("ok", Commands(10).run(["info"], timeout=60).stdout)
            self.assertEqual(5, run.call_args.kwargs["timeout"])
        with patch("check_nonroot.subprocess.run", side_effect=subprocess.TimeoutExpired("docker", 1)):
            with self.assertRaisesRegex(CheckError, "deadline"):
                Commands().run(["info"])
        with patch("check_nonroot.subprocess.run", return_value=subprocess.CompletedProcess([], 1, "private", "secret")):
            with self.assertRaisesRegex(CheckError, "docker_operation_failed"):
                Commands().run(["info"])

    def test_expired_budget_never_executes(self):
        with patch("check_nonroot.time.monotonic", side_effect=[100, 200]), patch("check_nonroot.subprocess.run") as run:
            with self.assertRaisesRegex(CheckError, "acceptance_deadline"):
                Commands(1).run(["info"])
            run.assert_not_called()

    def test_cleanup_deletes_only_recorded_and_labelled_resources(self):
        commands = Mock()
        gate = Acceptance("candidate", commands)
        gate.resources = [("volume", "own-volume"), ("container", "own-container"), ("container", "foreign")]
        def inspect(kind, name, absent_ok=False):
            label = {LABEL: "someone-else" if name == "foreign" else gate.owner}
            return {"Labels": label} if kind == "volume" else {"Config": {"Labels": label}}
        gate.inspect = inspect
        with self.assertRaisesRegex(CheckError, "cleanup_failed"):
            gate.cleanup()
        calls = [call.args[0] for call in commands.run.call_args_list]
        self.assertEqual([["container", "rm", "-f", "own-container"], ["volume", "rm", "own-volume"]], calls)
        self.assertFalse(any("prune" in args for args in calls))

    def test_failure_still_cleans_resources(self):
        gate = Acceptance("candidate", Mock())
        gate.inspect = Mock(side_effect=CheckError("qualification_failed"))
        gate.cleanup = Mock()
        with self.assertRaisesRegex(CheckError, "qualification_failed"):
            gate.run()
        gate.cleanup.assert_called_once()

    def test_candidate_is_frozen_to_image_id_before_matrix(self):
        gate = Acceptance("mutable-tag", Mock())
        image_id = "sha256:" + "a" * 64
        gate.inspect = Mock(return_value={"Id": image_id, "Config": {"Labels": {
            "io.tg-selfhost.bot-api-revision": "b" * 40}}})
        gate.matrix = Mock(); gate.supplementary = Mock(); gate.sharing = Mock(); gate.cleanup = Mock()
        with patch("builtins.print"):
            gate.run()
        self.assertEqual(image_id, gate.image)
        gate.matrix.assert_called_once(); gate.sharing.assert_called_once()
        gate.supplementary.assert_called_once()

    def test_already_removed_owned_resource_is_safe_to_skip(self):
        gate = Acceptance('candidate', Mock())
        gate.resources = [('container', 'own-completed')]
        gate.inspect = Mock(return_value=None)
        gate.cleanup()
        gate.commands.run.assert_not_called()

    def test_storage_probes_also_use_the_current_migration_adapter(self):
        gate = Acceptance('candidate', Mock())
        gate.evidence = Mock()
        gate.storage_probe('own-server', 1000, 2000)
        gate.evidence.assert_called_once_with('own-server', 1000, 2000)

    def test_supplementary_groups_are_checked_in_process_status(self):
        gate = Acceptance('candidate', Mock())
        gate.inspect = Mock(return_value={'State': {'Running': True}})
        response = 'HTTP/1.1 404 Not Found\nContent-Type: application/json\n\n{"ok":false,"error_code":404}'
        status = 'Uid:\t1000 1000 1000 1000\nGid:\t2000 2000 2000 2000\nGroups:\t2000 3000\n'
        outputs = (response, status, 'telegram-bot-ap\n')
        gate.commands.run.side_effect = [subprocess.CompletedProcess([], 0, s, '') for s in outputs]
        self.assertEqual(status, gate.wait_ready('own', 1000, 2000, supplementary=(3000,)))
        gate.commands.run.side_effect = [subprocess.CompletedProcess([], 0, s, '') for s in outputs]
        with self.assertRaisesRegex(CheckError, 'unexpected_server_groups'):
            gate.wait_ready('own', 1000, 2000)

    def test_server_readiness_observes_pid_one_not_exec_identity(self):
        commands = Mock()
        gate = Acceptance("candidate", commands)
        gate.inspect = Mock(return_value={"State": {"Running": True}})
        status = "Uid:\t1000\t1000\t1000\t1000\nGid:\t2000\t2000\t2000\t2000\nGroups:\t2000\n"
        response = 'HTTP/1.1 404 Not Found\nContent-Type: application/json\n\n{"ok":false,"error_code":404}'
        commands.run.side_effect = [subprocess.CompletedProcess([], 0, output, "")
                                    for output in (response, status, "telegram-bot-ap\n")]
        self.assertEqual(status, gate.wait_ready("own", 1000, 2000))
        self.assertTrue(any("/proc/1/status" in call.args[0] for call in commands.run.call_args_list))
        commands.run.side_effect = [subprocess.CompletedProcess([], 0, output, "")
                                    for output in (response, status.replace("1000", "0"))]
        with self.assertRaisesRegex(CheckError, "server_identity_mismatch"):
            gate.wait_ready("own", 1000, 2000)

    def test_quiesce_only_stops_own_running_bind_writers(self):
        gate = Acceptance("candidate", Mock())
        gate.resources = [("container", "own-running"), ("container", "unrelated-backing")]
        gate.inspect = lambda kind, name: {"State": {"Running": True}, "Config": {"Labels": {LABEL: gate.owner}},
            "Mounts": [{"Source": "/tmp/owned" if name == "own-running" else "/elsewhere"}]}
        gate.stop = Mock()
        gate.quiesce([("bind", "/tmp/owned")])
        gate.stop.assert_called_once_with("own-running")


if __name__ == "__main__":
    unittest.main()
