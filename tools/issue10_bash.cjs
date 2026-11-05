const fs = require('node:fs');
const path = require('node:path');

function bashBinary() {
  const configured = process.env.ISSUE10_BASH;
  if (configured && !path.isAbsolute(configured)) throw new Error('ISSUE10_BASH must be an absolute path');
  const binary = configured || (process.platform === 'win32'
    ? path.join(process.env.ProgramFiles || 'C:/Program Files', 'Git/bin/bash.exe') : '/bin/bash');
  if (/[/\\]windows[/\\](system32|sysnative)[/\\]|[/\\]wsl\.exe$/i.test(binary)) {
    throw new Error('WSL launchers are not supported; set ISSUE10_BASH to Git Bash');
  }
  if (!fs.existsSync(binary)) throw new Error('Bash required; set ISSUE10_BASH to its full path');
  return binary;
}

function stopChild(child) {
  child.kill('SIGKILL');
  for (const stream of [child.stdin, child.stdout, child.stderr]) stream?.destroy();
}

module.exports = {bashBinary, stopChild};
