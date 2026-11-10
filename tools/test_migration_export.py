import unittest
from migration_export import export_operation
from migration_contract import build_plan, plan_digest


class ExportTests(unittest.TestCase):
    def test_same_plan_identity_and_no_independent_executor(self):
        plan=build_plan(operation_id='op',bot_id='123',source='https://api.telegram.org',target='https://target.example',
                        token='123:secret_canary',profile={'mode':'polling'},action='polling',drop=False,key=b'x'*32)
        result=export_operation({'plan':plan,'digest':plan_digest(plan)})
        self.assertEqual(result['digest'],plan_digest(plan))
        text=str(result)
        for secret in ('secret_canary','https://','curl','binding.key'):
            self.assertNotIn(secret,text)
        self.assertTrue(all('--operation op' in command for command in result['commands']))
