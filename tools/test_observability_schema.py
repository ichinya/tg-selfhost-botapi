import copy
import datetime as dt
import json
import unittest
from unittest.mock import patch
from observability.schema import empty_status, serialize_status, freshness, count, alias, timestamp, SCHEMA


class SchemaTests(unittest.TestCase):
    def test_independent_states_and_null(self):
        status = empty_status()
        status['process'].update(state='ready', live=True, ready=True)
        status['webhook'].update(state='last_error_recorded')
        actual = json.loads(serialize_status(status))
        self.assertEqual(actual['migration']['state'], 'unknown')
        self.assertIsNone(actual['queue']['sampled']['pending_lower_bound'])
        status['queue']['registered']['pending_lower_bound'] = 0
        self.assertEqual(json.loads(serialize_status(status))['queue']['registered']['pending_lower_bound'], 0)

    def test_unknown_fields_versions_types_rejected(self):
        for change in [lambda s: s.update(schema_version=2), lambda s: s['image'].update(token='synthetic'),
                       lambda s: s['queue']['sampled'].update(pending_lower_bound=True),
                       lambda s: s['queue']['sampled'].update(pending_lower_bound=float('nan'))]:
            s = empty_status(); change(s)
            with self.assertRaises(ValueError): serialize_status(s)
        for value in [True, -1, float('inf'), 1 << 64]:
            with self.assertRaises(ValueError): count(value)
        for value in ['bot/token', 'label with space', 'x' * 33]:
            with self.assertRaises(ValueError): alias(value)

    def test_clock_and_size(self):
        self.assertEqual(freshness(0, 16, 15), (16, False))
        for args in [(2, 1, 15), (0, float('nan'), 15), (True, 1, 15)]:
            with self.assertRaises(ValueError): freshness(*args)
        with self.assertRaises(ValueError): timestamp('2999-01-01T00:00:00Z')
        with patch('observability.schema.MAX_STATUS_BYTES', 8):
            with self.assertRaises(ValueError): serialize_status(empty_status())

    def test_shipped_schema_matches(self):
        from pathlib import Path
        self.assertEqual(json.loads(Path(__file__).with_name('observability').joinpath('status.schema.json').read_text()), SCHEMA)
