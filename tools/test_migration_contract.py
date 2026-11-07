"""Versioned cloud to local contract; no network or real credentials."""
import copy
import unittest
from migration_contract import build_plan, validate_plan, validate_binding, plan_digest, normalize_endpoint


class ContractTests(unittest.TestCase):
    def plan(self, **overrides):
        values = dict(operation_id='op1', bot_id='123', source='https://api.telegram.org',
                      target='https://target.example/prefix/', token='123:synthetic',
                      profile={'mode': 'polling'}, action='polling', drop=True, key=b'x'*32)
        values.update(overrides)
        return build_plan(**values)

    def test_target_only_drop_and_order(self):
        p = self.plan()
        self.assertEqual(p['drop_step'], 'target_configure')
        self.assertEqual([s['id'] for s in p['steps']],
                         ['source_delete', 'source_logout', 'target_authorize', 'target_configure'])
        self.assertNotIn('synthetic', str(p))
        self.assertNotIn('https://', str(p))

    def test_all_direction_registries_and_endpoint_roles(self):
        cases = [
            ({'direction': 'local_to_local'}, ['source_delete', 'source_close', 'state_transfer', 'target_authorize', 'target_configure']),
            ({'direction': 'local_to_cloud', 'source': 'https://old.example', 'target': 'https://api.telegram.org',
              'local_mode': False, 'queue_ack': True}, ['source_delete', 'source_logout', 'target_authorize', 'target_configure']),
            ({'direction': 'webhook_only', 'target': 'https://api.telegram.org'}, ['target_configure']),
        ]
        for inputs, ids in cases:
            with self.subTest(inputs=inputs):
                p = self.plan(**inputs)
                self.assertEqual([s['id'] for s in p['steps']], ids)
                self.assertEqual(plan_digest(p), plan_digest(self.plan(**inputs)))
        with self.assertRaises(ValueError):
            self.plan(direction='local_to_cloud')
        with self.assertRaises(ValueError):
            self.plan(source='https://other.example')
        with self.assertRaises(ValueError):
            self.plan(target='https://api.telegram.org')

    def test_closed_version_and_graph(self):
        for name, value in [('engine_version', 1), ('drop_step', 'source_delete'),
                            ('token', 'oops'), ('steps', [])]:
            p = copy.deepcopy(self.plan())
            p[name] = value
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_plan(p)

    def test_bindings_and_normalization(self):
        p = self.plan()
        b = dict(source='https://api.telegram.org/', target='https://TARGET.example:443/prefix',
                 token='123:synthetic', profile={'mode': 'polling'}, action='polling', drop=True)
        validate_binding(p, plan_digest(p), b, b'x'*32)
        b['token'] = '123:changed'
        with self.assertRaises(ValueError):
            validate_binding(p, plan_digest(p), b, b'x'*32)
        for endpoint in ('https://a/../b', 'https://a/%2f', 'https://a/?secret=1', 'https://u:p@a',
                         'https://a/bot123:synthetic/getMe'):
            with self.assertRaises(ValueError):
                normalize_endpoint(endpoint)

    def test_profile_boundary(self):
        p=self.plan(action='set', profile={'mode':'url_only', 'url':'https://receiver.example/path'})
        self.assertEqual(p['profile_scope'],'url_only')
        with self.assertRaises(ValueError):
            self.plan(action='set', profile={'mode':'full', 'secret':'synthetic'})
