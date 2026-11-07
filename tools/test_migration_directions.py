"""Discoverable four-direction/action matrix against real loopback HTTP mocks."""
import json
from pathlib import Path
import time
import unittest

from migration_contract import canonical, plan_digest, registry
from migration_engine import Engine, Runtime, Stop
from migration_http import Client
from migration_mock import Bot, TOKEN, deployment
from migration_probe import Readiness
from migration_store import Journal
from test_migration_state_privacy import MemoryStore


CASES = json.loads((Path(__file__).parent / 'fixtures' / 'migration-executor-cases.json').read_text(encoding='utf-8'))


class DirectionMatrixTests(unittest.TestCase):
    def test_matrix_is_complete_and_uses_the_canonical_graph(self):
        expected = {(direction, action) for direction in CASES['directions']
                    for action in ('preserve', 'set', 'polling')}
        self.assertEqual({(row['direction'], row['action']) for row in CASES['cases']}, expected)
        self.assertEqual(len(CASES['cases']), 12)
        self.assertEqual(len({row['id'] for row in CASES['cases']}), 12)
        self.assertEqual(set(CASES['acceptance_tests']), {f'AC{i}' for i in range(1, 9)})
        for direction, config in CASES['directions'].items():
            with self.subTest(direction=direction):
                graph = registry(direction)
                self.assertEqual([step['id'] for step in graph], config['steps'])
                self.assertEqual([step['dependencies'] for step in graph],
                                 [config['steps'][max(0, i - 1):i] for i in range(len(graph))])

    def test_matrix_and_preserved_polling_finish_without_repeating_mutations(self):
        trace = []
        source, target = Bot('source', trace), Bot('target', trace)
        self.addCleanup(source.close)
        self.addCleanup(target.close)
        variants = [{**row, 'id': row['id'] + '-source-polling', 'source_polling': True}
                    for row in CASES['cases'] if row['action'] == 'preserve']
        for row in CASES['cases'] + variants:
            with self.subTest(case=row['id']):
                source.url = '' if row.get('source_polling') else 'https://fixture.example/old'
                target.url = 'https://fixture.example/preexisting-target'
                for bot in (source, target):
                    bot.active = bot is source
                    bot.calls.clear()
                    bot.faults.clear()
                    bot.effects = dict.fromkeys(bot.effects, 0)
                    bot.queue = [1, 2]
                trace.clear()
                direction, action = row['direction'], row['action']
                config = CASES['directions'][direction]
                selected = source if direction == 'webhook_only' else target
                profile = ({'mode': 'polling'} if action == 'polling' or row.get('source_polling') else
                           {'mode': 'url_only', 'url': source.url if action == 'preserve'
                            else 'https://fixture.example/replacement'})
                runtime = Runtime(source.endpoint, selected.endpoint, TOKEN, profile, action,
                                  fixture=True, direction=direction, local_mode=config['local_mode'],
                                  queue_ack=direction == 'local_to_cloud', cloud_not_before=0)
                journal = Journal(MemoryStore())
                journal.bot = '123'
                client = Client(fixture=True)
                record = deployment(selected.endpoint)
                engine = Engine(journal, client, Readiness(client, lambda: record, journal.key), runtime)
                state = engine.prepare(row['id'], quiescence='fixture-stopped', url_only_ack=True)
                self.assertFalse(any(side == 'target' and method == 'getMe' for side, method, _ in trace))
                self.assertEqual(state['digest'], plan_digest(state['plan']))
                self.assertNotIn(TOKEN, canonical(state['plan']))
                arguments = dict(confirm_digest=state['digest'], quiescence='fixture-stopped',
                                 endpoint_change='fixture-changed', application_start='fixture-started', resume=True)
                if direction == 'local_to_local':
                    with self.assertRaises(Stop) as stopped:
                        engine.run(state, **arguments)
                    self.assertEqual(stopped.exception.reason, 'state_transfer_checkpoint_required')
                    self.assertFalse(any(side == 'target' and method != 'probe' for side, method, _ in trace))
                    arguments['state_transfer'] = dict(
                        operation_id=row['id'], digest=state['digest'],
                        close_attempt=state['steps']['source_close'][-1]['id'],
                        source_fingerprint=state['plan']['source_fingerprint'],
                        target_fingerprint=state['plan']['target_fingerprint'],
                        target_deployment=state['deployment'], source_closed=True, no_writers=True,
                        layout_valid=True, source_manifest='a' * 64, target_manifest='a' * 64,
                        source_deployment='b' * 64, uid=1000, gid=1000, observed_at=time.time())
                result = engine.run(state, **arguments)
                self.assertEqual(result['results']['migration_outcome'], 'confirmed')
                self.assertEqual(result['results']['delivery_verification'], 'NOTRUN')
                self.assertEqual(selected.url, '' if profile['mode'] == 'polling' else profile['url'])
                if config['detach']:
                    detach = (source.side, config['detach'])
                    actions = [(side, method) for side, method, _ in trace]
                    self.assertLess(actions.index(detach), actions.index((selected.side, 'getMe')))
                    self.assertEqual(source.effects[config['detach']], 1)
                else:
                    self.assertEqual(source.effects['logOut'] + source.effects['close'], 0)
                mutations = sum(selected.effects[name] for name in ('setWebhook', 'deleteWebhook'))
                self.assertEqual(mutations, 0 if direction == 'webhook_only' and action == 'preserve' else 1)
                before = (dict(source.effects), dict(target.effects))
                engine.run(state, **arguments)
                self.assertEqual((source.effects, target.effects), before)
                self.assertTrue(all(params.get('drop_pending_updates') != 'true'
                                    for side, method, params in trace if side == 'source'))
