"""Offline acceptance tests for the actual browser-generated Bash plan."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOKEN = '123:abcdefghijklmnopqrstuv'
NODE, BASH = shutil.which('node'), shutil.which('bash')
HARNESS = r'''
const fs = require('fs'), vm = require('vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const html = fs.readFileSync(process.argv[1], 'utf8');
const nodes = {}, listeners = {};
function element(id) {
  if (!nodes[id]) { let value = ''; nodes[id] = {
    get value(){return value}, set value(v){value=String(v).replace(/[\r\n]/g,'')},
    checked:false, textContent:'', dataset:{}, style:{}, parentElement:{style:{}},
    classList:{toggle(){}}, appendChild(){},
    addEventListener(type, f){(listeners[id+type] ||= []).push(f)}
  }; }
  return nodes[id];
}
const context = {URL, console, document:{getElementById:element, querySelectorAll:()=>[], createElement:()=>element('entry')},
  navigator:{clipboard:{writeText:async value=>{context.copied=value}}},
  fetch:()=>{throw Error('network forbidden')}};
vm.createContext(context);
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], context);
context.input=input;
if ('literal' in input) {
  try {context.result=vm.runInContext('bashLiteral(input.literal)',context)} catch(e){context.error=e.message}
  process.stdout.write(JSON.stringify({result:context.result,error:context.error}));
} else {
  vm.runInContext(`state.mode=input.mode; els.oldApi.value=input.old; els.newApi.value=input.new;
    els.webhookUrl.value=input.hook; els.botToken.value=input.token; els.dropPending.checked=input.drop;
    state.currentWebhookFromCheck=input.api;`,context);
  if (input.auto) vm.runInContext('els.webhookUrl.value=input.api; state.webhookFromApiInField=true',context);
  async function run() {
    vm.runInContext('buildPlan()',context);
    if (input.fetchApi || input.apiChecks) {
      let apiIndex = 0;
      context.fetch = async (url, options={}) => {
        if (url.endsWith('/getMe')) return {ok:true,status:200,text:async()=>JSON.stringify({ok:true,result:{id:1}})};
        if (url.endsWith('/getWebhookInfo')) return {ok:true,status:200,text:async()=>JSON.stringify({ok:true,result:{url:input.apiChecks ? input.apiChecks[apiIndex++] : input.api}})};
        if (options.method === 'HEAD') return {ok:true,status:200};
        throw Error('unexpected fetch');
      };
      for (const [index] of (input.apiChecks || [input.api]).entries()) {
        await vm.runInContext('checkCurrentState()',context);
        if (index === 0 && input.editAfterFirst !== undefined) {
          element('webhookUrl').value=input.editAfterFirst; for(const f of listeners.webhookUrlinput) f();
        }
      }
    }
    if (input.edit !== undefined) {element('webhookUrl').value=input.edit; for(const f of listeners.webhookUrlinput) f()}
    if (input.badAfter) element('oldApi').value='invalid';
    await context.copyCurlPlan();
    process.stdout.write(JSON.stringify({plan:element('curlPlan').textContent, copied:context.copied,
      field:element('webhookUrl').value, exported:vm.runInContext('exportConfig().webhook',context)}));
  }
  run().catch(e=>{console.error(e);process.exit(1)});
}
'''


class MigratorPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not NODE or not BASH or os.name != 'posix':
            if os.environ.get('MIGRATOR_SECURITY_REQUIRED') == '1':
                raise RuntimeError('Node, Bash and POSIX PTY required')
            raise unittest.SkipTest('Run security tests in Linux/WSL with Node and Bash')
        import pty  # noqa: F401

    def render(self, **kwargs):
        data = dict(mode='self-to-self', old='https://old.invalid/', new='https://new.invalid/',
                    hook='', api='', token='123:browser_secret_abcdefghijk', drop=False)
        data.update(kwargs)
        result = subprocess.run([NODE, '-e', HARNESS, str(ROOT / 'tg_selfhost_botapi_migrator.html')],
                                input=json.dumps(data).encode(), capture_output=True, check=True, timeout=10)
        return json.loads(result.stdout)

    def execute(self, plan, token=TOKEN, options=()):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            script = folder / 'plan.sh'
            script.write_bytes(plan.encode())
            subprocess.run([BASH, '-n', str(script)], check=True, capture_output=True)
            mock = folder / 'curl'
            mock.write_text('#!/usr/bin/python3\nimport json,os,sys\nwith open(os.environ["CAPTURE"],"a") as f: f.write(json.dumps(sys.argv[1:])+"\\n")\n')
            mock.chmod(0o755)
            env = {'PATH': tmp + ':/usr/bin:/bin', 'CAPTURE': str(folder / 'calls')}
            if token is not None:
                env['BOT_TOKEN'] = token
            result = subprocess.run([BASH, *options, str(script)], cwd=tmp, env=env, capture_output=True,
                                    start_new_session=True, timeout=10)
            calls = [json.loads(line) for line in (folder / 'calls').read_text().splitlines()] if (folder / 'calls').exists() else []
            return result, calls, (folder / 'marker').exists()

    def test_modes_and_exact_argv(self):
        hook = "https://hook.invalid/$(touch marker)`touch marker`'\"\\; &|<>!*?[]{}ю"
        for mode in ('official-to-self', 'self-to-self', 'self-to-official', 'hook-only'):
            for drop in (False, True):
                for source in ('form', 'api', 'none'):
                    with self.subTest(mode=mode, drop=drop, source=source):
                        plan = self.render(mode=mode, drop=drop, hook=hook if source == 'form' else '',
                                           api=hook if source == 'api' else '')
                        self.assertEqual(plan['plan'], plan['copied'])
                        self.assertNotIn('browser_secret', plan['plan'])
                        result, actual, marker = self.execute(plan['plan'])
                        self.assertEqual((result.returncode, result.stdout, result.stderr, marker), (0, b'', b'', False))
                        old = 'https://api.telegram.org' if mode == 'official-to-self' else 'https://old.invalid'
                        new = 'https://api.telegram.org' if mode == 'self-to-official' else 'https://new.invalid'
                        drop_arg = 'drop_pending_updates=' + str(drop).lower()
                        def call(base, method, *data):
                            argv = ['--disable', '--globoff']
                            if method in ('deleteWebhook', 'logOut', 'close', 'setWebhook'):
                                argv += ['-X', 'POST']
                            argv += ['--url', base + '/bot' + TOKEN + '/' + method]
                            for item in data:
                                argv += ['--data-urlencode', item]
                            return argv
                        chosen = hook if source != 'none' else ''
                        if mode == 'hook-only':
                            expected = [call(old, 'getWebhookInfo'), call(old, 'setWebhook', 'url='+chosen, drop_arg) if chosen else call(old, 'deleteWebhook', drop_arg), call(old, 'getWebhookInfo')]
                        else:
                            expected = [call(old, 'getMe'), call(old, 'getWebhookInfo'), call(old, 'deleteWebhook', drop_arg), call(old, 'logOut' if mode == 'official-to-self' else 'close'), call(new, 'getMe')]
                            if chosen:
                                expected.append(call(new, 'setWebhook', 'url='+chosen, drop_arg))
                            expected.append(call(new, 'getWebhookInfo'))
                        self.assertEqual(actual, expected)

    def test_repeated_api_checks_keep_field_export_and_action_in_sync(self):
        first = 'https://a.invalid/hook'
        for second in ('https://b.invalid/hook', ''):
            with self.subTest(second=second):
                rendered = self.render(mode='hook-only', apiChecks=[first, second])
                self.assertEqual(rendered['field'], second)
                self.assertEqual(rendered['exported'], rendered['field'])
                result, calls, _ = self.execute(rendered['plan'])
                self.assertEqual(result.returncode, 0)
                self.assertTrue(calls[1][calls[1].index('--url') + 1].endswith(
                    '/setWebhook' if rendered['field'] else '/deleteWebhook'))
                if rendered['field']:
                    self.assertIn('url=' + rendered['field'], calls[1])
        edited = 'https://edited.invalid/hook'
        rendered = self.render(mode='hook-only', apiChecks=[first, 'https://b.invalid/hook'], editAfterFirst=edited)
        self.assertEqual((rendered['field'], rendered['exported']), (edited, edited))
        result, calls, _ = self.execute(rendered['plan'])
        self.assertEqual(result.returncode, 0)
        self.assertIn('url=' + edited, calls[1])

    def test_literal_raw_api_and_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([BASH, '-c', 'touch marker'], cwd=tmp, check=True)
            self.assertTrue((Path(tmp) / 'marker').exists())
            (Path(tmp) / 'marker').unlink()
            for value in ('', ' \r\n\n ', "'\"\\", '$(touch marker)`touch marker` ${HOME}; & | < > ! * ? [ ] { } ю'):
                quoted = self.render(literal=value)['result']
                p = subprocess.run([BASH, '-c', 'printf %s ' + quoted], cwd=tmp, capture_output=True, check=True)
                self.assertEqual(p.stdout, value.encode())
                self.assertFalse((Path(tmp) / 'marker').exists())
        self.assertIn('NUL', self.render(literal='x\0y')['error'])
        raw = 'https://hook.invalid/a\r\nb'
        result, calls, _ = self.execute(self.render(auto=True, api=raw)['plan'])
        self.assertEqual(result.returncode, 0)
        self.assertIn('url='+raw, calls[-2])
        result, calls, _ = self.execute(self.render(fetchApi=True, api=raw)['plan'])
        self.assertEqual(result.returncode, 0)
        self.assertIn('url='+raw, calls[-2])
        self.assertIn('edited.invalid', self.render(auto=True, api=raw, edit='https://edited.invalid')['plan'])
        for options in ({'badAfter':True}, {'hook':'http://bad.invalid'}, {'api':'https://x.invalid/\0'}):
            result = self.render(**options)
            self.assertEqual(result['plan'], '')
            self.assertNotIn('copied', result)

    def test_endpoint_fallback_and_token(self):
        html = (ROOT / 'tg_selfhost_botapi_migrator.html').read_text(encoding='utf8')
        self.assertRegex(html, r'<input id="botToken"[^>]*type="password"[^>]*autocomplete="off"[^>]*spellcheck="false"')
        base = "https://old.invalid/$(touch marker)'\";[]{}"
        result, calls, marker = self.execute(self.render(mode='hook-only', old=base)['plan'])
        self.assertEqual((result.returncode, marker), (0, False))
        self.assertEqual(calls[0][-1], base + '/bot' + TOKEN + '/getWebhookInfo')
        _, calls, marker = self.execute(self.render(new=base)['plan'])
        self.assertFalse(marker)
        self.assertEqual(calls[-1][-1], base + '/bot' + TOKEN + '/getWebhookInfo')
        for new, expected in (('https://fallback.invalid/', 'https://fallback.invalid'), ('', 'https://api.telegram.org')):
            _, calls, _ = self.execute(self.render(mode='hook-only', old='', new=new)['plan'])
            self.assertEqual(calls[0][-1], expected + '/bot' + TOKEN + '/getWebhookInfo')
        plan = self.render(mode='hook-only')['plan']
        self.assertEqual(plan, self.render(mode='hook-only', token='')['plan'])
        for token in (None, '', 'invalid', '$(touch marker)'):
            result, calls, marker = self.execute(plan, token)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((calls, marker), ([], False))
        for option in ('-x', '-v'):
            result, calls, _ = self.execute(plan, options=(option,))
            self.assertEqual((result.returncode, len(calls)), (0, 3))
            self.assertNotIn(TOKEN.encode(), result.stdout + result.stderr)

    def test_hidden_tty(self):
        import pty
        import select
        import termios
        import time
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / 'plan').write_bytes(self.render(mode='hook-only')['plan'].encode())
            mock = folder / 'curl'
            mock.write_text('#!/bin/sh\nprintf x >> "$CAPTURE"\n')
            mock.chmod(0o755)
            for supplied, success in ((TOKEN.encode()+b'\n', True), (b'\x04', False), (b'\n', False), (b'$(touch marker)\n', False)):
                capture = folder / 'calls'
                capture.unlink(missing_ok=True)
                pid, fd = pty.fork()
                if pid == 0:
                    os.chdir(tmp)
                    os.execve(BASH, [BASH, str(folder / 'plan')], {'PATH':tmp+':/usr/bin:/bin', 'CAPTURE':str(capture)})
                output = b''
                try:
                    while b'Bot token: ' not in output:
                        self.assertTrue(select.select([fd], [], [], 10)[0])
                        output += os.read(fd, 4096)
                    deadline = time.monotonic() + 10
                    while termios.tcgetattr(fd)[3] & termios.ECHO:
                        if time.monotonic() > deadline:
                            self.fail('terminal echo was not disabled')
                        time.sleep(0.01)
                    os.write(fd, supplied)
                    while select.select([fd], [], [], 10)[0]:
                        try:
                            chunk = os.read(fd, 4096)
                        except OSError:
                            break
                        if not chunk:
                            break
                        output += chunk
                    _, status = os.waitpid(pid, 0)
                    self.assertEqual(os.waitstatus_to_exitcode(status) == 0, success)
                    if supplied.strip():
                        self.assertNotIn(supplied.strip(), output)
                    self.assertEqual(capture.read_text() if capture.exists() else '', 'xxx' if success else '')
                    self.assertFalse((folder / 'marker').exists())
                finally:
                    os.close(fd)


if __name__ == '__main__':
    unittest.main()
