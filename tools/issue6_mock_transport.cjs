'use strict';
// Wrap the existing network-isolated page fixture with a deterministic API refusal.
const {page} = require('./issue10_ui_harness.cjs');
function refusingPage(method, code, retryAfter, options = {}) {
  const p = page(options);
  p.run(`{
    const originalFetch = fetch;
    fetch = async (url, request) => {
      const response = await originalFetch(url, request);
      if (new URL(url).pathname.endsWith('/' + ${JSON.stringify(method)})) {
        return {ok:false, status:${code}, text:async () => JSON.stringify({ok:false,error_code:${code},parameters:{retry_after:${JSON.stringify(retryAfter)}}})};
      }
      return response;
    };
  }`);
  return p;
}
module.exports = {page, refusingPage};
