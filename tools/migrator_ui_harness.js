// #14: same-origin helper replaces the legacy direct-fetch runtime.
const migrationModuleHtml = require('node:fs').readFileSync(require('node:path').join(__dirname, '..', 'tg_selfhost_botapi_migrator.html'), 'utf8');
if (migrationModuleHtml.includes('src="assets/js/migration-client.mjs"')) {
  import('./test_migration_ui.mjs').then(() => console.log('helper contract checks passed')).catch(() => { process.exitCode = 1; });
} else {
'use strict';
// Execute the shipped inline script with an in-memory DOM and intercepted fetch.
// No real fetch/network is exposed to the VM.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const { File } = require('node:buffer');
const root = path.resolve(__dirname,'..');
const html = fs.readFileSync(path.join(root,'tg_selfhost_botapi_migrator.html'),'utf8');
const script = html.split('<script>')[1].split('</script>')[0];
const fixtures = JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/issue7_webhook_profiles.json')));
const TOKEN = '123456:SYNTHETIC_bot_token_abcdefghijkl';
const SECRET = 'SYNTHETIC_webhook_secret';
const PEM = '-----BEGIN CERTIFICATE-----\nU1lOVEhFVElD\n-----END CERTIFICATE-----\n';
class Element {
  constructor(id='') { this.id=id; this._value=''; this.files=[]; this.checked=false; this.disabled=false; this.textContent=''; this.children=[]; this.style={}; this.dataset={}; this.events={}; this.classList={toggle(){}}; }
  get value() { return this._value; }
  set value(value) { this._value=value; if (this.id === 'certificateFile' && value === '') this.files=[]; }
  addEventListener(event,callback) { (this.events[event] ||= []).push(callback); }
  appendChild(child) { this.children.push(child); }
}
function setup(mode='official-to-self', options={}) {
  const elements = new Map();
  const get = id => { if (!elements.has(id)) elements.set(id,new Element(id)); return elements.get(id); };
  for (const match of html.matchAll(/id="([^"]+)"/g)) get(match[1]);
  const cards = ['official-to-self','self-to-self','self-to-official','hook-only'].map(mode => { const el = new Element(); el.dataset.mode=mode; return el; });
  const document = {getElementById:get,createElement:() => new Element(),querySelectorAll:selector => selector === '.mode-btn' ? cards : [...elements.values()]};
  let target = {...fixtures.source.result,url:''}, installed=false, samples=0;
  const requests=[], mutations=[];
  let clipboard='';
  const source = {ok:true,result:{...fixtures.source.result,...options.source}};
  const context = vm.createContext({document,URL,URLSearchParams,FormData,Blob,File,AbortController,
    confirm:()=>true, navigator:{clipboard:{writeText:async text=>{clipboard=text;}}},
    setTimeout:(cb,ms)=>ms === 5000 ? (queueMicrotask(cb),0) : setTimeout(cb,ms),clearTimeout,
    fetch:async (url,request)=>{
      const method = url.slice(url.lastIndexOf('/')+1);
      const fields={}, files={};
      if (request.body) for (const [name,value] of request.body.entries()) {
        if (typeof value === 'string') fields[name]=value;
        else files[name]=await value.text();
      }
      requests.push({method,fields,files,url});
      if (request.method === 'POST') mutations.push(method);
      if (options.beforeFetch) await options.beforeFetch(method,context);
      const result = data => ({ok:true,json:async()=>({ok:true,result:data})});
      if (options.failure === method) {
        if (options.failureType === 'timeout') throw Error(SECRET + TOKEN + PEM);
        if (options.failureType === 'non-json') return {ok:true,json:async()=>{throw Error(SECRET);}};
        return {ok:options.failureType !== 'http',json:async()=>({ok:false,description:SECRET + TOKEN + PEM + '<img src=x>'})};
      }
      if (method === 'getMe') return result({id:123456});
      if (method === 'getWebhookInfo') {
        if (installed && options.postUnavailable) throw Error(SECRET + TOKEN);
        if (!installed) return result(structuredClone(url.startsWith((mode === 'official-to-self' ? 'https://api.telegram.org' : 'https://source.example') + '/') ? source.result : target));
        const observed = {...target,...(options.observations || [])[samples++]};
        return result(observed);
      }
      if (method === 'setWebhook') {
        installed=true;
        target = {...target,url:fields.url,allowed_updates:JSON.parse(fields.allowed_updates),max_connections:Number(fields.max_connections),has_custom_certificate:!!files.certificate,ip_address:fields.ip_address || '203.0.113.21'};
      }
      return result(true);
    }
  });
  vm.runInContext(script + '\nglobalThis.harness={state,els,resolveProfile,validSnapshot,compareSnapshot,currentConfig,executeInBrowser,checkCurrentState,buildCommands,copyCurlPlan,invalidate,binding};',context);
  const h=context.harness;
  h.state.mode=mode;
  Object.assign(get('botToken'),{value:TOKEN});
  get('oldApi').value='https://source.example';
  get('newApi').value='https://target.example';
  get('secretMode').value='provided';
  get('secretToken').value=SECRET;
  get('ipMode').value='fixed';
  get('ipAddress').value='203.0.113.10';
  get('certificateMode').value=options.multipart ? 'provided' : 'none';
  if (options.multipart) get('certificateFile').files=[new File([PEM],'sensitive,;".pem')];
  return {h,get,requests,mutations,context,clipboard:()=>clipboard,output:()=>get('summaryBox').textContent+'\n'+get('logBox').children.map(e=>e.textContent).join('\n')};
}
async function main() {
  if (process.argv[2] === '--export') {
    const env = setup(process.argv[3],{multipart:process.argv[4] === 'multipart'});
    env.get('targetLocal').checked=true;
    env.get('allowedUpdates').value='["message","chat_member"]';
    env.get('maxConnections').value='50';
    process.stdout.write(env.h.buildCommands(env.h.currentConfig()).join('\n')+'\n');
    return;
  }
  let passed=0;
  const base = setup();
  for (const fixture of fixtures.cases) {
    const snapshot={ok:true,result:{...fixtures.source.result,...fixture.result}};
    for (const key of fixture.remove || []) delete snapshot.result[key];
    const result=base.h.resolveProfile({...fixtures.base,...fixture.config},snapshot);
    assert.equal(result.complete,fixture.complete,fixture.id);
    assert.equal(result.profile.version,fixtures.version,'contract version');
    passed++;
  }
  for (const mode of ['official-to-self','self-to-self','self-to-official','hook-only']) for (const multipart of [false,true]) {
    const env=setup(mode,{multipart});
    // Hidden new endpoint must never participate in hook-only resolution.
    if (mode === 'hook-only') env.get('newApi').value='https://unused.example';
    await env.h.executeInBrowser();
    const set=env.requests.find(r=>r.method === 'setWebhook');
    assert.ok(set,'setWebhook executed');
    assert.equal(set.fields.secret_token,SECRET,'scalar secret matches');
    assert.ok(!Object.hasOwn(set.files,'secret_token'),'secret is not an attachment');
    assert.equal(set.fields.max_connections,'40');
    assert.equal(set.fields.allowed_updates,'[]');
    assert.equal(set.fields.ip_address,'203.0.113.10');
    assert.equal(set.files.certificate,multipart ? PEM : undefined,'certificate bytes match');
    assert.match(env.output(),/readable=PASS/);
    assert.match(env.output(),/delivery=NOTRUN/);
    assert.equal(env.get('secretToken').value,'');
    assert.equal(env.get('certificateFile').files.length,0);
    assert.ok(!env.h.state.busy && !env.get('btnExecute').disabled);
    if (mode === 'hook-only') assert.ok(set.url.startsWith('https://source.example/'));
    passed++;
  }
  for (const configure of [e=>e.get('secretMode').value='',e=>e.get('secretToken').value=SECRET+'\n',e=>e.get('ipMode').value='',e=>e.get('maxConnections').value='100001',e=>e.get('allowedUpdates').value='null',e=>e.get('certificateMode').value='provided',e=>{e.get('certificateMode').value='provided';e.get('certificateFile').files=[new File(['-----BEGIN PRIVATE KEY-----'],'private.pem')];}]) {
    const env=setup(); configure(env); await env.h.executeInBrowser();
    assert.equal(env.mutations.length,0,'invalid input must not mutate'); passed++;
  }
  for (const failureType of ['api','http','non-json','timeout']) {
    const env=setup('official-to-self',{failure:'deleteWebhook',failureType});
    await env.h.executeInBrowser();
    assert.equal(env.mutations.join(','),'deleteWebhook','error stops lifecycle');
    for (const privateValue of [TOKEN,SECRET,PEM,encodeURIComponent(SECRET)]) assert.ok(!env.output().includes(privateValue),'diagnostic privacy');
    assert.ok(!env.output().includes('<img'));
    assert.match(env.output(),failureType === 'non-json' || failureType === 'timeout' ? /UNKNOWN/ : /FAIL/);
    passed++;
  }
  for (const patch of [{url:'https://wrong.example/hook'},{allowed_updates:['chat_member']},{max_connections:41},{has_custom_certificate:true},{ip_address:'203.0.113.99'}]) {
    const env=setup('hook-only',{observations:[patch,patch,patch]});
    await env.h.executeInBrowser(); assert.match(env.output(),/readable=FAIL/); passed++;
  }
  const fresh=setup('hook-only',{observations:[{}, {last_error_date:10}, {last_error_date:10}]});
  await fresh.h.executeInBrowser(); assert.match(fresh.output(),/errors=new/); passed++;
  const historical=setup('hook-only',{source:{last_error_date:10,last_error_message:SECRET},observations:[{last_error_date:10},{last_error_date:10},{last_error_date:10}]});
  await historical.h.executeInBrowser(); assert.match(historical.output(),/readable=PASS/); assert.match(historical.output(),/errors=historical/); passed++;
  const queue=setup('hook-only',{observations:[{pending_update_count:0},{pending_update_count:1},{pending_update_count:2}]});
  await queue.h.executeInBrowser(); assert.match(queue.output(),/queue=growing/); passed++;
  const unavailable=setup('hook-only',{postUnavailable:true});
  await unavailable.h.executeInBrowser(); assert.match(unavailable.output(),/readable=UNKNOWN/); assert.match(unavailable.output(),/queue=UNKNOWN/); passed++;
  const lostSet=setup('hook-only',{failure:'setWebhook',failureType:'timeout'});
  await lostSet.h.executeInBrowser(); assert.equal(lostSet.mutations.join(','),'setWebhook'); assert.match(lostSet.output(),/UNKNOWN/); passed++;
  const dns=setup('hook-only'); dns.get('ipMode').value='dns'; dns.get('ipAddress').value=''; dns.get('secretMode').value='none'; dns.get('secretToken').value='';
  dns.get('allowedUpdates').value='["message_reaction","chat_member","chat_member"]';
  await dns.h.executeInBrowser();
  const dnsSet=dns.requests.find(r=>r.method==='setWebhook');
  assert.ok(!Object.hasOwn(dnsSet.fields,'secret_token') && !Object.hasOwn(dnsSet.fields,'ip_address'));
  assert.equal(dnsSet.fields.allowed_updates,'["chat_member","message_reaction"]'); passed++;
  const polling=setup('official-to-self',{source:{url:''}}); polling.get('secretMode').value=''; polling.get('ipMode').value='';
  await polling.h.executeInBrowser(); assert.ok(!polling.mutations.includes('setWebhook')); assert.match(polling.output(),/readable=PASS/); passed++;
  const expired=setup(); await expired.h.checkCurrentState(); expired.h.state.snapshot.time=0;
  const countBefore=expired.requests.length; await expired.h.executeInBrowser();
  assert.ok(expired.requests.slice(countBefore).some(r=>r.method === 'getMe')); passed++;
  const stale=setup();
  await stale.h.checkCurrentState(); assert.ok(stale.h.state.snapshot); stale.h.invalidate(); assert.equal(stale.h.state.snapshot,null); passed++;
  let release;
  const late=setup('official-to-self',{beforeFetch:method=>method === 'getMe' ? new Promise(r=>{release=r;}) : undefined});
  const checking=late.h.checkCurrentState(); late.h.invalidate(); release(); await checking;
  assert.equal(late.h.state.snapshot,null,'late snapshot discarded'); passed++;
  let resume;
  const blocking=setup('official-to-self',{beforeFetch:method=>method === 'getMe' && !resume ? new Promise(r=>{resume=r;}) : undefined});
  const running=blocking.h.executeInBrowser();
  assert.ok(blocking.get('btnExecute').disabled);
  await blocking.h.executeInBrowser(); resume(); await running;
  assert.equal(blocking.mutations.filter(m=>m==='setWebhook').length,1,'no duplicate run'); passed++;
  for (const mode of ['official-to-self','self-to-self','self-to-official','hook-only']) {
    const env=setup(mode,{multipart:true});
    env.get('webhookUrl').value='https://private.example/secret-path?key=private';
    await env.h.copyCurlPlan();
    const exported=env.clipboard();
    for (const privateValue of [TOKEN,SECRET,PEM,'sensitive,;".pem','private.example','source.example','target.example']) assert.ok(!exported.includes(privateValue),'export privacy');
    assert.ok(exported.includes('requires private inputs') && exported.includes('snapshot_private_inputs'));
    passed++;
  }
  console.log(passed+' UI/contract/export checks passed (mock fetch; live delivery NOTRUN)');
}
main().catch(error=>{
  const location = String(error.stack || '').split('\n').find(line => /at .*migrator_ui_harness\.js:[0-9]+/.test(line)) || '';
  console.error('Migrator UI harness failed (private values omitted) ' + location.trim());process.exitCode=1;
});

}
