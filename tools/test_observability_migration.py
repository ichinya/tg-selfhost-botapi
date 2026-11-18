import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
import uuid
import os
from unittest.mock import patch
from observability import schema
from observability.migration import read_migrations, permits_polling


class MigrationTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'posix', 'POSIX producer mock integration: verification deferred to CI/gates')
    def test_shipped_producer_is_opt_in_atomic_and_sanitized(self):
        from test_migration_integration import WrapperTests
        from migration_mock import TOKEN
        fixture = WrapperTests('test_public_wrapper_success_and_local_status')
        fixture.setUp()
        try:
            import shutil
            root = Path(__file__).resolve().parents[1]
            checkout = fixture.root/'checkout'
            checkout.mkdir()
            shutil.copytree(root/'tools', checkout/'tools', ignore=shutil.ignore_patterns('__pycache__'))
            shutil.copyfile(root/'migrate_off_to_self.sh', checkout/'migrate_off_to_self.sh')
            fixture.wrapper = checkout/'migrate_off_to_self.sh'
            directory = checkout/'.observability'/'migration'
            directory.mkdir(parents=True, mode=0o755)
            fixture.plan()
            self.assertFalse((directory/'status.json').exists())
            fixture.env.update(MIGRATION_STATUS_DIR=str(directory), MIGRATION_STATUS_ALIAS='public',
                               WEBHOOK_URL='https://example.invalid/private-webhook-canary')
            _, plan = fixture.call('status', expected=0)
            self.assertFalse(permits_polling(read_migrations(directory)))
            fixture.call('apply', '--confirm-digest', plan['digest'], '--quiescence-receipt', 'stopped', expected=2)
            self.assertFalse(permits_polling(read_migrations(directory)))
            fixture.call('resume', '--endpoint-change-receipt', 'changed', '--application-start-receipt', 'started', expected=0)
            body=(directory/'status.json').read_text()
            self.assertNotIn(TOKEN,body); self.assertNotIn(fixture.source.endpoint,body)
            self.assertNotIn(fixture.env['WEBHOOK_URL'], body)
            self.assertEqual(read_migrations(directory)['operations'][0]['outcome'],'confirmed')
            self.assertTrue(permits_polling(read_migrations(directory)))
            self.assertFalse(list(directory.glob('.status.*')))
        finally: fixture.doCleanups()

    @unittest.skipUnless(os.name == 'posix', 'POSIX integration')
    def test_unsafe_directory_does_not_change_result(self):
        from test_migration_integration import WrapperTests
        fixture = WrapperTests('test_public_wrapper_success_and_local_status')
        fixture.setUp()
        try:
            import shutil
            root = Path(__file__).resolve().parents[1]
            checkout = fixture.root/'checkout'
            checkout.mkdir()
            shutil.copytree(root/'tools', checkout/'tools', ignore=shutil.ignore_patterns('__pycache__'))
            fixture.wrapper = checkout/'tools'/'migration_executor.sh'
            directory = checkout/'.observability'/'migration'
            directory.mkdir(parents=True, mode=0o755)
            directory.chmod(0o777)
            fixture.env.update(MIGRATION_STATUS_DIR=str(directory), MIGRATION_STATUS_ALIAS='public')
            child, _ = fixture.call('plan', '--action', 'polling', '--quiescence-receipt', 'stopped', expected=0)
            self.assertIn('Monitoring projection unavailable', child.stderr)
            self.assertFalse((directory/'status.json').exists())
        finally: fixture.doCleanups()

    @unittest.skipUnless(os.name == 'posix', 'POSIX integration')
    def test_unknown_logout_blocks_polling(self):
        import shutil
        from test_migration_integration import WrapperTests
        fixture = WrapperTests('test_public_unknown_logout_reconcile_no_second_logout')
        fixture.setUp()
        try:
            root = Path(__file__).resolve().parents[1]
            checkout = fixture.root/'checkout'
            checkout.mkdir()
            shutil.copytree(root/'tools', checkout/'tools', ignore=shutil.ignore_patterns('__pycache__'))
            fixture.wrapper = checkout/'tools'/'migration_executor.sh'
            directory = checkout/'.observability'/'migration'
            directory.mkdir(parents=True, mode=0o755)
            fixture.env.update(MIGRATION_STATUS_DIR=str(directory), MIGRATION_STATUS_ALIAS='public')
            plan = fixture.plan()
            fixture.source.faults['logOut'] = 'lost_applied'
            fixture.call('apply', '--confirm-digest', plan['digest'], '--quiescence-receipt', 'stopped', expected=2)
            migration = read_migrations(directory)
            self.assertEqual(migration['operations'][0]['outcome'], 'blocked')
            self.assertFalse(permits_polling(migration))
        finally: fixture.doCleanups()

    def test_absent_invalid_active_terminal_stale(self):
        self.assertFalse(permits_polling(read_migrations()))
        self.assertTrue(permits_polling(read_migrations(), True))
        with patch('observability.migration.read_json') as reader:
            root = '/synthetic'
            reader.side_effect = ValueError('invalid')
            self.assertEqual(read_migrations(root)['state'], 'unavailable')
            reader.side_effect = None
            data = dict(schema_version=1, observed_at=schema.utcnow(), operations=[dict(operation_id=str(uuid.uuid4()),
                alias='public', stage='verification', outcome='pending', observed_at=schema.utcnow(), delivery_evidence='not_observed')])
            reader.return_value = data; self.assertFalse(permits_polling(read_migrations(root)))
            data['operations'][0].update(stage='finished', outcome='confirmed')
            reader.return_value = data; self.assertTrue(permits_polling(read_migrations(root)))
            later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=181)
            self.assertEqual(read_migrations(root, later)['state'], 'stale')
            data['raw_token'] = 'synthetic'
            reader.return_value = data; self.assertEqual(read_migrations(root)['state'], 'unavailable')
