import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createClient} from '../assets/js/migration-client.mjs';

const digest = 'a'.repeat(64);
const location = {protocol: 'http:', hostname: '127.0.0.1'};
const reply = value => ({ok: true, json: async () => value});
function fixture() {
  const calls = [], renders = [], stored = new Map();
  let effects = 0;
  const fetcher = async (route, options) => {
    calls.push([route, options]);
    if (route === '/api/hello') return reply({protocol: 'migration-helper-v1', authenticated: false});
    if (route === '/api/session') return reply({csrf: 'session-private'});
    if (route === '/api/plan') return reply({operation_id: JSON.parse(options.body).operation_id, digest, steps: {}});
    if (route === '/api/apply') { effects++; throw Error('lost UI response'); }
    if (route.startsWith('/api/status?operation=')) return reply({operation_id: route.split('=')[1], digest, steps: {target_configure: 'confirmed'}});
    throw Error('Unexpected route');
  };
  const client = createClient({fetcher, render: value => renders.push(value),
    storage: {setItem: (k,v) => stored.set(k,v), getItem: k => stored.get(k)}});
  return {client, calls, renders, stored, effects: () => effects};
}

test('Pages/file origins never fetch, and loopback still requires a valid handshake', async () => {
  const f = fixture();
  assert.equal(await f.client.handshake({protocol: 'https:', hostname: 'example.github.io'}), false);
  assert.equal(await f.client.handshake({protocol: 'file:', hostname: ''}), false);
  assert.equal(f.calls.length, 0);
  const client = createClient({fetcher: async () => reply({protocol: 'another-service'})});
  assert.equal(await client.handshake(location), false);
});

test('lost apply response reads same status; storage contains only a locator', async () => {
  const f = fixture();
  await f.client.handshake(location);
  await f.client.login('bootstrap-private');
  await f.client.plan({token: '123:canary_private', source: 'https://canary.example/private'});
  await f.client.write('apply');
  assert.equal(f.effects(), 1);
  assert.equal(f.renders.at(-1).steps.target_configure, 'confirmed');
  assert.equal(f.calls.filter(([route]) => route === '/api/plan').length, 1);
  const stored = [...f.stored.values()].join();
  assert.deepEqual(Object.keys(JSON.parse(stored)).sort(), ['digest', 'operation_id']);
  assert(!stored.includes('private'));
  assert(!JSON.stringify(f.renders).includes('canary'));
  await f.client.restore();
  assert.equal(f.effects(), 1);
  assert.equal(f.calls.filter(([route]) => route === '/api/plan').length, 1);
});

test('late plan responses cannot overwrite a newer draft', async () => {
  const f = fixture();
  await f.client.handshake(location);
  await f.client.login('code');
  const pending = f.client.plan({token: 'private'});
  f.client.invalidate();
  assert.equal(await pending, null);
  assert.equal(f.client.active, null);
  assert.equal(f.renders.length, 0);
});

test('HTML keeps one allowlisted module and client renders as text, without direct Bot API calls', () => {
  const html = fs.readFileSync(new URL('./migration_executor.html', import.meta.url), 'utf8');
  const client = fs.readFileSync(new URL('../assets/js/migration-client.mjs', import.meta.url), 'utf8');
  assert.equal((html.match(/<script\b/g) || []).length, 1);
  assert.match(html, /<script type="module" src="assets\/js\/migration-client\.mjs"><\/script>/);
  for (const id of ['runtime-form', 'session', 'workspace', 'plan', 'confirm-digest', 'result'])
    assert.match(html, new RegExp(`id="${id}"`));
  assert(!/\bon(?:submit|click|load|error)=/i.test(html));
  assert(!/innerHTML|outerHTML|localStorage|console\./.test(client));
  assert(!/buildCommands|executeInBrowser|\/bot\$|getMe|deleteWebhook|logOut|setWebhook/.test(client));
  assert.match(client, /textContent/);
  assert(!html.startsWith('---'));
});
