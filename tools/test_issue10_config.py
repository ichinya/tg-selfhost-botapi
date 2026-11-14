import unittest
from migration_cli import parser,runtime,parse_env
class ConfigTests(unittest.TestCase):
    def base(self): return dict(BOT_TOKEN='123:synthetic',OLD_BOT_URL='https://api.telegram.org',TELEGRAM_BOT_URL='https://target.example',MIGRATION_ACTION='set',WEB_HOOK='https://receiver.example/hook')
    def test_aliases_and_canonical_precedence(self):
        env=self.base(); args=parser().parse_args(['plan','--operation','test'])
        value=runtime(args,env); self.assertEqual(value.target,env['TELEGRAM_BOT_URL']); self.assertEqual(value.profile['url'],env['WEB_HOOK'])
        env.update(SELF_BOT_URL='https://new.example',WEBHOOK_URL='https://new.example/hook')
        value=runtime(args,env); self.assertEqual(value.target,env['SELF_BOT_URL']); self.assertEqual(value.profile['url'],env['WEBHOOK_URL'])
    def test_explicit_action_and_queue_policy(self):
        args=parser().parse_args(['plan','--operation','test']); env=self.base(); env.pop('MIGRATION_ACTION')
        with self.assertRaises(ValueError): runtime(args,env)
        env.update(MIGRATION_ACTION='polling',DROP_PENDING_UPDATES='maybe')
        with self.assertRaises(ValueError): runtime(args,env)
        env['DROP_PENDING_UPDATES']='false'; self.assertFalse(runtime(args,env).drop)
    def test_dotenv_is_data_and_duplicate_or_expansion_rejected(self):
        self.assertEqual(parse_env('BOT_TOKEN="123:synthetic"')['BOT_TOKEN'],'123:synthetic')
        for value in ('BOT_TOKEN=$(touch marker)','BOT_TOKEN=`touch marker`','BOT_TOKEN=a\nBOT_TOKEN=b','UNKNOWN_KEY=value'):
            with self.subTest(value=value),self.assertRaises(ValueError): parse_env(value)
