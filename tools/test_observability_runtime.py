import datetime as dt
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from observe_runtime import atomic_write
from observability.runtime import read_runtime
from observability.schema import empty_status, utcnow


class RuntimeReaderTests(unittest.TestCase):
    def test_missing_fresh_stale_and_future(self):
        self.assertEqual(read_runtime()[1]['state'], 'unknown')
        with patch('observability.runtime.read_json') as reader:
            directory = '/synthetic'
            value = dict(schema_version=1, observed_at=utcnow(), storage=dict(filesystems=[]),
                         image={k:v for k,v in empty_status()['image'].items() if k not in {'source','state','reason','observed_at','age_seconds'}})
            value['image']['instance'] = 'a'*64
            reader.return_value = value
            self.assertEqual(read_runtime(directory)[1]['state'], 'ready')
            later = dt.datetime.now(dt.timezone.utc)+dt.timedelta(seconds=91)
            self.assertEqual(read_runtime(directory, later)[1]['state'], 'stale')
            reader.return_value = {'secret':'synthetic'}
            self.assertEqual(read_runtime(directory)[1]['state'], 'unavailable')
