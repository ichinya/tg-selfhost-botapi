'use strict';
const assert = require('node:assert/strict');
const {page, refusingPage} = require('./issue6_mock_transport.cjs');
async function main() {
  const privateHook = 'https://sink.test/private-hook?secret=synthetic-secret';
  const exportPage = page({mode:'hook-only',hook:privateHook});
  assert(!exportPage.plan().includes(privateHook), 'generated plan must not contain webhook secrets');
  const secretPage = page({oldHook:'https://legacy.test/hook?bot_token=SYNTHETIC_q',hook:'https://sink.test/private?intent=SYNTHETIC_q2'});
  await secretPage.run('executeInBrowser()');
  assert(!secretPage.elements.get('summaryBox').textContent.includes('SYNTHETIC_q'));
  assert(!secretPage.run('JSON.stringify(state.history)').includes('SYNTHETIC_q2'));
  assert(!secretPage.run('JSON.stringify(state.history)').includes('SYNTHETIC_q'));
  assert(secretPage.elements.get('summaryBox').textContent.includes('https://legacy.test'));
  secretPage.elements.get('webhookUrl').value = '';
  secretPage.elements.get('webhookUrl').events.input();
  assert(!secretPage.run('JSON.stringify(state.history)').includes('SYNTHETIC_q2'));
  let p = page({hook:'https://sink.test/hook'});
  await p.run('executeInBrowser()');
  assert.match(p.elements.get('summaryBox').textContent, /^SUCCESS/);
  assert.match(p.elements.get('summaryBox').textContent, /https:\/\/sink\.test\/…/);
  assert.equal(p.run('state.history[0].botId'), 123);

  for (const method of ['getWebhookInfo', 'getMe']) {
    p = refusingPage(method, 429, 600);
    await p.run('checkCurrentState()').catch(() => {});
    assert(p.run('state.guards.get("123")?.retryNotBefore') > Date.now(), `${method}: cooldown saved`);
    assert(!p.plan().includes('curl '));
    const n = p.calls.length;
    await p.run('checkCurrentState()').catch(() => {});
    assert.equal(p.calls.length, n, 'no re-request during cooldown');
  }
  p = page();
  p.run('state.busy = true; buildPlan()');
  assert(!p.elements.get('curlPlan').textContent.includes('\u043f\u0440\u0435\u0434\u044b\u0434\u0443\u0449\u0435\u0439 \u043e\u043f\u0435\u0440\u0430\u0446\u0438\u0438'));

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
  console.log('issue 6 result contract: 10 scenarios passed; 1 privacy scenario passed');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
