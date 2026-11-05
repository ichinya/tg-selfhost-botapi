// Cross-platform outer timeout: Windows timeout.exe is a sleep command.
const {spawn, spawnSync} = require('node:child_process');
const [seconds, command, ...args] = process.argv.slice(2);
if (!(Number(seconds) > 0) || !command) {
  console.error('Usage: node tools/issue10_timeout.cjs SECONDS COMMAND [ARGS...]');
  process.exit(2);
}
const child = spawn(command, args, {stdio: 'inherit', detached: process.platform !== 'win32'});
const timer = setTimeout(() => {
  console.error(`Outer timeout after ${seconds}s`);
  if (process.platform === 'win32' && child.pid) {
    spawnSync('taskkill.exe', ['/pid', String(child.pid), '/t', '/f'], {timeout: 3000, stdio: 'ignore'});
  } else if (child.pid) {
    try { process.kill(-child.pid, 'SIGKILL'); } catch {}
  }
  child.kill('SIGKILL');
  process.exit(124);
}, Number(seconds) * 1000);
child.on('error', error => { console.error(error.message); clearTimeout(timer); process.exit(1); });
child.on('exit', code => { clearTimeout(timer); process.exit(code ?? 1); });
