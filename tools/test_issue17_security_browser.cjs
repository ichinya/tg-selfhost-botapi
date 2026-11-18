const fs=require('node:fs'),assert=require('node:assert/strict');
const html=fs.readFileSync('tg_selfhost_botapi_migrator.html','utf8');
assert(!/<(?:script|input|textarea)\b/i.test(html));
const client=fs.readFileSync('assets/js/migration-client.mjs','utf8');
assert(!client.includes('innerHTML'));
import('./test_migration_ui.mjs').catch(error=>{console.error(error);process.exitCode=1;});
