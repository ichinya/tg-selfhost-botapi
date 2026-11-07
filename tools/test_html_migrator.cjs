// #14: same-origin helper replaces the legacy direct-fetch runtime.
const migrationModuleHtml = require('node:fs').readFileSync(require('node:path').join(__dirname, '..', 'tg_selfhost_botapi_migrator.html'), 'utf8');
if (migrationModuleHtml.includes('src="assets/js/migration-client.mjs"')) {
  import('./test_migration_ui.mjs').then(() => console.log('helper contract checks passed')).catch(() => { process.exitCode = 1; });
} else {
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const {test} = require('node:test');
const mock = require('./html_migrator_mock.js');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'tg_selfhost_botapi_migrator.html'), 'utf8');
function extract(value) {
  const scripts = [...value.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)];
  assert.equal(scripts.length, 1, 'The production HTML must have exactly one script');
  assert(!/\bsrc\s*=/i.test(scripts[0][1]), 'External production scripts are forbidden');
  return scripts[0][2];
}
const script = extract(html);
const TOKEN = '123456:AAAAAAAAAAAAAAAAAAAAAAAA';
const OTHER = '456789:BBBBBBBBBBBBBBBBBBBBBBBB';
const SOURCE = 'https://source.example.invalid';
const TARGET = 'https://target.example.invalid';
const OFFICIAL = 'https://api.telegram.org';
const HOOK = 'https://hook.example.invalid/path?version=1';
const me = id => ({ok:true, result:{id, is_bot:true}});
const hook = url => ({ok:true, result:{url}});
const yes = {ok:true, result:true};
const bad = (code, extra = {}) => ({ok:false, error_code:code, ...extra});
const sourceReads = (url = HOOK, id = 123456) => [me(id), hook(url)];
const flush = async () => { for (let i = 0; i < 128; i++) await Promise.resolve(); };
function fakeClock() {
  let now = 1700000000000, elapsed = 0, next = 0;
  const timers = new Map();
  class ClockDate extends Date {
    constructor(...args) { super(...(args.length ? args : [now])); }
    static now() { return now; }
  }
  return {Date:ClockDate, timers, performance:{now:()=>elapsed},
    setTimeout(fn, delay) { const id = ++next; timers.set(id,{fn, at:elapsed + delay}); return id; },
    clearTimeout(id) { timers.delete(id); },
    jumpWall(ms) { now += ms; },
    advance(ms) { now += ms; elapsed += ms; for (const [id, timer] of [...timers]) if (timer.at <= elapsed) { timers.delete(id); timer.fn(); } }};
}
function setup(t, replies = [], mode = 'official-to-self') {
  const m = mock.create(replies), elements = {}, clock = fakeClock(), clipboard = [];
  function element(id = '') {
    const listeners = new Map(), children = [];
    let text = '', markup = '';
    const el = {id, value:'', checked:false, disabled:false, readOnly:false, dataset:{}, style:{}, parentElement:{style:{}}, className:'', children,
      get textContent() { return text + children.map(x=>x.textContent).join(''); },
      set textContent(value) { text = String(value); markup = ''; children.length = 0; },
      get innerHTML() { return markup; }, set innerHTML(value) { markup = String(value); text = ''; children.length = 0; },
      addEventListener(type, fn) { if (!listeners.has(type)) listeners.set(type, []); listeners.get(type).push(fn); },
      dispatch(type) { return Promise.all((listeners.get(type) || []).map(fn=>fn({target:el}))); },
      click() { return el.disabled ? Promise.resolve() : el.dispatch('click'); },
      appendChild(child) { children.push(child); },
      classList:{toggle(){}}, scrollTop:0, scrollHeight:0};
    return el;
  }
  for (const match of html.matchAll(/\bid="([^"]+)"/g)) elements[match[1]] = element(match[1]);
  const modes = [...html.matchAll(/<button[^>]*data-mode="([^"]+)"/g)].map(match=>{
    const el = element(); el.dataset.mode = match[1]; return el;
  });
  assert.equal(modes.length,4, 'All mode controls must be actual buttons');
  const document = {getElementById:id=>elements[id] || null, querySelectorAll:selector=>selector === '.mode-btn' ? modes : [], createElement:()=>element()};
  const ctx = vm.createContext({document, URL, AbortController, setTimeout:clock.setTimeout, clearTimeout:clock.clearTimeout,
    Date:clock.Date, performance:clock.performance, fetch:m.fetch, navigator:{clipboard:{writeText:async value=>clipboard.push(value)}}});
  vm.runInContext(script,ctx,{filename:'production-inline.js'});
  const run = code=>vm.runInContext(code,ctx);
  elements.botToken.value = TOKEN;
  elements.oldApi.value = mode === 'official-to-self' ? OFFICIAL : SOURCE;
  elements.newApi.value = TARGET;
  run(`state.mode=${JSON.stringify(mode)}`);
  t.after(()=>assert.deepEqual(m.violations,[], 'Unexpected mocked request must fail the test even if the adapter catches it'));
  return {m,e:elements,modes,ctx,clock,clipboard,run,
    check:()=>run('checkCurrentState()'), apply:()=>run('executeInBrowser()'),
    change:async(id,value,type='input')=>{ if(id==='dropPending') elements[id].checked=value; else elements[id].value=value; await elements[id].dispatch(type); },
    op:()=>run('state.operation'), methods:()=>m.calls.map(x=>x.method)};
}
async function completed(t,replies,outcome,mode,configure) {
  const h=setup(t,replies,mode); if(configure) await configure(h);
  await h.check(); await h.apply();
  assert.equal(h.e.summaryBox.dataset.outcome,outcome);
  assert.match(h.e.summaryBox.textContent,new RegExp(outcome));
  assert.equal(h.e.summaryBox.innerHTML,'', 'Dynamic summaries use textContent');
  assert.equal(h.run('state.active'),null);
  assert.equal(h.e.btnExecute.disabled,false);
  return h;
}
const standardMethods = ['getMe','getWebhookInfo','deleteWebhook','logOut','getMe','setWebhook','getWebhookInfo'];

test('Harness rejects extra or external script blocks',()=>{
  assert.throws(()=>extract(html+'<script></script>'));
  assert.throws(()=>extract('<script src="remote.js"></script>'));
});
for (const mode of ['official-to-self','self-to-self','self-to-official','hook-only']) {
  test('Happy path and immutable plan: '+mode,async t=>{
    const migration=mode!=='hook-only';
    const replies=[...sourceReads(),...(migration?[yes,yes,me(123456)]:[]),yes,hook(HOOK)];
    const h=await completed(t,replies,'SUCCESS',mode);
    const methods=migration ? [...standardMethods] : ['getMe','getWebhookInfo','setWebhook','getWebhookInfo'];
    if(mode==='self-to-self'||mode==='self-to-official') methods[3]='close';
    assert.deepEqual(h.methods(),methods);
    const source=mode==='official-to-self'?OFFICIAL:SOURCE;
    const target=mode==='self-to-official'?OFFICIAL:mode==='hook-only'?SOURCE:TARGET;
    assert(h.m.calls.slice(0,migration?4:2).every(x=>x.endpoint===source));
    assert(h.m.calls.slice(migration?4:2).every(x=>x.endpoint===target));
    assert.equal(h.m.pending.length,0);
    assert(h.run('Object.isFrozen(state.operation.plan) && Object.isFrozen(state.operation.plan.order) && state.operation.plan.order.every(Object.isFrozen)'));
    const op=h.op();
    assert.equal(op.actual.url,HOOK); assert.equal(op.actual.operationId,op.id); assert.equal(op.actual.botId,123456);
    assert.equal(op.actual.endpoint,mode==='self-to-official'?OFFICIAL:mode==='hook-only'?SOURCE:TARGET);
    assert(op.milestones.includes('verified'));
    assert(!JSON.stringify(op).includes(TOKEN));
    const count=h.m.calls.length;
    await h.apply(); await h.check(); await h.run('copyCurlPlan()');
    assert.equal(h.m.calls.length,count); assert.equal(h.clipboard.length,0);
    assert.match(h.e.summaryBox.textContent,/SUCCESS/);
  });
}
for(const stage of ['getMe','getWebhookInfo']) {
  test('Source '+stage+' refusal stops before any mutation',async t=>{
    const h=setup(t,stage==='getMe'?[bad(401)]:[me(123456),bad(400)]);
    await h.check();
    assert.match(h.e.summaryBox.textContent,/ERROR проверки/);
    assert.match(h.e.summaryBox.textContent,/BLOCKED/);
    await h.apply();
    assert.deepEqual(h.methods(),stage==='getMe'?['getMe']:['getMe','getWebhookInfo']);
    assert.equal(h.run('state.snapshot'),null);
    assert.equal(h.run('history.length'),0);
  });
}
for(const method of ['deleteWebhook','logOut','close','getMe','setWebhook']) {
  test('Known refusal stops dependants: '+method,async t=>{
    const mode=method==='close'?'self-to-self':'official-to-self';
    const prefix=[...sourceReads()];
    if(method!=='deleteWebhook') prefix.push(yes);
    if(method==='getMe'||method==='setWebhook') prefix.push(yes);
    if(method==='setWebhook') prefix.push(me(123456));
    const h=await completed(t,[...prefix,bad(400)],method==='deleteWebhook'?'ERROR':'PARTIAL',mode);
    assert.equal(h.m.calls.at(-1).method,method);
    assert(h.op().steps.some(x=>x.status==='BLOCKED'));
    assert.equal(h.op().actual,null);
    assert.match(h.e.summaryBox.textContent,/Подтверждённый webhook: не подтверждено/);
    assert(!h.op().steps.some(x=>x.phase==='old_detached'&&x.status==='CONFIRMED') || method==='getMe'||method==='setWebhook');
  });
}
for(const lost of ['source_webhook_deleted','old_detached','target_identified','target_configured']) {
  test('Remote effect + lost response: '+lost,async t=>{
    let effect=false;
    const prefix=[...sourceReads()];
    if(lost!=='source_webhook_deleted') prefix.push(yes);
    if(['target_identified','target_configured'].includes(lost)) prefix.push(yes);
    if(lost==='target_configured') prefix.push(me(123456));
    const lostReply={effect:()=>{effect=true;},error:new Error('synthetic response loss '+TOKEN)};
    const h=await completed(t,[...prefix,lostReply],'UNKNOWN');
    assert(effect); assert.equal(h.m.effects.length,1);
    assert.equal(h.op().steps.find(x=>x.phase===lost).status,'UNKNOWN');
    const count=h.m.calls.length;
    await h.change('newApi','https://changed.example.invalid');
    await h.change('botToken',OTHER); await h.change('botToken',TOKEN);
    await h.apply(); await h.check(); await h.run('copyCurlPlan()');
    assert.equal(h.m.calls.length,count); assert.equal(h.clipboard.length,0);
    assert(!h.e.summaryBox.textContent.includes(TOKEN));
    assert(!h.e.logBox.textContent.includes(TOKEN));
    assert(!h.e.curlPlan.textContent.includes(TOKEN));
  });
}
test('Remote close effect loss is UNKNOWN and excludes target',async t=>{
  const h=await completed(t,[...sourceReads(),yes,{effect:()=>{},error:new Error('lost')}],'UNKNOWN','self-to-self');
  assert.deepEqual(h.methods(),['getMe','getWebhookInfo','deleteWebhook','close']);
});
test('Remote hook-only delete loss is UNKNOWN',async t=>{
  const h=await completed(t,[...sourceReads(''),{effect:()=>{},error:new Error('lost')}],'UNKNOWN','hook-only');
  assert.deepEqual(h.methods(),['getMe','getWebhookInfo','deleteWebhook']);
});
test('Remote hook-only set loss is UNKNOWN',async t=>{
  const h=await completed(t,[...sourceReads(),{effect:()=>{},error:new Error('lost')}],'UNKNOWN','hook-only');
  assert.deepEqual(h.methods(),['getMe','getWebhookInfo','setWebhook']);
});
test('Combined close 429 / staged setWebhook 400 never reaches target',async t=>{
  const h=await completed(t,[...sourceReads(),yes,bad(429,{parameters:{retry_after:321}}),bad(400)],'PARTIAL','self-to-self');
  assert.deepEqual(h.methods(),['getMe','getWebhookInfo','deleteWebhook','close']);
  assert.equal(h.m.pending.length,1);
  assert.equal(h.op().steps.find(x=>x.method==='close').status,'WAITING');
  assert.deepEqual(Array.from(h.op().milestones),['source_webhook_deleted']);
  assert.match(h.e.cooldownBox.textContent,/321 сек/);
  h.clock.advance(321000); await flush();
  await h.apply(); await h.check();
  assert.equal(h.m.calls.length,4);
});
for(const retry of [undefined,-1,1.5,'30',Number.MAX_SAFE_INTEGER+1,Number.MAX_SAFE_INTEGER,9_000_000_000_000]) {
  test('Invalid retry_after is not a countdown: '+String(retry),async t=>{
    const h=setup(t,[bad(429,retry===undefined?{}:{parameters:{retry_after:retry}})]);
    await h.check();
    assert.equal(h.run('remainingCooldown(botBinding(currentConfig().token))'),0);
    assert.equal(h.clock.timers.size,0);
    assert.equal(h.run('state.guards.size'),0);
  });
}
for(const retry of [0,30]) {
  test('Valid cooldown '+retry+' uses elapsed time and fresh check',async t=>{
    const h=setup(t,[bad(429,{parameters:{retry_after:retry}}),...sourceReads()]);
    await h.check();
    assert(h.run("state.guards.has('123456')"));
    if(retry) {
      h.clock.jumpWall(24*3600*1000); await h.check(); assert.equal(h.m.calls.length,1);
      await h.change('newApi','https://elsewhere.example.invalid'); await h.change('dropPending',true);
      await h.change('botToken',OTHER); await h.change('botToken',TOKEN);
      await h.check(); assert.equal(h.m.calls.length,1);
      h.clock.advance(29999); await h.check(); assert.equal(h.m.calls.length,1);
      h.clock.advance(1); await flush(); assert.equal(h.m.calls.length,1);
    }
    await h.check(); assert.equal(h.m.calls.length,3); assert(h.run('!!state.snapshot'));
  });
}
for(const payload of ['<html>gateway</html>',{ok:true,result:false},{ok:1,result:true},{ok:false,error_code:'400'},null,[]]) {
  test('Malformed mutation is UNKNOWN: '+JSON.stringify(payload),async t=>{
    const h=await completed(t,[...sourceReads(),payload],'UNKNOWN');
    assert.equal(h.methods().length,3); assert.equal(h.op().effects.length,0);
  });
}
test('HTTP error with no API JSON is UNKNOWN',async t=>{
  const h=await completed(t,[...sourceReads(),{status:502,body:'gateway'}],'UNKNOWN');
  assert.equal(h.op().steps.find(x=>x.phase==='source_webhook_deleted').receipt.status,502);
});
test('HTTP 500 with ok=true is not a success receipt',async t=>{
  const h=await completed(t,[...sourceReads(),{status:500,body:yes}],'UNKNOWN');
  assert.equal(h.op().effects.length,0);
});
for(const value of [{id:123456,is_bot:false},{id:0,is_bot:true},{id:1.2,is_bot:true},{}]) {
  test('Malformed identity blocks source: '+JSON.stringify(value),async t=>{
    const h=setup(t,[{ok:true,result:value}]); await h.check(); await h.apply();
    assert.equal(h.m.calls.length,1); assert.equal(h.run('state.snapshot'),null);
  });
}
for(const value of [{},{url:null},{url:0}]) {
  test('Missing/non-string source URL does not mean empty: '+JSON.stringify(value),async t=>{
    const h=setup(t,[me(123456),{ok:true,result:value}]); await h.check(); await h.apply();
    assert.equal(h.m.calls.length,2); assert.equal(h.run('state.snapshot'),null);
  });
}
for(const mode of ['official-to-self','hook-only']) {
  test('Preserve-empty explicitly deletes on target and verifies absence: '+mode,async t=>{
    const migration=mode!=='hook-only';
    const h=await completed(t,[...sourceReads(''),...(migration?[yes,yes,me(123456)]:[]),yes,hook('')],'SUCCESS',mode,
      x=>{x.e.dropPending.checked=true;});
    const actions=h.m.calls.filter(x=>x.httpMethod==='POST');
    assert.equal(actions.at(-1).method,'deleteWebhook');
    assert.equal(actions.at(-1).body,'drop_pending_updates=true');
    assert.equal(actions.filter(x=>x.body.includes('drop_pending_updates=true')).length,1);
    if(migration) assert.equal(actions[0].body,'drop_pending_updates=false');
    assert.equal(h.op().actual.url,'');
    assert.match(h.e.summaryBox.textContent,/Подтверждённый webhook: \(отсутствует\)/);
    assert.match(h.e.summaryBox.textContent,/polling-клиента не подтверждены/);
  });
}
for(const actual of ['https://hook.example.invalid/path?version=2','https://hook.example.invalid/path/?version=1','https://hook.example.invalid/other?version=1','']) {
  test('Exact final URL mismatch: '+actual,async t=>{
    const h=await completed(t,[...sourceReads(),yes,yes,me(123456),yes,hook(actual)],'PARTIAL');
    assert.equal(h.op().actual.url,actual); assert.equal(h.op().reason,'WEBHOOK_URL_MISMATCH');
    assert.match(h.e.summaryBox.textContent,/WEBHOOK_URL_MISMATCH/);
  });
}
for(const reply of [new Error('lost'),{ok:true,result:{}},bad(400),'<html>bad</html>']) {
  test('Untrustworthy started final read is UNKNOWN: '+String(reply),async t=>{
    const h=await completed(t,[...sourceReads(),yes,yes,me(123456),yes,reply],'UNKNOWN');
    assert.equal(h.op().actual,null);
    assert.match(h.e.summaryBox.textContent,/Подтверждённый webhook: не подтверждено/);
  });
}
test('Target ID mismatch never configures target',async t=>{
  const h=await completed(t,[...sourceReads(),yes,yes,me(999)],'PARTIAL');
  assert.equal(h.op().reason,'BOT_ID_MISMATCH'); assert.equal(h.m.calls.at(-1).method,'getMe');
  assert(!h.op().milestones.includes('target_identified'));
});
for(const hang of ['fetch','body']) {
  for(const phase of ['source','mutation','target','final']) {
    test('Deadline covers '+hang+' during '+phase,async t=>{
      const blocked=mock.deferred(), prefix=[];
      if(phase!=='source') prefix.push(...sourceReads());
      if(phase==='target'||phase==='final') prefix.push(yes,yes);
      if(phase==='final') prefix.push(me(123456),yes);
      const h=setup(t,[...prefix,hang==='fetch'?{wait:blocked}:{bodyWait:blocked}]);
      const operation=phase==='source'?h.check():(await h.check(),h.apply());
      await flush(); assert(h.run('state.active'));
      h.clock.advance(29999); await flush(); assert(h.run('state.active'));
      h.clock.advance(1); await operation;
      assert.equal(h.run('state.active'),null); assert.equal(h.e.btnExecute.disabled,false);
      assert.equal(h.clock.timers.size,0);
      assert(h.m.calls.at(-1).signal.aborted);
      if(phase==='source') assert.equal(h.run('state.snapshot'),null);
      else assert.equal(h.op().outcome,'UNKNOWN');
      const count=h.m.calls.length;
      blocked.resolve(hang==='fetch'?mock.response(yes):JSON.stringify(yes)); await flush();
      assert.equal(h.m.calls.length,count);
    });
  }
}
test('One active Check blocks repeated Check and Execute',async t=>{
  const d=mock.deferred(), h=setup(t,[{wait:d},hook(HOOK)]);
  const operation=h.check(); await h.check(); await h.apply();
  assert.equal(h.m.calls.length,1); assert.equal(h.e.btnExecute.disabled,true);
  d.resolve(mock.response(me(123456))); await operation;
  assert.equal(h.m.calls.length,2); assert.equal(h.e.btnExecute.disabled,false);
});
test('Apply locks all fields/modes and uses frozen inputs',async t=>{
  const d=mock.deferred(), h=setup(t,[...sourceReads(),{wait:d},yes,me(123456),yes,hook(HOOK)]);
  h.e.dropPending.checked=true;
  await h.check(); const operation=h.apply(); await flush();
  for(const id of ['botToken','oldApi','newApi','webhookUrl','dropPending','btnCheck','btnExecute','btnCopyCurl']) assert.equal(h.e[id].disabled,true,id);
  assert(h.modes.every(x=>x.disabled));
  await h.apply(); await h.check();
  await h.modes.at(-1).click();
  assert.equal(h.run('state.mode'),'official-to-self');
  h.e.newApi.value='https://changed.example.invalid'; await h.e.newApi.dispatch('input');
  h.e.webhookUrl.value='https://changed.example.invalid/hook'; await h.e.webhookUrl.dispatch('change');
  assert.equal(h.run('state.generation'),0);
  h.run('buildPlan()'); assert(!h.e.curlPlan.textContent.includes('changed.example.invalid'));
  d.resolve(mock.response(yes)); await operation;
  assert.equal(h.op().outcome,'SUCCESS'); assert.equal(h.op().actual.url,HOOK);
  assert.equal(h.m.calls[2].body,'drop_pending_updates=false');
  assert.equal(h.m.calls[5].body,'url='+encodeURIComponent(HOOK)+'&drop_pending_updates=true');
  assert(h.modes.every(x=>!x.disabled));
});
test('Old finally cannot release a newer owner',async t=>{
  const first=mock.deferred(), second=mock.deferred();
  const h=setup(t,[...sourceReads(),{wait:first}]); await h.check();
  const old=h.apply(); await flush();
  h.run("state.active=999; state.activeKind='apply'");
  first.resolve(mock.response(bad(400))); await old;
  assert.equal(h.run('state.active'),999); assert.equal(h.e.btnExecute.disabled,true);
  assert.equal(h.clock.timers.size,0);
});
test('Renderer exception releases controls while preserving guard',async t=>{
  const h=setup(t,[...sourceReads(),new Error('lost')]); await h.check();
  h.run("log=()=>{throw new Error('synthetic render failure')}");
  await assert.rejects(h.apply());
  assert.equal(h.run('state.active'),null); assert.equal(h.e.btnExecute.disabled,false);
  assert.equal(h.run("state.guards.get('123456').outcome"),'UNKNOWN');
});
for(const id of ['botToken','oldApi','newApi','webhookUrl','dropPending']) {
  test('Input/change invalidates snapshot and preview: '+id,async t=>{
    const h=setup(t,sourceReads()); await h.check();
    await h.change(id,id==='dropPending'?true:id==='botToken'?OTHER:'https://changed.example.invalid','change');
    assert.equal(h.run('state.snapshot'),null); assert.match(h.e.curlPlan.textContent,/устарел/);
    await h.apply(); assert.equal(h.m.calls.length,2);
  });
}
test('Mode change invalidates checks',async t=>{
  const h=setup(t,sourceReads()); await h.check(); await h.modes.at(-1).click();
  assert.equal(h.run('state.snapshot'),null); assert.equal(h.run('state.mode'),'hook-only');
});
test('Late A response cannot populate B; failed B cannot use A webhook',async t=>{
  const d=mock.deferred(), h=setup(t,[{wait:d},bad(400)]);
  const a=h.check(); await h.change('botToken',OTHER);
  d.resolve(mock.response(me(123456))); await a;
  assert.equal(h.run('state.snapshot'),null); assert.equal(h.e.webhookUrl.value,'');
  await h.check(); await h.apply();
  assert.deepEqual(h.methods(),['getMe','getMe']); assert.equal(h.run('state.snapshot'),null);
});
test('Completed A never autofills B; explicit URL remains intent',async t=>{
  const h=setup(t,[...sourceReads(),bad(400)]);
  h.e.webhookUrl.value='https://explicit.example.invalid'; await h.check();
  await h.change('botToken',OTHER); await h.check(); await h.apply();
  assert.equal(h.e.webhookUrl.value,'https://explicit.example.invalid');
  assert.equal(h.run('state.currentWebhookFromCheck'),''); assert.equal(h.m.calls.length,3);
});
test('Hook-only ignores stale hidden newApi in check, preview, executor',async t=>{
  const h=setup(t,[...sourceReads(),yes,hook(HOOK)],'hook-only');
  h.e.oldApi.value=''; h.e.newApi.value='https://stale.example.invalid';
  await h.check();
  assert(h.m.calls.every(x=>x.endpoint===OFFICIAL));
  assert(h.e.curlPlan.textContent.includes(OFFICIAL)); assert(!h.e.curlPlan.textContent.includes('stale'));
  await h.run('copyCurlPlan()'); assert.equal(h.clipboard.length,1);
  assert(!h.clipboard[0].includes(TOKEN)); assert(!h.clipboard[0].includes(HOOK));
  await h.apply(); assert(h.m.calls.every(x=>x.endpoint===OFFICIAL));
});
for(const mode of ['official-to-self','self-to-self','self-to-official']) {
  test('Equal normalized source/target rejected before network: '+mode,async t=>{
    const h=setup(t,[],mode);
    if(mode==='official-to-self') h.e.newApi.value=OFFICIAL+'/';
    else if(mode==='self-to-official') h.e.oldApi.value=OFFICIAL+'/';
    else h.e.newApi.value=SOURCE+'/';
    await h.check(); await h.apply(); assert.equal(h.m.calls.length,0);
  });
}
test('Hidden endpoint fields do not enter official-to-self or self-to-official plans',async t=>{
  const h=setup(t,sourceReads(),'self-to-official'); h.e.newApi.value='https://hidden.example.invalid';
  await h.check(); assert.equal(h.run('state.snapshot.plan.target'),OFFICIAL);
  assert(!h.e.curlPlan.textContent.includes('hidden'));
});
test('ERROR without effects permits a fresh check but never repeats without it',async t=>{
  const h=await completed(t,[...sourceReads(),bad(400),...sourceReads()],'ERROR');
  await h.apply(); assert.equal(h.m.calls.length,3);
  await h.check(); assert.equal(h.m.calls.length,5);
});
test('Logged out is an API refusal, not a detach receipt',async t=>{
  const h=setup(t,[bad(401,{description:'Logged out'})]); await h.check(); await h.apply();
  assert.equal(h.m.calls.length,1); assert.equal(h.run('state.snapshot'),null);
});
test('HEAD is separate non-API telemetry and proves no delivery',async t=>{
  const h=setup(t,[]); h.ctx.url=HOOK;
  const result=await h.run('checkWebhookReachability(url)');
  assert.equal(h.m.calls.length,0); assert.equal(h.m.nonApiCalls.length,1);
  assert.match(result.message,/не подтверждены/); assert.equal(h.clock.timers.size,0);
});
test('Server HTML and tokens are excluded from diagnostics and snapshots',async t=>{
  const h=setup(t,[bad(400,{description:'<script>'+TOKEN+'</script>'})]); await h.check();
  assert(!h.e.summaryBox.textContent.includes(TOKEN)); assert.equal(h.e.summaryBox.innerHTML,'');
  assert(!h.e.logBox.textContent.includes(TOKEN));
});
test('Mock reports unexpected requests even though production transport catches errors',async()=>{
  const m=mock.create([]); await assert.rejects(m.fetch(OFFICIAL+'/bot'+TOKEN+'/getMe'));
  assert.equal(m.violations.length,1);
});
test('Both CI workflows explicitly provision the same Node and run discovery',()=>{
  for(const file of ['image.yml','html-migrator.yml']) {
    const value=fs.readFileSync(path.join(root,'.github/workflows',file),'utf8');
    assert.match(value,/actions\/setup-node@v7/); assert.match(value,/node-version: '24'/);
    assert.match(value,/unittest discover -s tools -p 'test_\*\.py'/);
  }
});
test('Final URL containing a token is redacted in journal and diagnostics',async t=>{
  const h=await completed(t,[...sourceReads(),yes,yes,me(123456),yes,hook('https://hook.example.invalid/'+TOKEN)],'PARTIAL');
  assert.equal(h.op().actual.redacted,true);
  assert(!JSON.stringify(h.op()).includes(TOKEN));
  assert(!h.e.logBox.textContent.includes(TOKEN));
});
test('Late A rate limit survives change to B and back',async t=>{
  const d=mock.deferred(), h=setup(t,[{wait:d},...sourceReads()]);
  const operation=h.check(); await h.change('botToken',OTHER);
  d.resolve(mock.response(bad(429,{parameters:{retry_after:20}}))); await operation;
  await h.change('botToken',TOKEN); await h.check(); assert.equal(h.m.calls.length,1);
  h.clock.advance(20000); await flush(); await h.check(); assert.equal(h.m.calls.length,3);
});
test('Known mutation 429 before effects requires expiry and fresh check',async t=>{
  const h=await completed(t,[...sourceReads(),bad(429,{parameters:{retry_after:5}}),...sourceReads()],'ERROR');
  await h.apply(); await h.check(); assert.equal(h.m.calls.length,3);
  h.clock.advance(5000); await flush(); await h.apply(); assert.equal(h.m.calls.length,3);
  await h.check(); assert.equal(h.m.calls.length,5);
});
test('Future cooldown is not cleared by switching modes/endpoints',async t=>{
  const h=setup(t,[bad(429,{parameters:{retry_after:30}})]); await h.check();
  await h.modes.at(-1).click(); await h.change('oldApi','https://elsewhere.example.invalid');
  await h.change('webhookUrl','https://changed.example.invalid/hook');
  await h.apply(); await h.check(); assert.equal(h.m.calls.length,1);
});
test('Explicit URL is not confused with the source observation',async t=>{
  const expected='https://explicit.example.invalid/path/';
  const h=await completed(t,[...sourceReads(),yes,yes,me(123456),yes,hook(expected)],'SUCCESS',undefined,
    x=>{x.e.webhookUrl.value=expected;});
  assert.equal(h.op().plan.expectedWebhookUrl,expected);
  assert.equal(h.m.calls[5].body,'url='+encodeURIComponent(expected)+'&drop_pending_updates=false');
});
test('Markup in observed URL stays inert text',async t=>{
  const actual='https://hook.example.invalid/<img src=x onerror=alert(1)>';
  const h=await completed(t,[...sourceReads(),yes,yes,me(123456),yes,hook(actual)],'PARTIAL');
  assert(h.e.summaryBox.textContent.includes(actual)); assert.equal(h.e.summaryBox.innerHTML,'');
});
test('Snapshot stores safe source receipts and never credentials',async t=>{
  const h=setup(t,sourceReads()); await h.check();
  const snapshot=h.run('state.snapshot');
  assert(!JSON.stringify(snapshot).includes(TOKEN));
  assert.equal(snapshot.receipts.length,2);
  assert(snapshot.receipts.every(x=>x.receipt && x.status===200));
  assert(h.run('Object.isFrozen(state.snapshot.plan.sourceReceipts)'));
});
test('Pages source keeps the old path, excludes tools and has no production mock import',()=>{
  const config=fs.readFileSync(path.join(root,'_config.yml'),'utf8');
  assert.match(config,/baseurl: \/tg-selfhost-botapi/); assert.match(config,/\n  - tools\n/);
  assert(!html.includes('html_migrator_mock.js'));
  for(const language of ['en','ru']) {
    const doc=fs.readFileSync(path.join(root,'docs',language,'migration.md'),'utf8');
    assert(doc.includes('../../tg_selfhost_botapi_migrator.html'));
    for(const outcome of ['SUCCESS','ERROR','PARTIAL','UNKNOWN','BLOCKED','WAITING']) assert(doc.includes(outcome));
    assert(doc.includes('tools/check_docs.py'));
  }
});

}
