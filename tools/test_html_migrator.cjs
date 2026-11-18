const fs=require('node:fs'),assert=require('node:assert/strict');
const html=fs.readFileSync('tg_selfhost_botapi_migrator.html','utf8');
assert(!/<(?:input|textarea|script)\b/i.test(html));
assert(html.includes('tools/migration_helper.py'));
const ui=fs.readFileSync('tools/migration_executor.html','utf8');
for(const value of ['cloud_to_local','local_to_local','local_to_cloud','webhook_only','preserve','set','polling']) assert(ui.includes('value="'+value+'"'));
import('./test_migration_ui.mjs').catch(error=>{console.error(error);process.exitCode=1;});
