// The shipped migrator must load the helper client tested below.
const fs = require('node:fs');
const path = require('node:path');
require('./test_issue17_security_browser.cjs');
const html = fs.readFileSync(path.join(__dirname, 'migration_executor.html'), 'utf8');
if (!html.includes('src="assets/js/migration-client.mjs"')) {
  throw new Error('Migrator HTML must load assets/js/migration-client.mjs');
}
import('./test_migration_ui.mjs')
  .then(() => console.log('helper contract checks passed'))
  .catch(error => { console.error(error); process.exitCode = 1; });
