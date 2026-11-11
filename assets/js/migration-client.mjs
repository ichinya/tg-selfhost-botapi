// Same-origin presentation adapter. All sequencing and recovery live in Python.
const ID = /^[A-Za-z0-9_-]{1,128}$/;
const DIGEST = /^[a-f0-9]{64}$/;
const KEY = 'migration-operation-v1';
const WRITES = new Set(['plan', 'apply', 'resume', 'refresh', 'reconcile']);

export function createClient({fetcher = globalThis.fetch, storage, render = () => {}} = {}) {
  let csrf = '', active = null, generation = 0, ready = false;
  function show(value, ticket) { if (ticket === generation) render(value); }
  async function request(path, body) {
    const response = await fetcher(path, {method: body ? 'POST' : 'GET', credentials: 'same-origin',
      redirect: 'error', cache: 'no-store', headers: body ? {'Content-Type': 'application/json', 'X-CSRF-Token': csrf} : {},
      ...(body ? {body: JSON.stringify(body)} : {})});
    const result = await response.json();
    if (!response.ok) throw Error(result.reason || 'helper_request_failed');
    return result;
  }
  function remember(value) {
    if (!ID.test(value.operation_id) || !DIGEST.test(value.digest)) throw Error('invalid_operation_locator');
    active = {operation_id: value.operation_id, digest: value.digest};
    try { storage?.setItem(KEY, JSON.stringify(active)); } catch { /* storage may be unavailable */ }
  }
  return {
    invalidate() { generation++; },
    get active() { return active ? {...active} : null; },
    async handshake(location) {
      if (location.protocol !== 'http:' || location.hostname !== '127.0.0.1') return false;
      try {
        const hello = await request('/api/hello');
        ready = hello.protocol === 'migration-helper-v1';
        if (ready && hello.authenticated) csrf = (await request('/api/session')).csrf;
        return ready;
      } catch { return false; }
    },
    async login(code) {
      if (!ready) throw Error('helper_required');
      csrf = (await request('/api/session', {code})).csrf;
    },
    async restore() {
      let locator;
      try { locator = JSON.parse(storage?.getItem(KEY) || 'null'); } catch { return null; }
      if (!locator || !ID.test(locator.operation_id) || !DIGEST.test(locator.digest)) return null;
      const ticket = generation;
      const result = await request('/api/status?operation=' + encodeURIComponent(locator.operation_id));
      if (ticket !== generation) return null;
      if (result.digest !== locator.digest) throw Error('saved_locator_mismatch');
      active = locator;
      show(result, ticket);
      return result;
    },
    async status() {
      if (!active || !csrf) throw Error('session_and_operation_required');
      const ticket = generation, locator = {...active};
      const result = await request('/api/status?operation=' + encodeURIComponent(locator.operation_id));
      if (result.digest !== locator.digest) throw Error('operation_digest_mismatch');
      show(result, ticket);
      return result;
    },
    async plan(runtime, options = {}) {
      if (!csrf) throw Error('session_required');
      const ticket = ++generation;
      const operation_id = globalThis.crypto.randomUUID();
      const result = await request('/api/plan', {operation_id, runtime, ...options});
      if (ticket !== generation) return null;
      remember(result);
      show(result, ticket);
      return result;
    },
    async write(action, inputs = {}) {
      if (!WRITES.has(action) || action === 'plan' || !active || !csrf) throw Error('invalid_operation_action');
      const ticket = generation, locator = {...active};
      try {
        return await request('/api/' + action, {...inputs, ...locator});
      } catch {
        show({notice: 'UI_RESPONSE_UNKNOWN: read status of this operation before continuing.'}, ticket);
        // A lost UI response cannot rewrite the engine outcome or start another plan.
        try {
          const state = await request('/api/status?operation=' + encodeURIComponent(locator.operation_id));
          if (state.digest !== locator.digest) throw Error('digest_mismatch');
          show(state, ticket);
        } catch {
          show({notice: 'UI_RESPONSE_UNKNOWN: helper unavailable; retain operation ID and read status after restart.', ...locator}, ticket);
        }
        return {ui_response_unknown: true};
      }
    },
    async export() {
      if (!active || !csrf) throw Error('session_and_operation_required');
      return request('/api/export?operation=' + encodeURIComponent(active.operation_id));
    }
  };
}

export async function boot(document, location, dependencies = {}) {
  const $ = id => document.getElementById(id);
  if (!$('runtime-form')) return;
  let draftChanged = true, busy = false;
  const client = createClient({...dependencies, storage: dependencies.storage ?? globalThis.sessionStorage,
    render: state => { $('result').textContent = JSON.stringify(state, null, 2); }});
  const message = text => { $('notice').textContent = text; };
  const json = id => $(id).value.trim() ? JSON.parse($(id).value) : undefined;
  const runtime = () => {
    const action = $('action').value;
    if (!action) throw Error('Choose an explicit delivery action / Выберите действие');
    const profile = action === 'polling' || $('scope').value === 'polling' ? {mode: 'polling'} :
      {mode: $('scope').value, url: $('webhook').value, ...(json('profile') || {})};
    return {source: $('source').value, target: $('target').value, token: $('token').value, profile,
      action, drop: $('drop').checked, direction: $('direction').value, local_mode: $('local-mode').value === 'true',
      queue_ack: $('queue-ack').checked, cloud_not_before: $('cooldown').value ? Number($('cooldown').value) : null};
  };
  const receipts = () => ({quiescence: json('quiescence'), endpoint_change: json('endpoint-change'),
    application_start: json('application-start'), state_transfer: json('state-transfer')});
  const guarded = fn => async () => {
    if (busy) return;
    busy = true;
    try { await fn(); } catch (error) { message(error instanceof SyntaxError ? 'Invalid private JSON / Ошибка JSON' : error.message); }
    finally { busy = false; }
  };
  $('runtime-form').addEventListener('submit', event => event.preventDefault());
  $('runtime-form').addEventListener('input', () => { draftChanged = true; client.invalidate(); message('Draft changed; create a new plan before apply. / Изменены входы: нужен новый план.'); });
  $('login').addEventListener('click', guarded(async () => {
    await client.login($('session-code').value);
    $('session-code').value = '';
    $('workspace').hidden = false;
    await client.restore();
    message('Session ready / Сессия готова');
  }));
  $('plan').addEventListener('click', guarded(async () => {
    const result = await client.plan(runtime(), {ack_url_only: $('ack-scope').checked, quiescence: json('quiescence')});
    if (result) draftChanged = false;
  }));
  for (const action of ['apply', 'resume', 'refresh', 'reconcile']) {
    $(action).addEventListener('click', guarded(async () => {
      if (draftChanged && action === 'apply') throw Error('Review a new sealed plan / Создайте и проверьте план');
      if (!client.active || $('confirm-digest').value !== client.active.digest) throw Error('Enter the reviewed digest / Введите проверенный digest');
      await client.write(action, {runtime: runtime(), ...receipts(), ...(action === 'reconcile' ? json('evidence') || {} : {})});
      const until = Date.now() + 30000;
      let status;
      do {
        status = await client.status();
        if (!status.job?.running) break;
        await new Promise(resolve => setTimeout(resolve, 1000));
      } while (Date.now() < until);
      message(status.job?.running ? 'Job running; read status / Задача выполняется: читайте status' : 'Read individual outcomes / Проверьте итоги каждого этапа');
    }));
  }
  $('status').addEventListener('click', guarded(async () => { await client.status(); }));
  $('export').addEventListener('click', guarded(async () => {
    $('export-result').textContent = JSON.stringify(await client.export(), null, 2);
  }));
  const available = await client.handshake(location);
  $('session').hidden = !available;
  $('entry').hidden = available;
  if (available) {
    try { if (await client.restore()) { $('workspace').hidden = false; message('Saved operation loaded / Загружена прежняя операция'); } } catch { /* session bootstrap is required */ }
  }
  return client;
}

if (typeof document !== 'undefined') boot(document, globalThis.location);
