"""Tests for the storage primitives, without a Telegram connection."""
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

if os.name != "posix":
    raise unittest.SkipTest("requires POSIX filesystem and locking; run in Linux or WSL")

from migration_store import StateError, StateStore


class StateStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "state"
        self.store = StateStore(self.root)

    def test_snapshot_round_trip_and_failed_replace_keeps_old_snapshot(self):
        self.store.write("operation", {"version": 1, "stage": "planned"})
        with mock.patch("migration_store.os.replace", side_effect=OSError("injected")):
            with self.assertRaises(StateError):
                self.store.write("operation", {"version": 1, "stage": "pending"})
        self.assertEqual(self.store.read("operation")["stage"], "planned")
        self.assertEqual(list(self.root.glob(".snapshot-*")), [])

    def test_fsync_failure_is_reported_before_replace(self):
        self.store.write("operation", {"stage": "planned"})
        with mock.patch("migration_store.os.fsync", side_effect=OSError("injected")):
            with self.assertRaises(StateError):
                self.store.write("operation", {"stage": "pending"})
        self.assertEqual(self.store.read("operation"), {"stage": "planned"})

    def test_lock_is_per_bot_and_survives_parent_descriptor_close(self):
        with self.store.lock("123") as fd:
            child = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                pass_fds=(fd,), stdin=subprocess.DEVNULL,
            )
            self.addCleanup(lambda: child.poll() is None and child.kill())
            with self.assertRaises(StateError):
                with self.store.lock("123"):
                    pass
            with self.store.lock("124"):
                pass
        # The child owns the inherited open file description, keeping flock.
        with self.assertRaises(StateError):
            with self.store.lock("123"):
                pass
        child.terminate()
        child.wait(timeout=5)
        with self.store.lock("123"):
            pass

    def test_process_death_around_replace_leaves_a_complete_snapshot(self):
        self.store.write("operation", {"stage": "old"})
        script = """
import os, sys
from migration_store import StateStore
store = StateStore(sys.argv[1])
replace = os.replace
def interrupt(src, dst, **kwargs):
    if sys.argv[2] == 'after':
        replace(src, dst, **kwargs)
    os._exit(73)
os.replace = interrupt
store.write('operation', {'stage': 'new'})
"""
        for point, expected in (("before", "old"), ("after", "new")):
            with self.subTest(point=point):
                self.store.write("operation", {"stage": "old"})
                child = subprocess.run(
                    [sys.executable, "-c", script, str(self.root), point],
                    env={**os.environ, "PYTHONPATH": str(Path(__file__).parent.resolve())},
                    check=False,
                )
                self.assertEqual(child.returncode, 73)
                self.assertEqual(self.store.read("operation"), {"stage": expected})

    def test_directory_fsync_failure_is_reported_after_replace(self):
        self.store.write("operation", {"stage": "old"})
        real_fsync = os.fsync
        calls = 0

        def fail_directory(fd):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected directory fsync failure")
            real_fsync(fd)

        with mock.patch("migration_store.os.fsync", side_effect=fail_directory):
            with self.assertRaises(StateError):
                self.store.write("operation", {"stage": "new"})
        # Replacement may be visible, but its durability is unknown.
        self.assertEqual(self.store.read("operation"), {"stage": "new"})

    def test_ambiguous_or_non_object_json_is_rejected(self):
        path = self.root / "invalid.json"
        for contents in ('{"stage":"old","stage":"new"}',
                         '{"nested":{"x":1,"x":2}}',
                         '{"value":NaN}', '[]', 'null'):
            with self.subTest(contents=contents):
                path.write_text(contents, encoding="utf-8")
                os.chmod(path, 0o600)
                with self.assertRaises(StateError):
                    self.store.read("invalid")
        with self.assertRaises(StateError):
            self.store.write("invalid", [])

    def test_binding_key_is_private_and_stable(self):
        key = self.store.binding_key()
        self.assertEqual(len(key), 32)
        self.assertEqual(self.store.binding_key(), key)
        self.assertEqual((self.root / "binding.key").stat().st_mode & 0o777, 0o600)

    def test_private_root_excludes_checkout_and_data(self):
        checkout = Path(__file__).resolve().parent.parent
        for root in (checkout, checkout / "docs", checkout / "_site", checkout / "data"):
            with self.subTest(root=root), self.assertRaises(StateError):
                StateStore(root)
        with self.assertRaises(StateError):
            StateStore(Path(self.temp.name) / "data" / "state", data_dirs=[Path(self.temp.name) / "data"])
        with self.assertRaises(StateError):
            StateStore("relative")

    def test_replaced_root_is_rejected(self):
        self.root.rename(self.root.with_name("old"))
        self.root.mkdir(mode=0o700)
        with self.assertRaises(StateError):
            self.store.write("operation", {})
        with self.assertRaises(StateError):
            self.store.read("operation")
        with self.assertRaises(StateError):
            with self.store.lock("123"):
                pass

    def test_unsafe_paths_and_corrupt_snapshot_are_rejected(self):
        with self.assertRaises(StateError):
            self.store.write("../other", {})
        (self.root / "broken.json").write_text("{")
        os.chmod(self.root / "broken.json", 0o600)
        with self.assertRaises(StateError):
            self.store.read("broken")
        link = Path(self.temp.name) / "link"
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(StateError):
            StateStore(link)
        os.chmod(self.root, 0o755)
        with self.assertRaises(StateError):
            StateStore(self.root)


class JournalPosixTests(unittest.TestCase):
    def setUp(self):
        from migration_contract import build_plan
        from migration_store import Journal
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store=StateStore(Path(self.temp.name)/'private')
        self.addCleanup(self.store.close)
        self.j=Journal(self.store)
        self.plan=build_plan(operation_id='op',bot_id='123',source='https://api.telegram.org',
                             target='https://fixture.example',token='123:synthetic',
                             profile={'mode':'polling'},action='polling',drop=False,key=self.j.key)
        with self.j.lock('123'):
            self.s=self.j.create(self.plan,None)

    def test_second_operation_and_immutable_plan_are_rejected(self):
        from migration_contract import plan_digest
        other=dict(self.plan,operation_id='other')
        with self.j.lock('123'):
            with self.assertRaises(StateError):
                self.j.create(other,None)
            self.s['plan']['drop']=True
            self.s['plan']['drop_step']='target_configure'
            self.s['digest']=plan_digest(self.s['plan'])
            with self.assertRaises(StateError):
                self.j.save(self.s)

    def test_actual_fsync_failure_never_creates_send_permission(self):
        with self.j.lock('123'):
            with mock.patch('migration_store.os.fsync',side_effect=OSError('injected')):
                with self.assertRaises(StateError):
                    self.j.intent(self.s,'source_delete')
        self.assertEqual(self.j.outcome(self.j.load('op'),'source_delete'),'pending')

    def test_executor_death_after_intent_recovers_unknown_not_new_attempt(self):
        script='''
import os,sys
from migration_store import StateStore,Journal
store=StateStore(sys.argv[1],create=False)
j=Journal(store,read_only=True)
with j.lock('123'):
    s=j.load('op')
    j.intent(s,'source_delete')
    os._exit(73)
'''
        child=subprocess.run([sys.executable,'-c',script,str(self.store.root)],
                             env={**os.environ,'PYTHONPATH':str(Path(__file__).parent.resolve())},check=False,timeout=10)
        self.assertEqual(child.returncode,73)
        with self.j.lock('123'):
            state=self.j.load('op')
            self.j.recover(state)
            self.assertEqual(self.j.outcome(state,'source_delete'),'unknown')
            with self.assertRaises(StateError):
                self.j.intent(state,'source_delete')


if __name__ == '__main__':
    unittest.main()
