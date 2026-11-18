import contextlib
import io
import json
from unittest import mock
import unittest
from migration_cli import parse_env,main,parser,runtime,legacy


class CliTests(unittest.TestCase):
    def test_legacy_success_is_one_json_document(self):
        output = io.StringIO()
        def plan(_):
            print(json.dumps({'operation_id': 'op', 'digest': 'a' * 64}))
            return 0
        with mock.patch('migration_cli.main', side_effect=plan), contextlib.redirect_stdout(output):
            self.assertEqual(legacy(['--operation', 'op']), 2)
        self.assertEqual(json.loads(output.getvalue())['reason'], 'plan_confirmation_required')

    def test_canonical_cloud_target_uses_cloud_readiness(self):
        r = mock.Mock(direction='local_to_cloud', target='https://API.TELEGRAM.ORG:443', fixture=False, bot_id='123')
        journal = mock.MagicMock()
        journal.lock.return_value = contextlib.nullcontext()
        with mock.patch('migration_cli.StateStore'), mock.patch('migration_cli.Journal', return_value=journal), \
             mock.patch('migration_cli.runtime', return_value=r), mock.patch('migration_cli.Client'), \
             mock.patch('migration_cli.CloudReadiness') as readiness, mock.patch('migration_cli.Engine'), \
             mock.patch('migration_cli.view', return_value={}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['plan', '--operation', 'op']), 0)
            readiness.assert_called_once()

    def test_legacy_does_not_inject_dotenv_or_guess_a_source(self):
        with mock.patch('migration_cli.main', return_value=4) as delegated, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(legacy(['--operation', 'op', '--action', 'polling']), 4)
        delegated.assert_called_once_with(['plan', '--operation', 'op', '--action', 'polling'])

    def test_legacy_preserves_equals_operation(self):
        with mock.patch('migration_cli.main', return_value=4) as delegated, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(legacy(['--operation=chosen', '--action', 'polling']), 4)
        delegated.assert_called_once_with(['plan', '--operation=chosen', '--action', 'polling'])

    def test_empty_docker_inspect_fails_closed_before_store(self):
        with mock.patch('migration_probe.DockerEvidence.run', return_value='[]'), mock.patch('migration_cli.StateStore') as store, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(['plan', '--operation', 'op', '--docker-container', 'fixture']), 4)
            store.assert_not_called()
            self.assertIn('invalid_input_or_state', out.getvalue())

    def test_env_is_data_only(self):
        self.assertEqual(parse_env("# ignored\nOLD_BOT_URL=https://api.telegram.org\nBOT_TOKEN='123:synthetic'")['BOT_TOKEN'],'123:synthetic')
        for text in ('BOT_TOKEN=$(execute)','BOT_TOKEN=`execute`','export BOT_TOKEN=x','PATH=x','BOT_TOKEN=x\nBOT_TOKEN=y'):
            with self.subTest(text=text),self.assertRaises(ValueError):
                parse_env(text)

    def test_legacy_token_never_echoed(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            code=main(['123:never_echo_this'])
        self.assertEqual(code,4)
        self.assertNotIn('never_echo_this',out.getvalue())

    def test_noninteractive_missing_secret(self):
        args=parser().parse_args(['plan','--operation','op','--action','polling'])
        with mock.patch('sys.stdin.isatty',return_value=False),self.assertRaises(ValueError):
            runtime(args,{'OLD_BOT_URL':'https://api.telegram.org','SELF_BOT_URL':'https://target.example'})

    def test_cli_endpoint_precedence_and_queue_policy(self):
        args=parser().parse_args(['plan','--operation','op','--source','https://api.telegram.org','--action','polling'])
        r=runtime(args,{'OLD_BOT_URL':'https://ignored.example','SELF_BOT_URL':'https://target.example','BOT_TOKEN':'123:synthetic'})
        self.assertEqual(r.source,'https://api.telegram.org')
        self.assertFalse(r.drop)

    def test_missing_state_status_never_requests_http(self):
        with mock.patch('migration_cli.StateStore',side_effect=ValueError('missing')):
            with mock.patch('migration_cli.Client') as client,contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['status','--operation','op']),4)
                client.assert_not_called()
