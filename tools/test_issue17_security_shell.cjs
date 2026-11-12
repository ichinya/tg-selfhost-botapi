const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
test('generated runtime equals canonical sources',()=>{
  const read=p=>fs.readFileSync(p,'utf8').replace(/\r\n/g,'\n');
  const runtime=read('tools/webhook_profile_runtime.sh');
  const helper=read('migrate_off_to_self.sh');
  assert(helper.includes(runtime));
  assert(helper.includes(read('tools/migration_diagnostics_main.sh')));
  const html=read('tg_selfhost_botapi_migrator.html');
  const embedded=html.match(/const webhookRuntime = (.*);\n    \/\/ END WEBHOOK RUNTIME/);
  assert.equal(JSON.parse(embedded[1]),runtime);
});
test('secret HTTP URL uses private curl configuration',()=>{
  const source=fs.readFileSync('tools/webhook_profile_runtime.sh','utf8');
  assert.match(source,/exec \{fd\}</);
  assert.match(source,/Protected input rejected/);
  const executor=fs.readFileSync('tools/migration_executor.sh','utf8');
  assert.match(executor,/migration_cli.py" "\$@"/);
  assert.doesNotMatch(executor,/cli .*\$BOT_TOKEN/);
});
