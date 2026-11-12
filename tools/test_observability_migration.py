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
        from test_issue11_http import MigrationRequestTests
        from issue11_http_mock import TOKEN, WEBHOOK
        MigrationRequestTests.setUpClass()
        fixture = MigrationRequestTests('test_success_webhook_and_schema')
        fixture.setUp()
        try:
            result = fixture.run_script(third=WEBHOOK)
            self.assertEqual(result.returncode, 0)
            self.assertFalse((fixture.work/'.observability/migration/status.json').exists())
            fixture.reset_run()
            directory = fixture.work/'.observability/migration'
            directory.mkdir(parents=True, mode=0o755)
            result = fixture.run_script(third=WEBHOOK, MIGRATION_STATUS_DIR=str(directory), MIGRATION_STATUS_ALIAS='public')
            self.assertEqual(result.returncode, 0)
            body=(directory/'status.json').read_text()
            self.assertNotIn(TOKEN,body); self.assertNotIn(WEBHOOK,body)
            self.assertEqual(read_migrations(directory)['operations'][0]['outcome'],'confirmed')
            self.assertFalse(list(directory.glob('.status.*')))
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
