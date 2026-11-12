"""Execute shipped exports with an offline curl peer and byte-exact captures.

Only synthetic fixtures enter private temporary captures. The mock never invokes
curl or a socket. A separate loopback peer tests real curl/HTTP decoding.
"""
import base64
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tools/fixtures/issue8-shell-cases.json'
CASES = json.loads(FIXTURE.read_text(encoding='utf-8'))
TOKEN = CASES['canaries']['token']
SECRET = CASES['canaries']['secret']
MUTATIONS = {'deleteWebhook', 'logOut', 'setWebhook', 'close'}


def node(*args, data=None):
    result = subprocess.run(['node', str(ROOT / 'tools/issue8_shell_harness.cjs'), *args],
                            input=json.dumps(data) if data is not None else None,
                            text=True, capture_output=True, cwd=ROOT, timeout=30)
    if result.returncode:
        raise AssertionError('Node shell harness failed; private output omitted')
    return result.stdout


def mock_curl(args):
    """Private PATH executable entry point, with one NUL-framed file per call."""
    audit = Path(os.environ['ISSUE8_CAPTURE'])
    number = len(list(audit.glob('*.argv')))
    stem = audit / f'{number:04}'
    stem.with_suffix('.argv').write_bytes(b''.join(os.fsencode(arg) + b'\0' for arg in args))
    def option(name):
        return args[args.index(name) + 1]
    config = b''
    if '--config' in args:
        config = Path(option('--config')).read_bytes()
        # curl config serialization is JSON quoted by wp_request/canonical diagnostics.
        match = re.fullmatch(rb'url = (".*")\n?', config)
        if not match:
            raise ValueError('invalid private config')
        url = json.loads(match[1])
    else:
        url = args[-1]
    method = url.rsplit('/', 1)[-1] if '/bot' in url else 'probe'
    role = 'source' if '/source/' in url else 'target'
    scalars, files, fields = {}, {}, {}
    for index, arg in enumerate(args):
        if arg == '--data-urlencode':
            value = args[index + 1]
            if '@' in value and '=' not in value.split('@', 1)[0]:
                key, filename = value.split('@', 1)
                raw = Path(filename).read_bytes()
                scalars[key] = base64.b64encode(raw).decode('ascii')
                fields[key] = raw.decode('utf-8')
            else:
                key, value = value.split('=', 1)
                fields[key] = value
        elif arg == '--form':
            value = args[index + 1]
            match = re.fullmatch(r'([a-z_]+)=([<@])"([^"]+)"(?:;filename=certificate.pem)?', value)
            if not match:
                raise ValueError('invalid multipart argument')
            key, kind, filename = match.groups()
            raw = Path(filename).read_bytes()
            (files if kind == '@' else scalars)[key] = base64.b64encode(raw).decode('ascii')
            if kind == '<':
                fields[key] = raw.decode('utf-8')
        elif arg == '--form-string':
            key, value = args[index + 1].split('=', 1)
            fields[key] = value
    record = {'method':method, 'role':role, 'config':base64.b64encode(config).decode('ascii'),
              'scalars':scalars, 'files':files, 'fields':fields}
    stem.with_suffix('.json').write_text(json.dumps(record), encoding='utf-8')
    if os.environ.get('ISSUE8_PAUSE') == method:
        signal.signal(signal.SIGINT, lambda *_: sys.exit(130))
        (audit / 'paused').touch()
        time.sleep(30)
    if os.environ.get('ISSUE8_FAIL') == method:
        return 7
    state_file = audit / 'state.json'
    source_file = os.environ.get('ISSUE8_SOURCE_FILE')
    source_url = json.loads(Path(source_file).read_text(encoding='utf-8')) if source_file else ''
    profile = {'url':source_url, 'max_connections':7,
               'allowed_updates':['message'], 'has_custom_certificate':False,
               'pending_update_count':0, 'ip_address':'203.0.113.7'}
    if state_file.exists():
        profile = json.loads(state_file.read_text(encoding='utf-8'))
    if method == 'probe':
        status, reply = '404', {'ok':False, 'error_code':404, 'description':'Not Found'}
    else:
        status, result = '200', True
        if method == 'getMe':
            result = {'id':123, 'first_name':'Synthetic'}
        elif method == 'getWebhookInfo':
            result = profile
        elif method == 'setWebhook':
            profile.update(url=fields['url'], max_connections=int(fields['max_connections']),
                           allowed_updates=json.loads(fields['allowed_updates']),
                           has_custom_certificate='certificate' in files)
            if 'ip_address' in fields:
                profile['ip_address'] = fields['ip_address']
            state_file.write_text(json.dumps(profile), encoding='utf-8')
        reply = {'ok':True, 'result':result}
    Path(option('--output')).write_text(json.dumps(reply), encoding='utf-8')
    sys.stdout.write(status)
    return 0


class ExportContractTests(unittest.TestCase):
    def test_actual_root_clipboard_and_helper_bootstrap(self):
        self.assertIn('issue8 checks passed', node())


@unittest.skipIf(os.name == 'nt', 'POSIX Bash runtime; verification deferred to CI/gates')
class ShellSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for executable in ('bash', 'jq', 'node', 'curl', 'openssl'):
            if not shutil.which(executable):
                raise AssertionError('Required shell runtime missing: ' + executable)
        if os.geteuid() == 0:
            raise AssertionError('Shell safety acceptance must execute as non-root')
        cls.exports = {mode:json.loads(node('--export', data={'mode':mode}))
                       for mode in ('official-to-self', 'hook-only', 'self-to-self', 'self-to-official')}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='issue8-')
        self.addCleanup(self.tmp.cleanup)
        self.private = Path(self.tmp.name)
        self.checkout = self.private / 'checkout'
        self.checkout.mkdir()
        self.capture = self.private / 'captures'
        self.capture.mkdir()
        bindir = self.private / 'bin'
        bindir.mkdir()
        mock = bindir / 'curl'
        mock.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' ' +
                        shlex.quote(str(Path(__file__).resolve())) + ' --mock-curl "$@"\n')
        mock.chmod(0o700)
        # Observation delay has no bearing on quoting or file framing.
        sleep = bindir / 'sleep'
        sleep.write_text('#!/bin/sh\nexit 0\n')
        sleep.chmod(0o700)
        token = self.private / 'token \' " $(>marker) `>marker` λ\nfile'
        token.write_text(TOKEN)
        secret = self.private / 'secret \' " $(>marker) `>marker` λ\nfile'
        secret.write_text(SECRET)
        token.chmod(0o600)
        secret.chmod(0o600)
        self.env = {k:v for k,v in os.environ.items() if k in ('PATH', 'HOME', 'LANG')}
        self.env.update(PATH=str(bindir)+os.pathsep+self.env['PATH'], BOT_TOKEN_FILE=str(token),
                        SELF_BOT_URL='https://target.invalid/target', OFFICIAL_BOT_URL='https://source.invalid/source',
                        WEBHOOK_SECRET_MODE='provided', WEBHOOK_SECRET_TOKEN_FILE=str(secret),
                        WEBHOOK_IP_MODE='pinned', WEBHOOK_IP_ADDRESS='203.0.113.7',
                        WEBHOOK_CERTIFICATE_MODE='none', WEBHOOK_ALLOWED_UPDATES='["message"]',
                        WEBHOOK_MAX_CONNECTIONS='7', ISSUE8_CAPTURE=str(self.capture))

    def records(self):
        records = []
        for file in sorted(self.capture.glob('*.json')):
            if file.name == 'state.json':
                continue
            record = json.loads(file.read_text(encoding='utf-8'))
            record['argv'] = file.with_suffix('.argv').read_bytes().split(b'\0')[:-1]
            records.append(record)
        return records

    def fresh_capture(self):
        for file in self.capture.iterdir():
            file.unlink()
        # Diagnostics intentionally retain journals; each execution gets a new workspace.
        self.checkout = Path(tempfile.mkdtemp(prefix='checkout-', dir=self.private))

    def script(self, surface):
        script = self.checkout / 'migration-plan.sh'
        if surface == 'standalone':
            shutil.copyfile(ROOT / 'migrate_off_to_self.sh', script)
        elif surface.endswith(':target'):
            script.write_text(self.exports[surface.split(':')[0]]['target'], encoding='utf-8')
        else:
            script.write_text(self.exports[surface]['script'], encoding='utf-8')
        return script

    def execute(self, surface, *, webhook='', source='', extra=None):
        source_file = self.private / 'source-url.json'
        source_file.write_text(json.dumps(source), encoding='utf-8')
        env = {**self.env, 'WEBHOOK_URL':webhook, 'ISSUE8_SOURCE_FILE':str(source_file), **(extra or {})}
        result = subprocess.run(['bash', '-x', str(self.script(surface))], cwd=self.checkout,
                                env=env, input='y\ny\ny\n', text=True, capture_output=True, timeout=15)
        for private in (TOKEN, SECRET, 'BEGIN CERTIFICATE', 'https://example.invalid/'):
            self.assertFalse(private in result.stdout+result.stderr, 'Private value leaked into output/trace')
        self.assertFalse((self.checkout / 'marker').exists(), 'Payload executed a nested command')
        return result

    def assert_transport(self, records, expected, certificate=None, updates=None):
        calls = [r for r in records if r['method'] == 'setWebhook']
        self.assertEqual(len(calls), 1, 'A successful round trip requires exactly one setWebhook')
        call = calls[0]
        scalars = {k:base64.b64decode(v) for k,v in call['scalars'].items()}
        expected_scalars = {'url':expected.encode(), 'allowed_updates':json.dumps(updates or ['message'], separators=(',', ':'), ensure_ascii=False).encode(),
                            'max_connections':b'7', 'ip_address':b'203.0.113.7', 'secret_token':SECRET.encode()}
        self.assertTrue(scalars == expected_scalars, 'Scalar file bytes differ; private captures omitted')
        self.assertEqual(call['fields']['drop_pending_updates'], 'false')
        if certificate is None:
            self.assertEqual(call['files'], {})
        else:
            self.assertTrue(base64.b64decode(call['files']['certificate']) == certificate, 'Certificate bytes differ; private captures omitted')
        for record in records:
            argv = record['argv']
            self.assertEqual(argv[0], b'-q')
            self.assertIn(b'--globoff', argv)
            self.assertEqual(argv[argv.index(b'--proto')+1], b'=http,https')
            self.assertNotIn(b'--location', argv)
            self.assertNotIn(b'-L', argv)
            if record['method'] == 'probe':
                continue
            config = base64.b64decode(record['config'])
            config_url = json.loads(config.split(b' = ', 1)[1])
            base = self.env['OFFICIAL_BOT_URL'] if record['role'] == 'source' else self.env['SELF_BOT_URL']
            self.assertTrue(config_url == base+'/bot'+TOKEN+'/'+record['method'], 'Private config URL differs; capture omitted')
            self.assertFalse(TOKEN.encode() in b'\0'.join(argv), 'Token leaked into argv')
            self.assertFalse(SECRET.encode() in b'\0'.join(argv), 'Secret leaked into argv')
            directory = Path(os.fsdecode(argv[argv.index(b'--config')+1])).parent
            self.assertFalse(directory.exists(), 'Private curl snapshot not cleaned')
        # Verify complete argc/argv for the dynamic set request, normalizing only private temp paths.
        argv = [os.fsdecode(a) for a in call['argv']]
        config_dir = str(Path(argv[argv.index('--config')+1]).parent)
        normalized = [a.replace(config_dir, '<private>') for a in argv]
        prefix = ['-q','-sS','--connect-timeout','5','--max-time','30','--globoff','--proto','=http,https',
                  '--output','<private>/response','--write-out','%{http_code}','--config','<private>/request.conf','-X','POST']
        # Standalone diagnostics owns the same data transport with its own capture options.
        if '--retry' in argv:
            prefix = ['-q','--retry','0','-sS','--connect-timeout','5','--max-time','30','--globoff','--proto','=http,https',
                      '--output','<request>/.raw-body','--write-out','%{http_code}','-X','POST','--config','<private>/request.conf']
            normalized = [re.sub(r'[^ ]*/request-[^/]+/\.raw-body$', '<request>/.raw-body', a) for a in normalized]
        if certificate is None:
            suffix = sum((['--data-urlencode', key+'@<private>/'+file] for key,file in
                          [('url','url'),('allowed_updates','allowed_updates'),('max_connections','max_connections')]), [])
            suffix += ['--data-urlencode','drop_pending_updates=false','--data-urlencode','ip_address@<private>/ip','--data-urlencode','secret_token@<private>/secret']
        else:
            suffix = sum((['--form', key+'=<"<private>/'+file+'"'] for key,file in
                          [('url','url'),('allowed_updates','allowed_updates'),('max_connections','max_connections')]), [])
            suffix += ['--form-string','drop_pending_updates=false','--form','ip_address=<"<private>/ip"',
                       '--form','certificate=@"<private>/certificate";filename=certificate.pem','--form','secret_token=<"<private>/secret"']
        self.assertEqual(normalized, prefix+suffix)

    def test_full_exports_all_modes_and_standalone_exact_calls(self):
        for surface in ('standalone','official-to-self','hook-only','self-to-self:target','self-to-official:target'):
            for inherited in (False, True):
                for case in CASES['cases']:
                    if not case['valid_url'] or not case['value']:
                        continue
                    if surface.endswith(':target') and inherited:
                        continue  # A separately accepted target stage requires an explicit saved URL.
                    with self.subTest(surface=surface, inherited=inherited, case=case['id']):
                        self.fresh_capture()
                        result = self.execute(surface, webhook='' if inherited else case['value'], source=case['value'] if inherited else '')
                        self.assertEqual(result.returncode, 0, 'Migration surface failed; private output omitted')
                        records = self.records()
                        self.assert_transport(records, case['value'])
                        expected = (['probe','getMe','getWebhookInfo','deleteWebhook','logOut','getMe','setWebhook','getWebhookInfo']
                                    if surface == 'standalone' else
                                    ['probe','getMe','getWebhookInfo','getWebhookInfo','deleteWebhook','logOut','getMe','setWebhook','getWebhookInfo','getWebhookInfo']
                                    if surface == 'official-to-self' else
                                    ['getMe','getWebhookInfo','getWebhookInfo','setWebhook','getWebhookInfo','getWebhookInfo'])
                        self.assertEqual([r['method'] for r in records], expected)
                        if surface in ('standalone', 'official-to-self'):
                            logout = expected.index('logOut')
                            roles = ['target'] + ['source'] * logout + ['target'] * (len(expected)-logout-1)
                        else:
                            roles = ['target'] * len(expected)
                        self.assertEqual([r['role'] for r in records], roles)

    def test_invalid_source_and_explicit_urls_stop_before_mutations(self):
        for surface in ('standalone','official-to-self','hook-only','self-to-self:target','self-to-official:target'):
            for case in (c for c in CASES['cases'] if not c['valid_url']):
                for inherited in (True, False):
                    if not inherited and '\0' in case['value']:
                        # An OS environment cannot represent NUL; JSON source path below must reject it explicitly.
                        continue
                    with self.subTest(surface=surface, case=case['id'], inherited=inherited):
                        self.fresh_capture()
                        result = self.execute(surface, source=case['value'] if inherited else '', webhook='' if inherited else case['value'])
                        self.assertNotEqual(result.returncode, 0)
                        self.assertFalse(any(r['method'] in MUTATIONS for r in self.records()))
        for value in (None, 123, {}, []):
            self.fresh_capture()
            result = self.execute('official-to-self', source=value)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(any(r['method'] in MUTATIONS for r in self.records()))

    def test_manual_exports_stop_before_curl_and_empty_polling_semantics(self):
        for mode in ('self-to-self','self-to-official'):
            self.fresh_capture()
            self.assertEqual(self.execute(mode).returncode, 2)
            self.assertEqual(self.records(), [])
        for mode in ('official-to-self','hook-only'):
            self.fresh_capture()
            self.assertEqual(self.execute(mode).returncode, 0)
            methods = [r['method'] for r in self.records()]
            self.assertNotIn('setWebhook', methods)
            self.assertEqual(methods.count('deleteWebhook'), 1)

    def test_literal_serializer_scalar_bytes_and_multipart_snapshots(self):
        values = [c['value'] for c in CASES['cases'] if '\0' not in c['value']]
        quotes = json.loads(node('--quote', data=values))
        for value, literal in zip(values, quotes):
            result = subprocess.run(['bash','-c', "printf '%s' " + literal], cwd=self.checkout, capture_output=True, check=True)
            self.assertEqual(result.stdout, value.encode())
            self.assertFalse((self.checkout/'marker').exists())
        certificate = self.private / CASES['canaries']['certificate_name']
        key = self.private / 'test-only.key'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=example.invalid',
                        '-keyout',str(key),'-out',str(certificate)], capture_output=True, check=True, timeout=15)
        certificate.chmod(0o600)
        for multipart in (False, True):
            for value in values:
                self.fresh_capture()
                profile = {'profile':{'url':value,'allowed_updates':[value], 'max_connections':7,'secret_mode':'provided',
                                      'ip_mode':'pinned','ip_address':'203.0.113.7','certificate_mode':'provided' if multipart else 'none'}}
                profile_file = self.private / 'scalar-profile.json'
                profile_file.write_text(json.dumps(profile), encoding='utf-8')
                script = self.checkout / 'scalar.sh'
                script.write_text('set +x\nset -euo pipefail\nWP_SCRIPT_DIR="$PWD"\n'+
                                  (ROOT/'tools/webhook_profile_runtime.sh').read_text(encoding='utf-8')+
                                  '\nwp_load\nWP_PROFILE=$(cat -- "$ISSUE8_PROFILE")\n'+
                                  'wp_private_file "$WEBHOOK_SECRET_TOKEN_FILE" "$WP_TMP/secret"\n'+
                                  ('wp_private_file "$WEBHOOK_CERTIFICATE_FILE" "$WP_TMP/certificate"\n' if multipart else '')+
                                  'wp_set\n', encoding='utf-8')
                env = {**self.env, 'ISSUE8_PROFILE':str(profile_file), 'WEBHOOK_CERTIFICATE_FILE':str(certificate)}
                result = subprocess.run(['bash','-x',str(script)], cwd=self.checkout, env=env, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, 'Scalar transport failed; private output omitted')
                self.assert_transport(self.records(), value, certificate.read_bytes() if multipart else None, [value])
                self.assertFalse((self.checkout/'marker').exists())

    def test_marker_positive_control_and_trusted_env_round_trip(self):
        subprocess.run(['bash','-c', ': > marker'], cwd=self.checkout, check=True)
        with self.assertRaises(AssertionError):
            self.assertFalse((self.checkout/'marker').exists())
        (self.checkout/'marker').unlink()
        for c in (c for c in CASES['cases'] if c['valid_url'] and c['value']):
            self.fresh_capture()
            settings = self.private/'trusted.env'
            settings.write_text('WEBHOOK_URL='+shlex.quote(c['value'])+'\n', encoding='utf-8')
            # Absence in process environment permits the file tier to exercise Bash %q serialization.
            script = self.script('hook-only')
            env = {**self.env, 'ENV_FILE':str(settings)}
            result = subprocess.run(['bash','-x',str(script)], cwd=self.checkout, env=env,
                                    input='y\n', text=True, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0)
            self.assert_transport(self.records(), c['value'])
            self.assertFalse((self.checkout/'marker').exists())

    def test_failure_and_signal_cleanup(self):
        result = self.execute('official-to-self', webhook='https://example.invalid/private', extra={'ISSUE8_FAIL':'setWebhook'})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sum(r['method']=='setWebhook' for r in self.records()), 1)
        self.assertEqual(self.records()[-1]['method'], 'setWebhook', 'UNKNOWN must stop dependent requests')
        for r in self.records():
            if r['config']:
                argv = r['argv']
                self.assertFalse(Path(os.fsdecode(argv[argv.index(b'--config')+1])).parent.exists())
        for sig in (signal.SIGINT, signal.SIGTERM):
            self.fresh_capture()
            env = {**self.env, 'WEBHOOK_URL':'https://example.invalid/private', 'ISSUE8_PAUSE':'setWebhook'}
            process = subprocess.Popen(['bash', str(self.script('hook-only'))], cwd=self.checkout, env=env,
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            try:
                process.stdin.write(b'y\n')
                process.stdin.flush()
                deadline = time.monotonic()+10
                while not (self.capture/'paused').exists() and process.poll() is None and time.monotonic()<deadline:
                    time.sleep(.02)
                self.assertTrue((self.capture/'paused').exists(), 'Signal must reach an active mock request')
                os.killpg(process.pid, sig)
                stdout, stderr = process.communicate(timeout=5)
                self.assertNotEqual(process.returncode, 0)
                self.assertFalse(TOKEN.encode() in stdout+stderr, 'Token leaked after signal')
                for r in self.records():
                    if r['config']:
                        argv=r['argv']
                        self.assertFalse(Path(os.fsdecode(argv[argv.index(b'--config')+1])).parent.exists())
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate()

    def test_real_curl_and_python_http_decode_the_same_payloads(self):
        from tools.webhook_profile_http_mock import MockAPI
        from migration_http import Client
        api=MockAPI()
        thread=api.start()
        self.addCleanup(api.server_close)
        self.addCleanup(thread.join, 5)
        self.addCleanup(api.shutdown)
        for c in (c for c in CASES['cases'] if c['valid_url'] and c['value']):
            for multipart in (False, True):
                self.fresh_capture()
                env={**self.env, 'PATH':os.environ['PATH'], 'WEBHOOK_URL':c['value'],
                     'SELF_BOT_URL':api.base+'/target', 'OFFICIAL_BOT_URL':api.base+'/source', 'NO_PROXY':'127.0.0.1', 'no_proxy':'127.0.0.1'}
                cert=self.private/'public.pem'
                key=self.private/'wire-only.key'
                if multipart:
                    if not cert.exists():
                        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=example.invalid',
                                        '-keyout',str(key),'-out',str(cert)],capture_output=True,check=True,timeout=15)
                        cert.chmod(0o600)
                    env.update(WEBHOOK_CERTIFICATE_MODE='provided',WEBHOOK_CERTIFICATE_FILE=str(cert))
                api.applied=False
                api.source['url']=''
                before=len(api.calls)
                result=subprocess.run(['bash',str(self.script('official-to-self'))],cwd=self.checkout,env=env,
                                      input='y\n',text=True,capture_output=True,timeout=15)
                self.assertEqual(result.returncode,0,'Real curl transport failed; private output omitted')
                for private in (TOKEN, SECRET, c['value'], 'BEGIN CERTIFICATE'):
                    self.assertFalse(private in result.stdout+result.stderr, 'Private value leaked in real-curl output')
                call=next(r for r in api.calls[before:] if r['method']=='setWebhook')
                self.assertTrue(call['fields']['url'] == c['value'], 'Real curl URL bytes differ')
                self.assertTrue(call['fields']['secret_token'] == SECRET, 'Real curl secret bytes differ')
                self.assertTrue(call['files'].get('certificate') == (cert.read_bytes() if multipart else None), 'Real curl certificate bytes differ')
                params={'url':c['value'],'allowed_updates':['message'],'max_connections':7,'secret_token':SECRET}
                if multipart:
                    params['certificate_pem']=cert.read_text()
                reply=Client(fixture=True).request(api.base+'/target','setWebhook',token=TOKEN,params=params,effect=True)
                self.assertEqual(reply.outcome,'confirmed')
                self.assertTrue(api.calls[-1]['fields']['url'] == c['value'], 'Python HTTP URL bytes differ')
                self.assertTrue(api.calls[-1]['files'].get('certificate') == (cert.read_bytes() if multipart else None), 'Python HTTP certificate bytes differ')


if __name__ == '__main__':
    if sys.argv[1:2] == ['--mock-curl']:
        try:
            raise SystemExit(mock_curl(sys.argv[2:]))
        except Exception:
            sys.stderr.write('Synthetic curl peer failed; private output omitted\n')
            raise SystemExit(9)
    unittest.main()
