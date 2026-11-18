const fs=require('node:fs'),path=require('node:path');
const root=path.join(__dirname,'..'),check=process.argv.includes('--check');
const read=p=>fs.readFileSync(path.join(root,p),'utf8').replace(/\r\n/g,'\n');
const targets=[['migrate_off_to_self.sh',read('tools/migration_adapter.sh')],['tg_selfhost_botapi_migrator.html',read('tools/migration_entry.html')]];
for(const [name,value] of targets){
 if(check){if(read(name)!==value)throw new Error('Generated adapter out of date: '+name);}
 else fs.writeFileSync(path.join(root,name),value);
}
console.log('Canonical adapters checked');
