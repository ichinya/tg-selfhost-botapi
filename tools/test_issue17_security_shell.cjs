const fs=require('node:fs'),assert=require('node:assert/strict');
const read=p=>fs.readFileSync(p,'utf8').replace(/\r\n/g,'\n');
assert.equal(read('migrate_off_to_self.sh'),read('tools/migration_adapter.sh'));
assert.equal(read('tg_selfhost_botapi_migrator.html'),read('tools/migration_entry.html'));
assert(!read('migrate_off_to_self.sh').includes('wp_migration_main'));
const executor=read('tools/migration_executor.sh');
assert(executor.includes('migration_cli.py" "$@"'));
assert(!/cli .*\$BOT_TOKEN/.test(executor));
