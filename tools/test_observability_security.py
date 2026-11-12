import contextlib
import io
import json
from urllib.parse import quote
import unittest
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
from observability import schema
from observability.stats import parse
from observability.webhook import collect_webhooks, project
from observability.server import Collector
from test_observability_stats import sample


class PrivacyTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'posix', 'POSIX permissions/symlink gate; NOTRUN on Windows')
    def test_private_reader_rejects_modes_symlinks_and_size(self):
        from observability.migration import read_json
        from observe_runtime import atomic_write
        with tempfile.TemporaryDirectory() as root:
            secret=Path(root)/'secret.json'; secret.write_text('{"token":"synthetic"}'); secret.chmod(0o644)
            with self.assertRaises(ValueError): read_json(secret,private=True)
            secret.chmod(0o600)
            self.assertEqual(read_json(secret,private=True),{'token':'synthetic'})
            link=Path(root)/'link.json'; link.symlink_to(secret)
            with self.assertRaises(ValueError): read_json(link,private=True)
            secret.write_bytes(b' '*65537)
            with self.assertRaises(ValueError): read_json(secret)

    def test_opt_in_only_fixed_method_and_paused_no_calls(self):
        registry=dict(schema_version=1,enabled=True,instance='a'*64,allow_unobserved_migration=True,
                      bots=[dict(alias='public',credential_file='bot.json')])
        credential={'token':'123456:SYNTHETIC_secret_16'}
        c=Collector()
        with patch('observability.webhook.read_json',side_effect=lambda path,**kw:registry if str(path)=='/registry' else credential), \
             patch('observability.webhook.allowed',return_value=True), \
             patch('observability.webhook.probes.request',return_value=(200,{},b'{"ok":true,"result":{"url":"","pending_update_count":0}}')) as request:
            result=collect_webhooks(c,'/registry')
            self.assertEqual(result['bots'][0]['pending_update_count'],0)
            self.assertTrue(request.call_args.args[2].endswith('/getWebhookInfo'))
            self.assertNotIn('SYNTHETIC',repr(result))

    def test_retry_after_is_bounded_and_not_retried_in_cycle(self):
        registry=dict(schema_version=1,enabled=True,instance='a'*64,allow_unobserved_migration=True,
                      bots=[dict(alias='public',credential_file='bot.json')])
        c=Collector()
        with patch('observability.webhook.read_json',side_effect=lambda path,**kw:registry if str(path)=='/registry' else {'token':'123456:SYNTHETIC_secret_16'}), \
             patch('observability.webhook.allowed',return_value=True), \
             patch('observability.webhook.probes.request',return_value=(429,{},b'{"parameters":{"retry_after":300}}')) as request:
            collect_webhooks(c,'/registry'); collect_webhooks(c,'/registry')
            self.assertEqual(request.call_count,1)

    def test_marker_variants_never_escape_projection_or_diagnostics(self):
        secret='123456:SYNTHETIC_secret_16'
        variants=[secret,quote(secret,safe=''),quote(quote(secret,safe=''),safe=''), ''.join('\\u%04x'%ord(c) for c in secret)]
        for marker in variants:
            out,err=io.StringIO(),io.StringIO()
            with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
                value=parse(sample(b'2')+('new_url\thttps://user:'+marker+'@invalid/'+marker+'?x='+marker+'\n').encode())
                bot=project('public',dict(ok=True,result=dict(url='https://'+marker,pending_update_count=0,last_error_date=1,last_error_message=marker)))
            capture=json.dumps([value,bot])+out.getvalue()+err.getvalue()
            self.assertNotIn(secret,capture); self.assertNotIn(marker,capture)

    def test_default_off_and_ownership_denial_do_not_touch_token(self):
        c=Collector()
        with patch('observability.webhook.probes.request') as request:
            self.assertEqual(collect_webhooks(c)['state'],'disabled')
            registry=dict(schema_version=1,enabled=True,instance='a'*64,allow_unobserved_migration=False,bots=[])
            with patch('observability.webhook.read_json',return_value=registry),patch('observability.webhook.allowed',return_value=False):
                self.assertEqual(collect_webhooks(c,'/synthetic')['reason'],'ownership_required')
            request.assert_not_called()

    def test_status_rejects_arbitrary_metadata(self):
        value=schema.empty_status(); value['image']['Config.Env']=['SECRET']
        with self.assertRaises(ValueError): schema.serialize_status(value)
