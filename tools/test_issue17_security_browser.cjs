const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync('tg_selfhost_botapi_migrator.html','utf8');
const begin=html.indexOf('    function publicOperation(run) {');
const end=html.indexOf('    function renderOperation(run)',begin);
assert(begin>0&&end>begin);
const context={};vm.createContext(context);
vm.runInContext("const stages=['prepared','target_verified'];\n"+html.slice(begin,end)+'\nthis.project=publicOperation;',context);
const marker='private_endpoint_canary';
const old={id:'operation-1',plan:{mode:'hook-only',source:marker,target:marker},expectedUrl:marker,
  sourceObservation:{url:marker,endpoint:marker},finalObservation:{url:marker,endpoint:marker},
  stages:{prepared:'CONFIRMED',target_verified:'UNKNOWN'},receipts:[{stage:'prepared',status:'UNKNOWN',method:'getMe',role:'source',description:marker}]};
const projected=context.project(old);
assert.doesNotThrow(()=>context.project(null));
assert.doesNotThrow(()=>context.project({...old,receipts:[null]}));
assert(!JSON.stringify(projected).includes(marker));
assert.equal(projected.stages.target_verified,'UNKNOWN');
assert.equal(projected.receipts[0].method,'getMe');
assert.deepEqual(JSON.parse(JSON.stringify(context.project(projected))),JSON.parse(JSON.stringify(projected)));
console.log('public browser projection checks passed');
