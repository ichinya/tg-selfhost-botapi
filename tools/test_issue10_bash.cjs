// Loopback-only integration check using the real helper and curl.
const http = require('http');
const fs = require('fs');
const os = require('os');
const path = require('path');
const {spawn} = require('child_process');
const assert = require('assert');
const {bashBinary, stopChild} = require('./issue10_bash.cjs');
let activeChild;
const watchdog = setTimeout(() => {
  console.error('Bash harness watchdog expired after 300s');
  if (activeChild) stopChild(activeChild);
  process.exit(1);
}, 300000);

(async () => {
  const bash = bashBinary();
  const events = [];
  let scenario = {}, targetHook = '';
  async function server(role) {
    const s = http.createServer(async (req, res) => {
      let body = '';
      for await (const chunk of req) body += chunk;
      events.push([role, req.url, body, req.headers]);
      if (role === 'target' && !req.url.includes('/bot')) {
        if (scenario.probe === 'redirect') { res.writeHead(302, {Location:urls[2]}); return res.end(); }
        if (scenario.probe === 'http') { res.writeHead(500); return res.end(); }
        if (scenario.probe === 'malformed') { res.writeHead(404); return res.end('<html>Not Found</html>'); }
        if (scenario.probe === 'timeout') return;
        res.writeHead(404, {'Content-Type':'application/json'});
        return res.end(JSON.stringify({ok:false,error_code:404,description:'Not Found'}));
      }
      if (role === 'sink') { res.writeHead(404); return res.end('not an API'); }
      const method = req.url.split('/').at(-1);
      if (scenario.fail === `${role}:${method}`) {
        if (scenario.failure === 'lost') return req.socket.destroy();
        if (scenario.failure === 'redirect') { res.writeHead(302, {Location:urls[2]}); return res.end(); }
        res.writeHead(scenario.failure === 'unauthorized' ? 401 : scenario.failure === 'http' ? 500 : 200, {'Content-Type':'application/json'});
        return res.end(scenario.failure === 'malformed' ? '{' : JSON.stringify(
          scenario.failure === 'false-result' ? {ok:true,result:false} : {ok:false,error_code:429,description:'Synthetic rejection'}));
      }
      let result = true;
      if (req.url.endsWith('/getMe')) result = {id:123,first_name:'Test',username:'test'};
      if (req.url.endsWith('/getWebhookInfo')) result = {url:role === 'target' ? targetHook : ''};
      if (method === 'setWebhook') targetHook = new URLSearchParams(body).get('url');
      res.writeHead(200, {'Content-Type':'application/json'});
      res.end(JSON.stringify({ok:true,result}));
    });
    await new Promise((resolve, reject) => { s.once('error', reject); s.listen(0, '127.0.0.1', resolve); });
    return s;
  }
  const servers = await Promise.all(['source','target','sink'].map(server));
  const urls = servers.map(s => `http://127.0.0.1:${s.address().port}`);
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'issue10-'));
  const helper = path.join(tmp, 'helper.sh');
  fs.copyFileSync(path.join(__dirname, '..', 'migrate_off_to_self.sh'), helper);
  fs.copyFileSync(helper, path.join(tmp, 'migrate_off_to_self.sh'));
  const baseEnv = Object.fromEntries(Object.entries(process.env).filter(([key]) =>
    /^(PATH|SYSTEMROOT|WINDIR|TEMP|TMP|COMSPEC|HOME|ISSUE10_BASH)$/i.test(key)));
  async function run(answer, target, options = {}) {
    events.length = 0;
    scenario = options; targetHook = '';
    const runRoot = fs.mkdtempSync(path.join(tmp, 'run-'));
    fs.copyFileSync(helper, path.join(runRoot, 'helper.sh'));
    fs.copyFileSync(helper, path.join(runRoot, 'migrate_off_to_self.sh'));
    return await new Promise((resolve, reject) => {
      const child = activeChild = spawn(bash, ['-c', options.command ||
        'bash ./helper.sh "$1" "$2"', '_', '123:synthetic', target], {
        cwd:runRoot,
        env: {...baseEnv, OFFICIAL_BOT_URL:urls[0], SELF_BOT_URL:urls[1], NO_PROXY:'127.0.0.1', no_proxy:'127.0.0.1'},
        stdio:['pipe','pipe','pipe']
      });
      let output = '', stderr = '';
      const timer = setTimeout(() => {
        stopChild(child);
        reject(new Error('Child deadline expired after 12s'));
      }, 12000);
      child.stdout.on('data', d => output += d);
      child.stderr.on('data', d => { stderr += d; output += d; });
      child.on('error', error => { clearTimeout(timer); activeChild = null; reject(error); });
      child.on('close', code => { clearTimeout(timer); activeChild = null; resolve({code, output, stderr}); });
      child.stdin.on('error', () => {});
      child.stdin.end(answer);
    });
  }
  try {
    let unauthorized = await run('y\n', urls[1], {fail:'source:getMe', failure:'unauthorized'});
    assert.notStrictEqual(unauthorized.code, 0);
    assert(unauthorized.stderr.includes('HTTP 401'));
    assert(unauthorized.stderr.includes('error_code=429'));
    assert(!unauthorized.output.includes('123:synthetic'));
    assert(!events.some(([role,url]) => role === 'target' && url.includes('/bot')));
    let result = await run('n\n', urls[1]);
    assert.strictEqual(result.code, 0, result.output);
    assert.deepStrictEqual(events.map(e => e.slice(0, 2)), [['target','/']]);
    result = await run('', urls[1]);
    assert.strictEqual(result.code, 0, result.output);
    assert.deepStrictEqual(events.map(e => e.slice(0, 2)), [['target','/']]);
    result = await run('y\n', urls[2]);
    assert.notStrictEqual(result.code, 0);
    assert.deepStrictEqual(events.map(e => e.slice(0, 2)), [['sink','/']]);
    assert(!JSON.stringify(events).includes('123:synthetic'));
    for (const probe of ['redirect','malformed','timeout']) {
      result = await run('y\n', urls[1], {probe});
      assert.notStrictEqual(result.code, 0, result.output);
      assert.deepStrictEqual(events.map(e => e.slice(0, 2)), [['target','/']]);
    }
    for (const fail of ['source:getMe','source:getWebhookInfo','source:deleteWebhook','source:logOut']) {
      for (const failure of ['api','http','malformed','lost','redirect','false-result']) {
        if (failure === 'false-result' && !/deleteWebhook|logOut/.test(fail)) continue;
        result = await run('y\n', urls[1], {fail,failure});
        assert.notStrictEqual(result.code, 0, `${fail}/${failure}: ${result.output}`);
        assert(!events.some(([r,u]) => r === 'target' && u.includes('/bot')), JSON.stringify(events));
        assert(!events.some(([r]) => r === 'sink'));
        assert(!result.output.includes('DONE'));
      }
    }
    result = await run('y\n', urls[1]);
    assert.strictEqual(result.code, 0, result.output);
    const logout = events.findIndex(([r, u]) => r === 'source' && u.endsWith('/logOut'));
    const login = events.findIndex(([r, u]) => r === 'target' && u.endsWith('/getMe'));
    assert(logout > 0 && login > logout, JSON.stringify(events));
    result = await run('y\n', urls[1] + '/prefix');
    assert.strictEqual(result.code, 0, result.output);
    assert(events.some(([,u]) => u.startsWith('/prefix/bot')));
    for (const language of ['en','ru']) {
      const doc = fs.readFileSync(path.join(__dirname, '..', 'docs', language, 'migration.md'), 'utf8');
      for (const form of ['environment','positional']) {
        const marker = '<!-- issue10-example:' + form + ' -->';
        const section = doc.split(marker)[1];
        assert(section, `Missing ${language}/${form} published example`);
        const block = section.split('```sh')[1]?.split('```')[0];
        assert(block, `Missing ${language}/${form} shell block`);
        const command = block.replace(/\r\n/g, '\n').replace(/^read -rsp[^\n]*$/m, "BOT_TOKEN='123:synthetic'")
          .replaceAll('http://127.0.0.1:18080', urls[1])
          .replaceAll('https://example.com/telegram/webhook', urls[2] + '/telegram/webhook');
        result = await run('y\n', urls[1], {command});
        assert.strictEqual(result.code, 0, `${language}/${form}: ${result.output}`);
        const set = events.find(([role,url]) => role === 'target' && url.endsWith('/setWebhook'));
        assert(set, `No target setWebhook: ${language}/${form}`);
        assert.strictEqual(new URLSearchParams(set[2]).get('url'), urls[2] + '/telegram/webhook');
        assert(!events.some(([role]) => role === 'sink'));
        if (form === 'positional') {
          const swapped = command.replaceAll(urls[1], '__API__')
            .replaceAll(urls[2] + '/telegram/webhook', urls[1])
            .replaceAll('__API__', urls[2] + '/telegram/webhook');
          result = await run('y\n', urls[1], {command:swapped});
          assert.notStrictEqual(result.code, 0, 'Reversed published arguments must fail');
          assert(events.every(([role]) => role === 'sink'));
          assert(!JSON.stringify(events).includes('123:synthetic'));
        }
      }
    }
    const {page} = require('./issue10_ui_harness.cjs');
    const generated = page({hook:'https://sink.test/webhook'}).plan()
      .replaceAll('https://api.telegram.org', urls[0])
      .replaceAll('http://target.test/prefix', urls[1])
      .replaceAll('https://sink.test/webhook', urls[2] + '/webhook');
    for (const probe of ['redirect','malformed','http']) {
      result = await run('', urls[1], {command:generated, probe});
      assert.notStrictEqual(result.code, 0, result.output);
      assert(result.stderr.includes('phase='), 'probe failure must report outcome');
    }
    result = await run('', urls[1], {command:generated.replaceAll(urls[1], 'http://127.0.0.1:1')});
    assert.notStrictEqual(result.code, 0, result.output);
    assert(result.stderr.includes('phase='), 'unavailable probe must report outcome');
    for (const failure of [null,'api','http','malformed','lost','redirect','false-result']) {
      result = await run(`y\n123:synthetic\n${urls[2]}/webhook\n`, urls[1], {command:generated,
        ...(failure ? {fail:'source:logOut',failure} : {})});
      if (failure) {
        assert.notStrictEqual(result.code, 0, result.output);
        assert(!events.some(([role,url]) => role === 'target' && url.includes('/bot')));
      } else {
        assert.strictEqual(result.code, 0, result.output);
        assert(events.findIndex(([,u]) => u.endsWith('/logOut')) < events.findIndex(([r,u]) => r === 'target' && u.endsWith('/getMe')));
      }
      assert(!events.some(([role]) => role === 'sink'));
    }
    console.log('Bash loopback: consent, probe, failures, ordering, prefix and four published examples passed');
  } finally {
    for (const s of servers) { s.closeAllConnections(); s.close(); }
    fs.rmSync(tmp, {recursive:true, force:true});
    clearTimeout(watchdog);
  }
})().catch(error => {
  clearTimeout(watchdog);
  if (activeChild) stopChild(activeChild);
  console.error(error);
  process.exit(1);
});
