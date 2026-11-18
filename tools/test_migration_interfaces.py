"""Canonical plan parity across entrypoints, with no paid or external APIs."""
import contextlib
import io
import json
import os
from pathlib import Path
import threading
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from migration_cli import main
from migration_contract import canonical
from migration_engine import Engine,Runtime
from migration_export import export_operation
from migration_helper import Application
from migration_http import Client
from migration_mock import Bot,TOKEN,deployment
from migration_probe import Readiness
from migration_store import Journal,StateError
from test_migration_state_privacy import MemoryStore


class Authority(MemoryStore):
    """Boundary double with real directory discovery and independent bot locks."""
    def __init__(self):
        super().__init__()
        self.locks={}
        owner=self
        class Root:
            def __fspath__(self): return str(Path(__file__).resolve().parents[1])
            def glob(self, pattern):
                from types import SimpleNamespace
                return [SimpleNamespace(stem=name) for name in owner.rows]
            def __truediv__(self, name):
                class Entry:
                    def exists(self): return name.removesuffix('.json') in owner.rows
                return Entry()
        self.root=Root()
    def binding_key(self,create=True):
        return b'x'*32
    @contextlib.contextmanager
    def lock(self,bot):
        lock=self.locks.setdefault(bot,threading.Lock())
        if not lock.acquire(blocking=False): raise StateError('busy')
        try: yield 0
        finally: lock.release()
    def write(self,name,row):
        super().write(name,row)
    def close(self):
        pass


class InterfaceTests(unittest.TestCase):
    def test_offline_status_does_not_require_provider_or_deployment_inputs(self):
        store=Authority()
        journal=Journal(store)
        runtime=Runtime('https://api.telegram.org','https://target.example',TOKEN,{'mode':'polling'},'polling')
        with journal.lock('123'):
            journal.create(runtime.plan('offline',journal.key),None)
        output=io.StringIO()
        with patch.dict(os.environ,{'MIGRATION_TRUST_FILE':'unavailable'},clear=True), \
             patch('migration_cli.StateStore',return_value=store), \
             patch('migration_cli.private_json',side_effect=AssertionError('offline status read private provider inputs')), \
             patch('migration_cli.Client') as client,contextlib.redirect_stdout(output):
            self.assertEqual(main(['status','--operation','offline']),0)
            client.assert_not_called()

    def test_plan_parity_core_cli_helper_and_export_all_directions(self):
        for direction in ('cloud_to_local','local_to_local','local_to_cloud','webhook_only'):
            with self.subTest(direction=direction):
                source,target=Bot('source'),Bot('target')
                try:
                    target_url=source.endpoint if direction=='webhook_only' else target.endpoint
                    runtime=Runtime(source.endpoint,target_url,TOKEN,{'mode':'polling'},'polling',fixture=True,
                                    direction=direction,local_mode=direction!='local_to_cloud',queue_ack=True,cloud_not_before=0)
                    record=deployment(target_url)
                    binding=Readiness(Client(fixture=True),lambda:record,b'x'*32).check(target_url)
                    expected=runtime.plan('parity',b'x'*32,binding)
                    store=Authority()
                    env={'BOT_TOKEN':TOKEN,'OLD_BOT_URL':source.endpoint,'SELF_BOT_URL':target_url,
                         'MIGRATION_DIRECTION':direction,'MIGRATION_LOCAL_MODE':'true' if runtime.local_mode else 'false',
                         'MIGRATION_QUEUE_ACK':'true','MIGRATION_CLOUD_NOT_BEFORE':'0'}
                    out=io.StringIO()
                    with patch.dict(os.environ,env,clear=True), patch('migration_cli.StateStore',return_value=store), \
                         patch('migration_cli.private_json',return_value=record),contextlib.redirect_stdout(out):
                        code=main(['plan','--operation','parity','--action','polling','--fixture-loopback',
                                   '--evidence-file','synthetic','--quiescence-receipt','fixture'])
                    self.assertEqual(code,0,out.getvalue())
                    cli=json.loads(out.getvalue())
                    self.assertEqual(cli['plan'],expected)
                    with patch('migration_helper.private_json',return_value=record):
                        app=Application(dict(state_dir='boundary-double',allowed_endpoints=[source.endpoint,target_url],evidence_file='synthetic',trust_file=None,fixture=True))
                        @contextlib.contextmanager
                        def context(**kw): yield Journal(store),record
                        app.context=context
                        try:
                            values={k:v for k,v in runtime.__dict__.items() if k!='fixture'}
                            helper=app.plan({'operation_id':'parity','runtime':values,'quiescence':'fixture'})
                            self.assertEqual(helper['plan'],cli['plan'])
                            exported=export_operation(Journal(store).load('parity'))
                            self.assertEqual(exported['digest'],helper['digest'])
                            self.assertNotIn(TOKEN,canonical(exported))
                        finally: app.close()
                finally: target.close(); source.close()
