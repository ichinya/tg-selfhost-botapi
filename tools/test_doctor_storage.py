import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import unittest
import os
import subprocess
import tempfile
from pathlib import Path
from doctor_checks import mount_for, capacity
from doctor_runtime import WRITE_PROBE, STORAGE_METADATA, Installation, Budget, mount_accounting
from doctor import parser


class StorageTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "POSIX probe primitive")
    def test_real_probe_cleans_only_its_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve()
            sentinel = path / "sentinel"
            sentinel.write_bytes(b"existing state")
            groups = sorted(set(os.getgroups()) | {os.getgid()})
            command = ["sh", "-c", WRITE_PROBE, "doctor", str(path), str(os.getuid()), str(os.getgid()),
                       "".join(str(g) + " " for g in groups), "abcdef0123456789"]
            result = subprocess.run(command, capture_output=True, timeout=3)
            self.assertEqual((0, b"OK\n"), (result.returncode, result.stdout), result.stderr)
            self.assertEqual(b"existing state", sentinel.read_bytes())
            self.assertEqual(["sentinel"], [p.name for p in path.iterdir()])

    def test_nested_mount_and_temp_layer(self):
        mounts = [{"Destination": "/data", "RW": True}, {"Destination": "/data/nested", "RW": False}]
        self.assertFalse(mount_for("/data/nested/path", mounts)["RW"])
        self.assertIsNone(mount_for("/database", mounts))
        self.assertIsNone(mount_for("/tmp", mounts))

    def test_capacity_margin_and_inodes(self):
        self.assertTrue(capacity(210, 111, 100, 100, 100, 10))
        self.assertTrue(capacity(211, 112, 100, 100, 100, 10))
        self.assertFalse(capacity(209, 112, 100, 100, 100, 10))
        self.assertFalse(capacity(1000, 99, 100, 100))

    def test_probe_is_fixed_exclusive_and_bounded(self):
        for fragment in ('set -C', 'trap cleanup EXIT', 'rm -- "$probe"', 'id -G', 'stat -c'):
            self.assertIn(fragment, WRITE_PROBE)
        self.assertNotIn("mkdir", WRITE_PROBE + STORAGE_METADATA)
        self.assertNotIn("chown", WRITE_PROBE + STORAGE_METADATA)

    def test_no_write_and_group_mismatch(self):
        class Runner:
            budget = Budget()
            def run(self, argv):
                raise AssertionError("no write command is permitted")
        args = parser().parse_args(["--scenario", "official-to-self", "--no-write-probe"])
        obj = Installation(args, Runner(), None, [], [])
        obj.containers["botapi"] = {"Mounts": [{"Destination": "/data", "Type": "volume", "RW": True}]}
        obj.process = dict(uid=101, gid=101, groups=[102], work="/data", temp="/tmp")
        obj.exec = lambda *a, **k: b"1:2\nfs 4096 999999 999999\n101\n101\n101\nDOCTOR_MOUNTINFO\n1 0 0:1 / / rw - ext4 /synthetic rw\n"
        obj.storage()
        self.assertTrue(any(c["reason_code"] == "supplementary_groups_mismatch" for c in obj.checks))
        self.assertEqual(2, sum(c["reason_code"] == "write_probe_disabled" for c in obj.checks))

    def test_enabled_quota_and_nested_mounts(self):
        points, quota = mount_accounting(["1 0 0:1 / / rw - ext4 /synthetic rw",
            "2 1 0:2 / /data rw - xfs /synthetic rw,prjquota",
            "3 2 0:3 / /data/nested rw - ext4 /synthetic rw"], "/data")
        self.assertTrue(quota)
        self.assertIn("/data/nested", points)
        self.assertFalse(mount_accounting(["1 0 0:1 / / rw - ext4 /synthetic rw"], "/data")[1])
