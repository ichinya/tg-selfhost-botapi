// Resolver is data validation; mutation sequencing belongs to Python.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
if(process.argv.includes('--resolve')){
 const input=JSON.parse(fs.readFileSync(0,'utf8'));
 const source=fs.readFileSync(path.join(__dirname,'webhook_profile_resolver.js'),'utf8');
 const resolve=value=>vm.runInNewContext(source+';resolveWebhookProfile(input)',{input:value,atob});
 process.stdout.write(JSON.stringify(input.map(resolve)));
} else { require('./test_html_migrator.cjs'); }
