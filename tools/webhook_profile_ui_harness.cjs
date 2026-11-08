// Executes the shipped inline script and actual FormData. Synthetic inputs only.
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),assert=require('node:assert/strict');
const {page}=require('./issue10_ui_harness.cjs');
const html=fs.readFileSync(path.join(__dirname,'../tg_selfhost_botapi_migrator.html'),'utf8');
const secret='Synthetic_secret_7',pem='-----BEGIN CERTIFICATE-----\nUExBQ0VIT0xERVI=\n-----END CERTIFICATE-----\n';
function configure(p,cert=false){
  for(const [id,v] of Object.entries({secretMode:'provided',secretToken:secret,allowedUpdates:'["message","callback_query"]',maxConnections:'7',ipMode:'pinned',ipAddress:'203.0.113.7'}))p.elements.get(id).value=v;
  if(cert){p.elements.get('certificateMode').value='provided';p.elements.get('certificateFile').files=[new File([pem],'private-input.pem')];}
}
function projection(input){
  const source=html.split('// BEGIN PROFILE RESOLVER')[1].split('// END PROFILE RESOLVER')[0],ctx=vm.createContext({input});
  return JSON.parse(JSON.stringify(vm.runInContext(source+';resolveWebhookProfile(input)',ctx)));
}
async function tests(){
  let count=0;
  for(const c of JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/webhook-profile-v1.json'))).cases){const r=projection(c.input);assert.equal(r.complete,c.complete,c.id);assert.deepEqual(r.missing,c.missing,c.id);assert.deepEqual(r.invalid,c.invalid,c.id);assert(!JSON.stringify(r).includes(secret));count++;}
  for(const cert of [false,true]){
    const p=page({hook:'https://sink.test/webhook',fastTimers:true});configure(p,cert);await p.run('executeInBrowser()');
    assert.equal(p.run('state.completedMigration'),true,p.logs());
    const c=p.calls.find(c=>c.method==='setWebhook');assert(c);
    const form=cert?c.request.body:new URLSearchParams(c.request.body);
    assert.equal(form.get('secret_token'),secret);assert.equal(form.get('max_connections'),'7');assert.equal(form.get('ip_address'),'203.0.113.7');
    assert.deepEqual(JSON.parse(form.get('allowed_updates')),['message','callback_query']);
    if(cert){assert.equal(await form.get('certificate').text(),pem);assert(!c.request.headers);}
    assert(!p.logs().includes(secret));assert(!p.logs().includes('BEGIN CERTIFICATE'));assert(!p.run('JSON.stringify(state)').includes(secret));
    assert(p.logs().includes('delivery_confirmed'));assert(!p.run('JSON.stringify(state)').includes('synthetic_token'));count++;
  }
  for(const values of [{secretMode:'unknown'},{ipMode:'unknown'},{allowedUpdates:'null'},{maxConnections:'100000'},{certificateMode:'provided'},{secretMode:'provided',secretToken:'bad space'}]){
    const p=page({hook:'https://sink.test/webhook',fastTimers:true});for(const [id,v]of Object.entries(values))p.elements.get(id).value=v;
    await p.run('executeInBrowser()');assert(!p.calls.some(c=>['deleteWebhook','logOut','setWebhook'].includes(c.method)));assert(!p.calls.some(c=>c.role==='target'&&c.method!=='probe'));count++;
  }
  for(const id of ['secretMode','secretToken','allowedUpdates','maxConnections','targetLocal','ipMode','ipAddress','certificateMode','certificateFile']){
    const p=page({fastTimers:true});await p.run('checkCurrentState()');const revision=p.run('state.revision');p.elements.get(id).events.change();assert(p.run('state.revision')>revision);assert.equal(p.run('state.checkedConfig'),'');count++;
  }
  for(const mismatch of [{max_connections:41},{allowed_updates:['chat_member']},{has_custom_certificate:true},{ip_address:'203.0.113.99'},{max_connections:null},{last_error_date:9999},{last_synchronization_error_date:9999}]){
    const p=page({hook:'https://sink.test/webhook',readback:mismatch,fastTimers:true});configure(p);await p.run('executeInBrowser()');assert.equal(p.run('state.needsReconcile'),true,p.logs());assert.equal(p.run('state.completedMigration'),false);const n=p.calls.length;await p.run('executeInBrowser()');assert.equal(p.calls.length,n);count++;
  }
  const p=page({hook:'https://sink.test/private-url',fastTimers:true});configure(p,true);
  const plan=p.plan();for(const value of [secret,pem,'private-input.pem','https://sink.test/private-url','synthetic_token'])assert(!plan.includes(value),value);
  assert(plan.includes('WEBHOOK_SECRET_TOKEN_FILE'));assert(plan.includes('wp_resolve'));count++;
  console.log(`${count} webhook profile UI/fixture/privacy checks PASS`);
}
async function main(){
 if(process.argv[2]==='--resolve') {let data='';for await(const c of process.stdin)data+=c;console.log(JSON.stringify(JSON.parse(data).map(i=>projection(i))));}
 else if(process.argv[2]==='--export')console.log(page({hook:'https://sink.test/private-ui-value'}).plan());
 else if(process.argv[2]==='--http-case'){
   const base=process.argv[3],cert=process.argv[4]==='certificate';
   const p=page({hook:'https://sink.test/webhook',fastTimers:true,transport:async c=>{
     const u=new URL(c.url);const route=c.method==='probe'?'/target/':`/${c.role}${u.pathname}`;
     return fetch(base+route,c.request);
   }});configure(p,cert);await p.run('executeInBrowser()');assert.equal(p.run('state.completedMigration'),true,p.logs());console.log('Actual UI HTTP '+(cert?'multipart':'urlencoded')+' PASS');
 }else await tests();
}
module.exports={projection,configure};
if(require.main===module){const watchdog=setTimeout(()=>{console.error('Profile harness deadline');process.exit(1);},60000);main().then(()=>clearTimeout(watchdog)).catch(e=>{clearTimeout(watchdog);console.error(e);process.exitCode=1;});}
