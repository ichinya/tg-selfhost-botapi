'use strict';
const assert = require('node:assert/strict');
const {page, refusingPage} = require('./issue6_mock_transport.cjs');
async function main() {
  let p = page({hook:'https://sink.test/hook'});
  await p.run('executeInBrowser()');
  assert.match(p.elements.get('summaryBox').textContent, /^SUCCESS/);
  assert.match(p.elements.get('summaryBox').textContent, /https:\/\/sink\.test\/hook/);
  assert.equal(p.run('state.history[0].botId'), 123);

  p = refusingPage('deleteWebhook', 429, 600);
  await p.run('executeInBrowser()');
  assert.match(p.elements.get('summaryBox').textContent, /^ERROR/);
  assert(!p.calls.some(c => c.method === 'logOut'));
  assert(p.run('state.guards.get("123").retryNotBefore > Date.now()'));
  assert(!p.plan().includes('curl '));

  p = refusingPage('logOut', 429, 600);
  await p.run('executeInBrowser()');
  assert.match(p.elements.get('summaryBox').textContent, /^PARTIAL/);
  assert(!p.calls.some(c => c.role === 'target' && c.method !== 'probe'));
  const before = p.calls.length; await p.run('executeInBrowser()'); assert.equal(p.calls.length, before);

  p = page({fail:'source:logOut',failure:'lost'});
  await p.run('executeInBrowser()');
  assert.match(p.elements.get('summaryBox').textContent, /^UNKNOWN/);
  assert(!p.calls.some(c => c.role === 'target' && c.method !== 'probe'));

  p = refusingPage('setWebhook', 400, null, {mode:'hook-only',hook:'https://sink.test/hook'});
  await p.run('executeInBrowser()');
  assert.match(p.elements.get('summaryBox').textContent, /^ERROR/);
  assert.equal(p.calls.filter(c => c.method === 'getWebhookInfo').length, 1);

  p = refusingPage('deleteWebhook', 429, '600');
  await p.run('executeInBrowser()');
  assert.equal(p.run('state.guards.get("123")?.retryNotBefore ?? null'), null);
  assert(!p.calls.some(c => c.method === 'logOut'));

  p = page({hook:'https://sink.test/hook'});
  p.run(`{
    const originalFetch = fetch;
    fetch = async (url, request) => {
      const response = await originalFetch(url, request);
      if (url.includes('target.test') && url.endsWith('/getMe'))
        return {ok:true,status:200,text:async () => JSON.stringify({ok:true,result:{id:456}})};
      return response;
    };
  }`);
  await p.run('executeInBrowser()');
  assert.match(p.elements.get('summaryBox').textContent, /^PARTIAL/);
  assert(!p.calls.some(c => c.method === 'setWebhook'));

  p = page({hook:'https://sink.test/hook'});
  await Promise.all([p.run('executeInBrowser()'), p.run('executeInBrowser()'), p.run('checkCurrentState()')]);
  assert.equal(p.calls.filter(c => c.method === 'logOut').length, 1);

  p = page({mismatch:true,hook:'https://sink.test/hook'});
  await p.run('executeInBrowser()');
  assert.match(p.elements.get('summaryBox').textContent, /^PARTIAL/);
  assert.match(p.elements.get('summaryBox').textContent, /https:\/\/other\.test\//);
  p.elements.get('botToken').value = '456:another_synthetic_token_only';
  p.run('invalidate()'); assert(!p.run('blocked(currentConfig())'));
  p.elements.get('botToken').value = '123:rotated_synthetic_token_only';
  p.run('invalidate()'); assert(p.run('blocked(currentConfig())'));
  p.elements.get('botToken').value = '00123:rotated_synthetic_token_only';
  p.run('invalidate()'); assert(p.run('blocked(currentConfig())'));
  console.log('issue 6 result contract: 9 scenarios passed');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
