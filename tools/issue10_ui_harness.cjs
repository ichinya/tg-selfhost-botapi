// Executes the shipped inline script. No browser package or external network.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(path.join(__dirname, '..', 'tg_selfhost_botapi_migrator.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const token = '123:synthetic_token_for_tests_only';

function page(options = {}) {
  const calls = [], prompts = [], clipboard = [], elements = new Map();
  function element() {
    return {value:'', checked:false, disabled:false, style:{}, dataset:{}, textContent:'', children:[],
      events:{}, classList:{toggle() {}},
      addEventListener(name, callback) { this.events[name] = callback; },
      appendChild(child) { this.children.push(child); }};
  }
  for (const [,id] of html.matchAll(/\bid="([^"]+)"/g)) elements.set(id, element());
  const modes = ['official-to-self','self-to-self','self-to-official','hook-only'].map(mode =>
    Object.assign(element(), {dataset:{mode}}));
  let targetHook = options.targetHook || '', sourceHook = options.oldHook || '';
  const context = vm.createContext({URL, URLSearchParams, AbortController, setTimeout, clearTimeout,
    document:{getElementById(id) { assert(elements.has(id), `Missing DOM id: ${id}`); return elements.get(id); },
      createElement:element, querySelectorAll:() => modes},
    navigator:{clipboard:{async writeText(text) { clipboard.push(text); }}},
    confirm(message) { prompts.push(message); return options.consent !== false; },
    async fetch(address, request = {}) {
      const url = new URL(address);
      const role = url.origin === 'https://api.telegram.org' || url.hostname === 'source.test' ? 'source'
        : url.hostname === 'target.test' ? 'target' : 'sink';
      assert.notEqual(role, 'sink', 'No fetch may reach a webhook or unknown host');
      assert.equal(request.redirect, 'error');
      assert(request.signal, 'Every fetch has a deadline signal');
      const method = url.pathname.includes('/bot') ? url.pathname.split('/').at(-1) : 'probe';
      const call = {role, method, url:address, request}; calls.push(call);
      if (method !== 'probe') assert(url.pathname.includes('/bot' + token + '/'));
      if (method === 'probe') assert(!address.includes(token));
      const selector = role + ':' + method;
      const fail = selector === options.fail;
      if (fail && options.failure === 'lost') throw new Error('Simulated lost response');
      if (fail && options.failure === 'timeout') {
        return new Promise((resolve, reject) => request.signal.addEventListener('abort', () => reject(new Error('Aborted'))));
      }
      let status = method === 'probe' ? 404 : 200;
      let json;
      if (method === 'probe') json = {ok:false,error_code:404,description:'Not Found'};
      else {
        let result = true;
        if (method === 'getMe') result = {id:123,first_name:'Synthetic'};
        if (method === 'getWebhookInfo') result = {url:role === 'source' ? sourceHook : targetHook};
        if (method === 'setWebhook' && !fail) {
          assert.equal(request.method, 'POST');
          assert.equal(request.headers['Content-Type'], 'application/x-www-form-urlencoded');
          if (role === 'target') targetHook = new URLSearchParams(request.body).get('url');
          else sourceHook = new URLSearchParams(request.body).get('url');
        }
        if (method === 'deleteWebhook' && !fail) {
          if (role === 'target') targetHook = ''; else sourceHook = '';
        }
        json = {ok:true,result};
      }
      if (fail) {
        switch (options.failure) {
          case 'http': status = 500; break;
          case 'redirect': status = 302; break;
          case 'false-result': json = {ok:true,result:false}; break;
          case 'malformed': return {ok:true,status:200,text:async () => '{'};
          case 'wrong-url': json = {ok:true,result:{url:null}}; break;
          default: json = {ok:false,error_code:429,parameters:{retry_after:600}};
        }
      }
      if (options.mismatch && role === 'target' && method === 'getWebhookInfo') json.result.url = 'https://other.test/';
      return {ok:status >= 200 && status < 300, status, text:async () => JSON.stringify(json)};
    }});
  vm.runInContext(script, context, {timeout:1000});
  const run = code => vm.runInContext(code, context, {timeout:1000});
  run(`state.mode=${JSON.stringify(options.mode || 'official-to-self')}; applyMode();`);
  elements.get('botToken').value = token;
  if (options.mode && options.mode !== 'official-to-self') elements.get('oldApi').value = 'https://source.test/prefix';
  elements.get('newApi').value = 'http://target.test/prefix';
  elements.get('webhookUrl').value = options.hook || '';
  return {calls, prompts, clipboard, elements, run,
    logs:() => elements.get('logBox').children.map(el => el.textContent).join('\n'),
    plan:() => { run('buildPlan()'); return elements.get('curlPlan').textContent; }};
}

async function tests() {
  let count = 0;
  let p = page({consent:false});
  await p.run('checkCurrentState()'); assert.equal(p.calls.length, 0); count++;
  p = page({consent:false}); await p.run('executeInBrowser()');
  assert.deepEqual(p.calls.map(c => c.method), ['probe']); count++;
  p = page();
  p.run('runLocalChecks(); buildPlan()'); assert.equal(p.calls.length, 0); count++;
  await p.run('checkCurrentState()');
  assert(p.calls.every(c => c.role === 'source'));
  assert.equal(p.prompts.length, 1); count++;
  p = page({fail:'target:probe',failure:'timeout'});
  await p.run('executeInBrowser()');
  assert.deepEqual(p.calls.map(c => c.method), ['probe']);
  assert(!p.logs().includes('Конфигурация проверена')); count++;
  for (const mode of ['self-to-self','self-to-official']) {
    p = page({mode});
    await p.run('executeInBrowser()'); assert.equal(p.calls.length, 0);
    assert(p.elements.get('btnExecute').disabled);
    const plan = p.plan(); assert(!plan.includes('curl '));
    if (mode === 'self-to-self') {
      assert(plan.indexOf('close') < plan.indexOf('СТОП — внешний перенос'));
      assert(plan.indexOf('СТОП — внешний перенос') < plan.indexOf('первый getMe'));
    } else { assert(plan.indexOf('source') < plan.indexOf('source logOut')); assert(!plan.includes('close')); }
    count++;
  }
  for (const fail of ['target:probe','source:getMe','source:getWebhookInfo','source:deleteWebhook','source:logOut','target:getMe','target:setWebhook']) {
    for (const failure of ['http','redirect','api','false-result','malformed','lost']) {
      p = page({fail,failure,hook:'https://sink.test/webhook'});
      await p.run('executeInBrowser()');
      assert(!p.logs().includes('Конфигурация проверена'), `${fail}/${failure}`);
      if (fail.startsWith('source:')) assert(!p.calls.some(c => c.role === 'target' && c.method !== 'probe'));
      if (fail === 'source:deleteWebhook') assert(!p.calls.some(c => c.method === 'logOut'));
      if (fail === 'target:probe') assert(!p.calls.some(c => c.role === 'source'));
      if (fail === 'source:logOut' && failure === 'lost') {
        assert(p.logs().includes('UNKNOWN'));
        const previous = p.calls.length; await p.run('executeInBrowser()'); assert.equal(p.calls.length, previous);
      }
      count++;
    }
  }
  p = page({hook:'https://sink.test/webhook'}); await p.run('executeInBrowser()');
  assert(p.logs().includes('Конфигурация проверена'));
  const logout = p.calls.findIndex(c => c.method === 'logOut');
  const login = p.calls.findIndex(c => c.role === 'target' && c.method === 'getMe');
  assert(logout >= 0 && login > logout);
  assert.equal(new URLSearchParams(p.calls.find(c => c.method === 'setWebhook').request.body).get('url'), 'https://sink.test/webhook'); count++;
  const completedCalls = p.calls.length;
  await p.run('executeInBrowser()'); await p.run('checkCurrentState()');
  assert.equal(p.calls.length, completedCalls, 'Do not reauthorize the old source after success'); count++;
  for (const options of [{fail:'source:logOut',failure:'lost'}, {}]) {
    p = page({...options, hook:'https://sink.test/webhook'});
    await p.run('executeInBrowser()');
    assert(p.elements.get('btnCopyCurl').disabled, 'Copy must be disabled after UNKNOWN or migration');
    assert(!p.elements.get('curlPlan').textContent.includes('curl '), 'Displayed plan must be replaced immediately');
    await p.run('copyCurlPlan()');
    const plan = p.plan();
    assert(!plan.includes('curl '), 'No executable plan may be generated');
    assert.equal(p.clipboard[0], plan);
    assert(!plan.includes(' logOut -X POST'));
    assert(plan.includes('getWebhookInfo'));
    count++;
  }
  for (const hook of ['', 'https://sink.test/webhook']) {
    p = page({mode:'hook-only',hook}); await p.run('executeInBrowser()');
    assert(!p.calls.some(c => ['logOut','close','probe'].includes(c.method)));
    assert(p.logs().includes('Конфигурация проверена')); count++;
  }
  p = page({oldHook:'https://previous.test/path'}); await p.run('checkCurrentState()');
  p.elements.get('newApi').value = 'https://target.test/changed';
  p.elements.get('newApi').events.input();
  assert.equal(p.run('state.currentWebhookFromCheck'), '');
  assert(!p.plan().includes('https://previous.test')); count++;
  for (const options of [{mismatch:true}, {fail:'target:getWebhookInfo',failure:'wrong-url'}]) {
    p = page(options); await p.run('executeInBrowser()'); assert(!p.logs().includes('Конфигурация проверена')); count++;
  }
  p = page({hook:'https://sink.test/$(echo bad)'});
  const plan = p.plan(); assert(!plan.includes(token));
  assert(plan.includes('set -euo pipefail')); assert(plan.includes('UNKNOWN'));
  assert(plan.indexOf(' logOut -X POST') < plan.indexOf("'http://target.test/prefix' getMe")); count++;
  for (const mode of ['official-to-self', 'hook-only']) {
    p = page({mode, hook:'http://sink.test/webhook'});
    await p.run('checkCurrentState()');
    assert.equal(p.calls[0]?.method, 'getMe', `${mode}: HTTP webhook must reach the first request`); count++;
  }
  for (const mode of ['self-to-official', 'hook-only']) {
    p = page({mode, hook:'http://sink.test/webhook'});
    if (mode === 'hook-only') p.elements.get('oldApi').value = 'https://api.telegram.org';
    await p.run('checkCurrentState()'); assert.equal(p.calls.length, 0, `${mode}: cloud requires HTTPS`); count++;
    p.elements.get('webhookUrl').value = 'https://sink.test/webhook';
    await p.run('checkCurrentState()'); assert.equal(p.calls[0]?.method, 'getMe'); count++;
  }
  console.log(`${count} HTML VM/fetch scenarios passed`);
}
module.exports = {page, tests};
if (require.main === module) {
  const watchdog = setTimeout(() => { console.error('HTML harness watchdog expired after 40s'); process.exit(1); }, 40000);
  tests().then(() => clearTimeout(watchdog)).catch(error => { clearTimeout(watchdog); console.error(error); process.exitCode = 1; });
}
