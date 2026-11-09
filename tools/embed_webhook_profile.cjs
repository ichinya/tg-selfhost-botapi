// Keep shipped helper, browser resolver and exported Bash identical to canonical sources.
const fs=require('node:fs'),path=require('node:path');
const root=path.join(__dirname,'..'),check=process.argv.includes('--check');
const read=p=>fs.readFileSync(path.join(root,p),'utf8').replace(/\r\n/g,'\n');
const runtime=read('tools/webhook_profile_runtime.sh'),resolver=read('tools/webhook_profile_resolver.js');
const diagnostics=read('tools/migration_diagnostics_main.sh');
const helper='#!/usr/bin/env bash\nset +x\nset +v\nset -euo pipefail\nWP_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"\n'+runtime+'\n'+diagnostics+'\nwp_migration_main "$@"\n';
let html=read('tg_selfhost_botapi_migrator.html');
html=html.replace(/    \/\/ BEGIN PROFILE RESOLVER[\s\S]*?    \/\/ END PROFILE RESOLVER/,()=> '    // BEGIN PROFILE RESOLVER\n'+resolver+'    // END PROFILE RESOLVER');
html=html.replace(/    \/\/ BEGIN WEBHOOK RUNTIME[\s\S]*?    \/\/ END WEBHOOK RUNTIME/,()=> '    // BEGIN WEBHOOK RUNTIME\n    const webhookRuntime = '+JSON.stringify(runtime).replaceAll('<','\\u003c')+';\n    // END WEBHOOK RUNTIME');
for(const [p,t] of [['migrate_off_to_self.sh',helper],['tg_selfhost_botapi_migrator.html',html]]) {
  if(check){if(read(p)!==t)throw new Error('Generated file out of date: '+p);}else fs.writeFileSync(path.join(root,p),t);
}
console.log('Embedded runtime/resolver '+(check?'check PASS':'updated'));
