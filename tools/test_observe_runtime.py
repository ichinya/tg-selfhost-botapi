import json
import unittest
from observe_runtime import collect


class RuntimeProducerTests(unittest.TestCase):
    def runner(self, race=False):
        calls = []
        def run(args):
            calls.append(args)
            if 'ps' in args: return 'a' * 64
            if args[:2] == ['docker', 'inspect']:
                return json.dumps(dict(Id='a'*64, Image='sha256:'+'b'*64,
                     State=dict(Running=True, StartedAt='changed' if race and sum(a[:2]==['docker','inspect'] for a in calls)>1 else '2026', Pid=1)))
            if args[:3] == ['docker', 'image', 'inspect']:
                return json.dumps(dict(Id='sha256:'+'b'*64, Config=dict(Labels={'org.opencontainers.image.source':'https://github.com/ichinya/tg-selfhost-botapi', 'evil':'TOKEN'}), Os='linux', Architecture='amd64', RepoDigests=[]))
            if args[-1] == '/proc/1/cmdline': return 'telegram-bot-api\x00--dir=/state\x00--temp-dir=/tmp\x00'
            if args[-1] == '/proc/1/status': return 'Uid:\t101\t101\t101\t101\nGid:\t101\t101\t101\t101'
            if '--version' in args: return '9.2'
            if 'stat' in args: return 'abcdef 10 4096'
            raise ValueError('SECRET')
        return run, calls

    def test_actual_identity_fs_no_digest_and_no_private_values(self):
        runner, calls = self.runner()
        result = collect(['docker','compose'], runner=runner)
        self.assertIsNone(result['image']['registry_digest'])
        self.assertEqual(result['storage']['filesystems'][0]['available_bytes'], 40960)
        self.assertEqual(result['storage']['filesystems'][0]['filesystem'], result['storage']['filesystems'][1]['filesystem'])
        self.assertNotIn('TOKEN', repr(result))
        self.assertFalse(any('setWebhook' in str(a) for a in calls))

    def test_recreate_and_ambiguous_target_fail(self):
        runner, _ = self.runner(True)
        with self.assertRaises(ValueError): collect(['docker','compose'], runner=runner)
        with self.assertRaises(ValueError): collect(['docker','compose'], runner=lambda _: 'a\nb')
