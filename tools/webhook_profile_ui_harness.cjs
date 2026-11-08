// Executes the shipped inline script and actual FormData. Synthetic inputs only.
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),assert=require('node:assert/strict');
const {page}=require('./issue10_ui_harness.cjs');
const html=fs.readFileSync(path.join(__dirname,'../tg_selfhost_botapi_migrator.html'),'utf8');
const secret='Synthetic_secret_7',pem="-----BEGIN CERTIFICATE-----\nMIIDFTCCAf2gAwIBAgIUXiIjm5V67BVj9iGApSk1SLUwc0swDQYJKoZIhvcNAQEL\nBQAwGjEYMBYGA1UEAwwPZXhhbXBsZS5pbnZhbGlkMB4XDTI2MTEwODExMjczN1oX\nDTM2MTEwNTExMjczN1owGjEYMBYGA1UEAwwPZXhhbXBsZS5pbnZhbGlkMIIBIjAN\nBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA3nFtlRATUN5IPC3aZXY4beOY/kel\nQLKixJHrN39spHGgneVS1Cf3DxkDo+2I2ONzRJ20LqlFvpbHR+SRAKI/omKbmeRh\n+IoDR11SJRmTvDUa6UMyAXCDnKhnFMOzcZeAR9H1YionLfmS8iU0lwpjgECZj9CU\n9lrs1Tilzep5TSUCq+9ZXmV97n5hZHrwr29frIanvUwYz9JPrECV2z77FjC/a2rN\n9vohYiMq29dsKyfPddlYE3cbYIQce3Bkkcc5iA7FSCBqTEOOCq0MDTfJaf1rTbsU\nRRkwfjWZynpI7I74lsqKoHuJcE6ivDPY+nFR9q2FJyrTbUEykxmBvYQQeQIDAQAB\no1MwUTAdBgNVHQ4EFgQUUs64hMhdnrn/eY3vzZLKsXW9qtEwHwYDVR0jBBgwFoAU\nUs64hMhdnrn/eY3vzZLKsXW9qtEwDwYDVR0TAQH/BAUwAwEB/zANBgkqhkiG9w0B\nAQsFAAOCAQEAcz7Dd5rhuexGldW/nfiqb1NvwtIzRkwMvzmBT7Ci7g+GfK1PDHvK\noB5h0ZP3tR5Y+RGV909+HGEaQU9El/C9SMpqqn8iyNQgL2rcG7PiabdkHdJ1q1+V\nfXSITq3FmGXEgRZEt3LeKRBJcDPdxsj/XGy3xs8YEVzei+C2n9IUUs7kiyVJH8y3\n641olRMTon2xlWNV5nhgvW9TvnzXVeajPPrzk99oCn+Tt5VO1HeaErRpBJfH0EgD\nxPDkWpZM6lnLTrnrt0zAbNgYcYe7Vy4gZDuSCs99VVaCU0EhR8jSKN90m5jurWww\nvVNJaim3fyEk+s1sWr+DH0UGwaSzSBxhqQ==\n-----END CERTIFICATE-----\n";
function configure(p,cert=false){
  for(const [id,v] of Object.entries({secretMode:'provided',secretToken:secret,allowedUpdates:'["message","callback_query"]',maxConnections:'7',ipMode:'pinned',ipAddress:'203.0.113.7'}))p.elements.get(id).value=v;
  if(cert){p.elements.get('certificateMode').value='provided';p.elements.get('certificateFile').files=[new File([pem],'private-input.pem')];}
}
function projection(input){
  const source=html.split('// BEGIN PROFILE RESOLVER')[1].split('// END PROFILE RESOLVER')[0],ctx=vm.createContext({input,atob});
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
  {
    const p=page({hook:'https://sink.test/webhook',fastTimers:true});configure(p);
    p.elements.get('certificateMode').value='provided';p.elements.get('certificateFile').files=[new File(['-----BEGIN CERTIFICATE-----\nPLACEHOLDER\n-----END CERTIFICATE-----'],'invalid.pem')];
    await p.run('executeInBrowser()');assert(!p.calls.some(c=>['deleteWebhook','logOut','setWebhook'].includes(c.method)));count++;
  }
  {
    const p=page({hook:'https://sink.test/webhook',fastTimers:true});configure(p);
    p.elements.get('certificateMode').value='provided';p.elements.get('certificateFile').files=[new File(['-----BEGIN CERTIFICATE-----\nMAUwAwIBAQ==\n-----END CERTIFICATE-----'],'invalid.pem')];
    await p.run('executeInBrowser()');assert(!p.calls.some(c=>['deleteWebhook','logOut','setWebhook'].includes(c.method)));count++;
  }
  {
    const now=Math.floor(Date.now()/1000), p=page({hook:'https://sink.test/webhook',sourceProfile:{last_error_date:now},readback:{last_error_date:now},fastTimers:true});
    p.run(`Date.now=()=>${now}000`);configure(p);await p.run('executeInBrowser()');
    assert.equal(p.run('state.completedMigration'),false,p.logs());assert(p.logs().includes('"new_error":true'));assert(p.logs().includes('"delivery_observation":"degraded"'));count++;
  }
  for(const id of ['secretMode','secretToken','allowedUpdates','maxConnections','targetLocal','ipMode','ipAddress','certificateMode','certificateFile']){
    const p=page({fastTimers:true});await p.run('checkCurrentState()');const revision=p.run('state.revision');p.elements.get(id).events.change();assert(p.run('state.revision')>revision);assert.equal(p.run('state.checkedConfig'),'');count++;
  }
  for(const mismatch of [{max_connections:41},{allowed_updates:['chat_member']},{has_custom_certificate:true},{ip_address:'203.0.113.99'},{max_connections:null},{last_error_date:Math.floor(Date.now()/1000)},{last_synchronization_error_date:9999}]){
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
