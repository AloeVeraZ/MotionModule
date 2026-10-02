'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const timers = new Map();
let nextTimer = 0;
let lastDelay;
const context = vm.createContext({
  AbortController,
  setTimeout(callback, delay) { lastDelay = delay; timers.set(++nextTimer, callback); return nextTimer; },
  clearTimeout(id) { timers.delete(id); },
});
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), context);
const request = context.createJSONClient(100);
const abortError = () => Object.assign(new Error('aborted'), {name: 'AbortError'});
async function run() {
  context.fetch = async (url, options) => {
    assert.equal(options.cache, 'no-store');
    assert.equal(options.timeoutMs, undefined);
    assert.equal(options.headers['X-MotionModule-Token'], 'session');
    return {ok: true, json: async () => ({value: 4})};
  };
  assert.equal((await request('/status', {headers: {'X-MotionModule-Token': 'session'}})).value, 4);
  assert.equal(timers.size, 0);
  assert.equal(lastDelay, 100);
  await request('/scan', {timeoutMs: 35000, headers: {'X-MotionModule-Token': 'session'}});
  assert.equal(lastDelay, 35000, 'Slow network scans retain their longer timeout');
  assert.equal(timers.size, 0);
  context.fetch = async () => ({ok: false, status: 401, json: async () => ({error: 'Password needed', password_required: true})});
  await assert.rejects(request('/update'), error => error.status === 401 && error.data.password_required);
  assert.equal(timers.size, 0);
  for (const phase of ['headers', 'body']) {
    context.fetch = (_url, options) => {
      const blocked = () => new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => reject(abortError()), {once: true}));
      return phase === 'headers' ? blocked() : Promise.resolve({ok: true, json: blocked});
    };
    const waiting = request('/slow');
    await Promise.resolve();
    [...timers.values()][0]();
    await assert.rejects(waiting, error => error.name === 'AbortError');
    assert.equal(timers.size, 0, 'Timeouts are cleared after a stalled response');
  }
  const owner = new AbortController();
  context.fetch = (_url, options) => new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => reject(abortError()), {once:true}));
  const waiting = request('/cancelled', {signal: owner.signal});
  owner.abort();
  await assert.rejects(waiting, error => error.name === 'AbortError');
  assert.equal(timers.size, 0);
  console.log('JSON transport: success, errors, header/body timeouts and caller cancellation passed');
}
run().catch(error => { console.error(error); process.exitCode = 1; });
