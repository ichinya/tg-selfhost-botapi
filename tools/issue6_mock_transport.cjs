'use strict';
// Return API refusals before the fixture applies any remote effect.
const {page} = require('./issue10_ui_harness.cjs');
function refusingPage(method, code, retryAfter, options = {}) {
  return page({...options, refusal:{method, code, retryAfter}});
}
module.exports = {page, refusingPage};
