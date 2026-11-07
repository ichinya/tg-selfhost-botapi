// Actual standalone inline HTML, intercepted fetch, and export generation. No external requests.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const {page} = require('./issue10_ui_harness.cjs');
const matrix = JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/issue9_action_contract.json')));
function cases() {
  const rows=[];
  for(const mode of ['official-to-self','hook-only']) for(const oldHook of matrix.sourceUrls)
    for(const targetHook of matrix.targetUrls) for(const action of matrix.actions) for(const drop of matrix.drop)
      if(!(mode==='hook-only' && action==='preserve' && drop)) rows.push({mode,oldHook,targetHook,action,drop,hook:matrix.setUrl});
  return rows;
}
async function tests() {
  let count=0;
  for(const row of cases()) {
    const p=page(row); await p.run('executeInBrowser()');
    assert(p.logs().includes('Конфигурация проверена'), JSON.stringify(row)+' '+p.logs());
    const role=row.mode==='hook-only'?'source':'target';
    const mutations=p.calls.filter(c=>c.role===role && ['setWebhook','deleteWebhook'].includes(c.method));
    const noop=row.mode==='hook-only' && row.action==='preserve';
    const method=row.action==='set'||(row.action==='preserve'&&row.oldHook)?'setWebhook':'deleteWebhook';
    assert.equal(mutations.length,noop?0:1);
    if(!noop) assert.equal(mutations[0].method,method);
    if(row.mode!=='hook-only') {
      const detach=p.calls.find(c=>c.role==='source'&&c.method==='deleteWebhook');
      assert.equal(new URLSearchParams(detach.request.body).get('drop_pending_updates'),'false');
      assert.equal(p.final().queues.source,3);
    } else assert(!p.calls.some(c=>['logOut','close','probe'].includes(c.method)));
    const result=p.final();
    assert.equal(role==='target'?result.targetHook:result.sourceHook,noop?row.oldHook:method==='setWebhook'?(row.action==='set'?row.hook:row.oldHook):'');
    assert.equal(result.queues[role],noop?(role==='source'?3:5):row.drop?0:(role==='source'?3:5));
    const before=p.calls.length; p.plan(); assert.equal(p.calls.length,before); count++;
  }
  for(const action of ['', 'bad', 'set']) {
    const p=page({action,hook:''}); await p.run('executeInBrowser()'); assert.equal(p.calls.length,0); count++;
  }
  for(const fields of [{secretMode:''},{ipMode:''},{allowedUpdates:''},{allowedUpdates:'[null]'},{maxConnections:'0'},
    {secretMode:'provided',webhookSecret:'bad!'}, {certificateMode:'provided'}]) {
    const p=page({action:'set',hook:matrix.setUrl,fields}); await p.run('executeInBrowser()');
    assert.equal(p.calls.length,0,JSON.stringify(fields)); count++;
  }
  let p=page({mode:'hook-only',action:'preserve',drop:true});await p.run('executeInBrowser()');assert.equal(p.calls.length,0);count++;
  p=page({action:'polling',hook:'bad URL',fields:{secretMode:'bad',allowedUpdates:'bad',maxConnections:'bad'}});
  await p.run('executeInBrowser()');assert(p.logs().includes('Конфигурация проверена'));count++;
  for(const method of ['deleteWebhook','setWebhook']) for(const failure of ['http','redirect','api','false-result','malformed','lost','lost-after']) {
    p=page({action:method==='deleteWebhook'?'polling':'set',hook:matrix.setUrl,oldHook:matrix.sourceUrls[1],targetHook:matrix.targetUrls[1],fail:'target:'+method,failure});
    await p.run('executeInBrowser()'); assert(!p.logs().includes('Конфигурация проверена'));
    assert(p.run('state.needsReconcile')); const n=p.calls.length;
    if(failure==='lost-after') assert.equal(p.final().targetHook,method==='deleteWebhook'?'':matrix.setUrl);
    else assert.equal(p.final().targetHook,matrix.targetUrls[1]);
    p.elements.get('deliveryAction').events.change();await p.run('executeInBrowser()');assert.equal(p.calls.length,n);count++;
  }
  p=page({action:'set',hook:matrix.setUrl,fields:{secretMode:'provided',webhookSecret:'private_canary_secret'}});
  const cert=new File(['-----BEGIN CERTIFICATE-----\nMAA=\n-----END CERTIFICATE-----\n'],'private-canary.pem');
  p.elements.get('certificateFile').files=[cert];p.elements.get('certificateMode').value='provided';
  await p.run('executeInBrowser()');assert(p.logs().includes('Конфигурация проверена'),p.logs());
  const body=p.calls.find(c=>c.method==='setWebhook').request.body;assert(body instanceof FormData);assert.equal(body.get('secret_token'),'private_canary_secret');
  p=page({action:'set',hook:matrix.setUrl,fields:{secretMode:'provided',webhookSecret:'private_canary_secret'}});
  const exported=p.plan();for(const canary of ['private_canary_secret',matrix.setUrl,'http://target.test/prefix','synthetic_token'])assert(!exported.includes(canary));
  assert(exported.includes('WEBHOOK_URL'));count++;
  // Input changes and simultaneous attempts cannot remove reconcile/completion locks or reuse a stale File.
  p=page({action:'polling'}); const first=p.run('executeInBrowser()');await p.run('executeInBrowser()');await first;
  assert.equal(p.calls.filter(c=>c.role==='target'&&c.method==='deleteWebhook').length,1);count++;
  for(const id of ['deliveryAction','webhookSecret','certificateFile','targetLocal','dropPending']) {
    p=page({action:'polling'});await p.run('checkCurrentState()');assert(p.run('state.checkedConfig'));
    p.elements.get(id).events.change();assert.equal(p.run('state.checkedConfig'),'');count++;
  }
  for(const failure of ['wrong-url','missing-url','number-url']) {
    p=page({action:'polling',fail:'target:getWebhookInfo',failure});await p.run('executeInBrowser()');
    assert(!p.logs().includes('Конфигурация проверена'));assert(p.run('state.needsReconcile'));count++;
  }
  for(const sourceProfile of [{allowed_updates:null},{max_connections:'40'},{has_custom_certificate:null}]) {
    p=page({action:'preserve',oldHook:matrix.sourceUrls[1],sourceProfile});await p.run('executeInBrowser()');
    assert(!p.calls.some(c=>['deleteWebhook','setWebhook','logOut'].includes(c.method)));count++;
  }
  p=page({action:'polling'});p.elements.get('newApi').value='https://API.TELEGRAM.ORG.:443';
  await p.run('executeInBrowser()');assert.equal(p.calls.length,0);count++;
  console.log('Issue9 actual inline HTML: '+count+' matrix/negative/fault/privacy scenarios PASS');
}
if(process.argv[2]==='--exports') {
  fs.mkdirSync(process.argv[3],{recursive:true});
  const rows=cases();rows.forEach((row,i)=>fs.writeFileSync(path.join(process.argv[3],i+'.sh'),page(row).plan()));
  fs.writeFileSync(path.join(process.argv[3],'rows.json'),JSON.stringify(rows));
} else if(process.argv[2]==='--profile-export') {
  const p=page({action:'preserve',fields:{secretMode:'provided',ipMode:'fixed',ipAddress:'192.0.2.1'}});
  fs.writeFileSync(process.argv[3],p.plan());
} else {
  const watchdog=setTimeout(()=>{console.error('Issue9 VM deadline');process.exit(1);},30000);
  tests().then(()=>clearTimeout(watchdog)).catch(e=>{clearTimeout(watchdog);console.error(e);process.exitCode=1;});
}
