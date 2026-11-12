// Exercise the shipped root HTML and helper module. No network/browser dependency.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {page} = require('./issue10_ui_harness.cjs');
const root = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'tg_selfhost_botapi_migrator.html'), 'utf8');
const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures/issue8-shell-cases.json'), 'utf8'));
const modes = ['official-to-self', 'hook-only', 'self-to-self', 'self-to-official'];

async function exported(input = {}) {
  const p = page({mode: input.mode, hook: input.webhook || '', oldHook: input.sourceUrl || '', fastTimers: true});
  for (const [id, value] of Object.entries({secretMode:'provided', secretToken:fixture.canaries.secret,
    allowedUpdates:'["message"]', maxConnections:'7', ipMode:'pinned', ipAddress:'203.0.113.7',
    certificateMode:'none', ...(input.fields || {})})) p.elements.get(id).value = value;
  p.elements.get('certificateFile').files = [new File(['synthetic private certificate canary'], fixture.canaries.certificate_name)];
  const script = p.plan();
  await p.run('copyCurlPlan()');
  assert.equal(p.clipboard.length, 1);
  assert.equal(p.clipboard[0], script);
  assert.equal(p.calls.length, 0, 'Plan and clipboard must remain offline');
  const separator = '# BEGIN SEPARATE TARGET PROFILE SCRIPT: save the following part as a new file after state/lifecycle acceptance.\n';
  return {script, clipboard:p.clipboard[0], target:script.includes(separator) ? script.split(separator)[1] : script};
}

async function selfTest() {
  assert.match(html, /id="botToken" type="password"[^>]*autocomplete="off"[^>]*spellcheck="false"/);
  let checks = 0;
  for (const c of fixture.cases) {
    for (const mode of modes) {
      for (const inherited of [false, true]) {
        const result = await exported({mode, webhook: inherited ? '' : c.value, sourceUrl: inherited ? c.value : ''});
        for (const privateValue of [fixture.canaries.token, fixture.canaries.secret, fixture.canaries.certificate_name])
          assert(!result.script.includes(privateValue), 'Private browser values must not be exported');
        if (c.value) assert(!result.script.includes(c.value), 'Webhook must not be exported');
        assert(result.target.startsWith('#!/usr/bin/env bash\n'));
        assert.match(result.target, /Bash 4\+/);
        if (mode.startsWith('self-to-')) assert(result.script.indexOf('exit 2') < result.script.indexOf(separatorLabel()));
        checks++;
      }
    }
    for (const inherited of [false, true]) {
      const p = page({hook:inherited ? '' : c.value, oldHook:inherited ? c.value : '', fastTimers:true});
      assert.equal(p.run(`hookUrlValid(${JSON.stringify(c.value)}, false)`), c.valid_url, c.id);
      // Direct assignment bypasses browser sanitization of multiline input values.
      await p.run('executeInBrowser()');
      const mutation = p.calls.find(call => call.method === 'setWebhook');
      if (!c.valid_url) {
        assert(!p.calls.some(call => ['setWebhook','deleteWebhook','logOut'].includes(call.method)), c.id);
        if (!inherited) assert.equal(p.calls.length, 0, c.id + ': invalid form URL must stop before requests');
      } else if (c.value) {
        assert(mutation, c.id + ': accepted browser input must reach setWebhook');
        assert.equal(new URLSearchParams(mutation.request.body).get('url'), c.value);
      }
    }
  }
  const p = page();
  for (const mode of ['bad\n>marker', 'target-stage', '', null]) {
    assert.throws(() => p.run(`buildCommands({mode:${JSON.stringify(mode)}})`));
  }
  assert(!p.run(`manualPlan({mode:'self-to-self',oldApi:'\\n>marker',newApi:'\\n>marker'}).join('\\n')`).includes('>marker'));
  const {boot} = await import('../assets/js/migration-client.mjs');
  let requests = 0;
  const dependencies = {storage:{getItem:()=>null,setItem(){}}, fetcher:async()=>{requests++;throw Error('Unexpected fetch');}};
  assert.equal(await boot({getElementById:()=>null}, {protocol:'file:',hostname:''}, dependencies), undefined);
  const helper = fs.readFileSync(path.join(__dirname, 'migration_executor.html'), 'utf8');
  assert.match(helper, /id="token"[^>]*type="password"|type="password"[^>]*id="token"/);
  const elements = new Map([...helper.matchAll(/\bid="([^"]+)"/g)].map(([,id]) => [id,{events:{},addEventListener(n,f){this.events[n]=f;}}]));
  await boot({getElementById:id=>elements.get(id)}, {protocol:'https:',hostname:'example.invalid'}, dependencies);
  assert.equal(requests, 0);
  assert.equal(elements.get('session').hidden, true);
  assert.equal(typeof elements.get('export').events.click, 'function');
  console.log(`issue8 checks passed: ${checks} export/clipboard cases, root/helper bootstrap and URL refusals`);
}
function separatorLabel() { return '# BEGIN SEPARATE TARGET PROFILE SCRIPT'; }
async function main() {
  let data = '';
  if (process.argv[2] === '--export' || process.argv[2] === '--quote') for await (const chunk of process.stdin) data += chunk;
  if (process.argv[2] === '--export') process.stdout.write(JSON.stringify(await exported(JSON.parse(data))));
  else if (process.argv[2] === '--quote') {
    const p = page();
    process.stdout.write(JSON.stringify(JSON.parse(data).map(value => p.run(`shellQuote(${JSON.stringify(value)})`))));
  } else await selfTest();
}
if (require.main === module) main().catch(() => { console.error('issue8 harness failed; private output omitted'); process.exitCode = 1; });
module.exports = {exported};
