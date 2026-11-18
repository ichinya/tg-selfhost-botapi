/* Install before Check/Execute: const mock = htmlMigratorMock.create([...]);
 * globalThis.fetch = mock.fetch; No request is forwarded to a real fetch.
 */
(function (root) {
  function response(value, status = 200) {
    return {status, ok: status >= 200 && status < 300,
      text: async () => typeof value === 'string' ? value : JSON.stringify(value)};
  }
  function deferred() {
    let resolve, reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    return {promise, resolve, reject};
  }
  function create(replies = []) {
    const pending = [...replies], calls = [], nonApiCalls = [], violations = [], effects = [];
    function violation(message) { violations.push(message); throw new Error(message); }
    async function fetch(url, options = {}) {
      const parsed = new URL(url);
      if (options.method === 'HEAD') {
        nonApiCalls.push({url, method: 'HEAD', nonApi: true});
        return response('', 204);
      }
      const match = parsed.pathname.match(/^(.*)\/bot([^/]+)\/([^/]+)$/);
      if (!match) return violation('Unexpected non-API fetch');
      const call = {method: match[3], endpoint: parsed.origin + match[1], token: match[2],
        httpMethod: options.method || 'GET', body: options.body || '', signal: options.signal};
      calls.push(call);
      if (!pending.length) return violation('Unexpected API fetch: ' + call.method);
      const next = pending.shift();
      if (next instanceof Error) throw next;
      const item = typeof next === 'function' ? await next(call) : next;
      if (item === null || typeof item !== 'object') return response(item);
      if (item.method && item.method !== call.method) return violation('Unexpected method: ' + call.method);
      if (item.endpoint && item.endpoint !== call.endpoint) return violation('Unexpected endpoint: ' + call.endpoint);
      if (item.expectedBody !== undefined && item.expectedBody !== call.body) return violation('Unexpected body for ' + call.method);
      if (item.effect) { effects.push({method: call.method, endpoint: call.endpoint}); item.effect(call); }
      if (item.error) throw item.error;
      if (item.wait) return item.wait.promise;
      if (item.bodyWait) return {status: 200, ok: true, text: () => item.bodyWait.promise};
      return response(item.body === undefined ? item : item.body, item.status === undefined ? 200 : item.status);
    }
    return {fetch, calls, nonApiCalls, violations, effects, pending};
  }
  const api = {create, response, deferred};
  root.htmlMigratorMock = api;
  if (typeof module !== 'undefined') module.exports = api;
})(globalThis);

// Closed helper-route fixture for module-based clients; no arbitrary proxy.
module.exports.helperResponse = function(route, value) {
  if (!/^\/api\/(hello|session|plan|apply|resume|refresh|reconcile|status\?operation=[A-Za-z0-9_-]+|export\?operation=[A-Za-z0-9_-]+)$/.test(route)) {
    throw new Error('non-helper request rejected');
  }
  return {ok: true, json: async () => value};
};
