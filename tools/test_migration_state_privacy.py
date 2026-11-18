import copy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import os
from check_docs import private_site_paths
from migration_contract import build_plan
from migration_store import Journal, StateError, _validate_state


class MemoryStore:
    """Test-only durable-boundary double; never used by the CLI."""
    def __init__(self, root=None):
        class EmptyRoot:
            def glob(self, pattern):
                return []
        self.root = Path(root) if root else EmptyRoot()
        self.rows = {}
        self.fail = False

    def binding_key(self):
        return b'x'*32

    def read(self, name):
        return copy.deepcopy(self.rows[name])

    def write(self, name, row):
        if self.fail:
            raise StateError('injected durable write failure')
        self.rows[name] = copy.deepcopy(row)


class PrivacyTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.j = Journal(self.store)
        self.j.bot = '123'
        p = build_plan(operation_id='op',bot_id='123',source='https://api.telegram.org',
                       target='https://target.example', token='123:synthetic',
                       profile={'mode':'polling'},action='polling',drop=False,key=b'x'*32)
        self.state = self.j.create(p, None)

    def test_intent_crash_recovery_and_integrity(self):
        self.j.intent(self.state,'source_delete')
        s = self.j.load('op')
        self.j.recover(s)
        self.assertEqual(self.j.outcome(s,'source_delete'),'unknown')
        self.assertEqual(s['steps']['source_delete'][0]['events'][0]['outcome'],'in_flight')
        with self.assertRaises(StateError):
            self.j.intent(s,'source_delete')
        self.store.rows['op']['state']['results']['migration_outcome']='confirmed'
        with self.assertRaises(StateError):
            self.j.load('op')

    def test_no_receipt_or_intent_on_disk_failure(self):
        self.store.fail = True
        with self.assertRaises(StateError):
            self.j.intent(self.state,'source_delete')
        self.assertEqual(self.j.outcome(self.j.load('op'),'source_delete'),'pending')

    def test_closed_receipts_and_no_runtime_secrets(self):
        self.j.intent(self.state,'source_delete')
        with self.assertRaises(StateError):
            self.j.finish(self.state,'source_delete','confirmed','https://secret.example')
        self.assertNotIn('synthetic',str(self.store.rows))
        self.assertNotIn('https://',str(self.store.rows))

    @unittest.skipUnless(os.name=='posix','POSIX filesystem fixture; required in Linux CI')
    def test_private_site_paths_nested(self):
        temp=TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root=Path(temp.name)
        for name in ('a/.env','a/.env.local','a/.migration-state/op.json','migration-helper.env','archive/binding.key'):
            p=root/name
            p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text('synthetic')
        p=root/'archive'/'renamed-journal.json'
        p.write_text('{"state":{},"mac":"synthetic"}')
        self.assertGreaterEqual(len(list(private_site_paths(root))),6)

    def test_prerequisites_and_lock_required(self):
        with self.assertRaises(StateError):
            self.j.intent(self.state,'source_logout')
        self.j.bot=None
        with self.assertRaises(StateError):
            self.j.save(self.state)

    def test_superseding_never_accepts_a_started_attempt(self):
        self.j.supersede(self.state,'replacement')
        self.assertIn('superseded',self.j.load('op')['checkpoints'])
        self.setUp()
        self.j.intent(self.state,'source_delete')
        with self.assertRaises(StateError):
            self.j.supersede(self.state,'other')
