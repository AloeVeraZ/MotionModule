'use strict';

// Dependency-free DOM and transport fixtures. Production dashboard code runs
// unchanged in a VM; tests interact with its real controls and event handlers.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const fixture = JSON.parse(fs.readFileSync(0, 'utf8'));

class Element {
  constructor(spec = {tag: 'div', attrs: {}, text: ''}) {
    this.tagName = spec.tag.toUpperCase();
    this.attrs = {...spec.attrs};
    this.dataset = {};
    for (const [name, value] of Object.entries(this.attrs)) {
      if (name.startsWith('data-')) {
        this.dataset[name.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())] = value;
      }
    }
    this.hidden = 'hidden' in this.attrs;
    this.checked = 'checked' in this.attrs;
    this.disabled = 'disabled' in this.attrs;
    this.value = this.attrs.value || '';
    this.className = this.attrs.class || '';
    this.textContent = spec.text;
    this.style = {};
    this.children = [];
    this.events = new Map();
    this.classList = {
      contains: name => this.className.split(/\s+/).includes(name),
      toggle: (name, force) => {
        const names = new Set(this.className.split(/\s+/).filter(Boolean));
        const enabled = force === undefined ? !names.has(name) : force;
        enabled ? names.add(name) : names.delete(name);
        this.className = [...names].join(' ');
        return enabled;
      },
      add: (...names) => names.forEach(name => this.classList.toggle(name, true)),
      remove: (...names) => names.forEach(name => this.classList.toggle(name, false)),
    };
  }
  matches(selector) {
    if (selector === ':focus') return this.ownerDocument?.activeElement === this;
    const hiddenNegation = selector.endsWith(':not([hidden])');
    if (hiddenNegation) return !this.hidden && this.matches(selector.slice(0, -15));
    if (selector.startsWith('#')) return this.attrs.id === selector.slice(1);
    if (selector.startsWith('.')) return this.classList.contains(selector.slice(1));
    const attribute = selector.match(/^\[([^=\]]+)(?:=["']?([^"'\]]*)["']?)?\]$/);
    if (attribute) return attribute[1] in this.attrs && (attribute[2] === undefined || this.attrs[attribute[1]] === attribute[2]);
    return this.tagName.toLowerCase() === selector.toLowerCase();
  }
  querySelectorAll(selector) {
    const parts = selector.trim().split(/\s+(?=(?:[^"']*["'][^"']*["'])*[^"']*$)/);
    if (parts.length > 1) {
      return this.querySelectorAll(parts.shift()).flatMap(item => item.querySelectorAll(parts.join(' ')));
    }
    return this.children.flatMap(child => [
      ...(child.matches(selector) ? [child] : []),
      ...child.querySelectorAll(selector),
    ]);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest(selector) { return this.matches(selector) ? this : this.parentElement?.closest(selector) || null; }
  append(...children) {
    for (const child of children) {
      child.parentElement = this;
      child.ownerDocument = this.ownerDocument;
      this.children.push(child);
    }
  }
  replaceChildren(...children) { this.children = []; this.append(...children); }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  addEventListener(type, listener) {
    if (!this.events.has(type)) this.events.set(type, []);
    this.events.get(type).push(listener);
  }
  async fire(type, extra = {}) {
    const event = {target: this, currentTarget: this, preventDefault() {}, ...extra};
    await Promise.all((this.events.get(type) || []).map(listener => listener(event)));
  }
  focus() { this.ownerDocument.activeElement = this; }
  setPointerCapture() {}
}

function statusData() {
  return {
    ok: true,
    robot: {
      hardware: false, motors: {1: 0, 2: 0}, watchdog_ms: 500,
      watchdog_armed: false, watchdog_tripped: false,
      servo_boards: [], servo_commands: {}, servos: {}, servo_outputs: {},
    },
    system: {
      hostname: 'testrobot', active_project: 'TestRobot', version: 'test',
      temperature_c: null, uptime_seconds: 100, memory: {}, disk: {},
    },
  };
}

function browser(now = 1700000000000) {
  const document = new Element({tag: 'document', attrs: {}, text: ''});
  document.ownerDocument = document;
  document.hidden = false;
  document.hasFocus = () => true;
  const nodes = fixture.nodes.map(spec => new Element(spec));
  fixture.nodes.forEach((spec, index) => {
    (spec.parent === null ? document : nodes[spec.parent]).append(nodes[index]);
    nodes[index].ownerDocument = document;
  });
  document.documentElement = document.querySelector('html');
  document.body = document.querySelector('body');
  document.activeElement = document.querySelector('body');
  document.createElement = tag => new Element({tag, attrs: {}, text: ''});
  document.createTextNode = text => new Element({tag: '#text', attrs: {}, text: String(text)});
  const window = new Element();
  const requests = [];
  const failures = new Map();
  const intervals = new Map();
  const currentStatus = statusData();
  let timerId = 0;
  const context = vm.createContext({
    document, window, console, URLSearchParams, AbortController,
    Date: class extends Date { static now() { return now; } },
    performance: {now: () => now},
    location: {hash: '', pathname: '/code', reload() {}},
    history: {replaceState() {}},
    navigator: {clipboard: {writeText: async () => {}}},
    localStorage: {getItem: () => null, setItem() {}},
    addEventListener: (...args) => window.addEventListener(...args),
    setInterval: (callback, delay) => { intervals.set(++timerId, {callback, delay}); return timerId; },
    clearInterval: id => intervals.delete(id),
    setTimeout: () => ++timerId,
    clearTimeout() {},
    fetch: async (url, options = {}) => {
      requests.push({url, ...options, payload: options.body ? JSON.parse(options.body) : undefined});
      const failure = failures.get(url);
      if (failure instanceof Error) throw failure;
      if (failure) return {ok: false, status: failure.status, json: async () => ({error: failure.message})};
      const data = url === '/api/status' ? currentStatus : {ok: true};
      return {ok: true, status: 200, json: async () => data};
    },
  });
  vm.runInContext(fixture.script + '\nglobalThis.dashboard = {selectTab, refreshStatus, sendDrive, stopAll};', context);
  const $ = selector => document.querySelector(selector);
  const driveRequests = () => requests.filter(item => item.url === '/api/drive');
  const settle = async () => { for (let index = 0; index < 12; index++) await Promise.resolve(); };
  async function arm() {
    await context.dashboard.refreshStatus();
    $('#driveEnable').checked = true;
    await $('#driveEnable').fire('change');
    document.activeElement = $('body');
  }
  async function forward(extra = {}) {
    await window.fire('keydown', {key: 'w', ...extra});
    await settle();
  }
  async function releaseForward(extra = {}) {
    await window.fire('keyup', {key: 'w', ...extra});
    await settle();
  }
  function setRobotStatus(patch) { Object.assign(currentStatus.robot, patch); }
  return {$, context, document, window, requests, failures, intervals, driveRequests, settle, arm, forward, releaseForward, setRobotStatus};
}

async function run(scenario) {
  const app = browser();
  await app.arm();
  await app.forward();
  assert(app.driveRequests().some(item => item.payload.forward === 1), 'Fixture must first demonstrate enabled motor control');

  if (scenario === 'key-release-stop') {
    await app.releaseForward();
    const last = app.driveRequests().at(-1).payload;
    assert.deepEqual(
      {forward: last.forward, strafe: last.strafe, rotate: last.rotate},
      {forward: 0, strafe: 0, rotate: 0},
      'Releasing W must send an immediate zero command instead of waiting for the watchdog',
    );
  } else if (scenario === 'servo-offline') {
    app.setRobotStatus({
      hardware: true,
      servo_boards: [{index: 0, address: '0x40', available: false, error: 'Remote I/O error', fault: null}],
    });
    await app.context.dashboard.refreshStatus();
    assert(app.$('#servoStat').classList.contains('alert-bad'), 'A missing physical servo board must be red');
    assert.match(app.$('#servoNote').textContent, /not answering/i);
    assert.equal(app.$('#servoBusNotice').hidden, false);
    assert(app.$('#servoBusNotice').classList.contains('danger'));
  } else if (scenario === 'servo-command-fault') {
    app.setRobotStatus({
      hardware: true,
      servo_boards: [{index: 0, address: '0x40', available: true, error: null, fault: 'Remote I/O error'}],
    });
    await app.context.dashboard.refreshStatus();
    assert(app.$('#servoStat').classList.contains('alert-warn'), 'A board rejecting commands must be yellow');
    assert.match(app.$('#servoNote').textContent, /refusing commands/i);
    assert(app.$('#servoSummary').querySelector('.warn'));
  } else if (scenario === 'tab-disarm') {
    app.document.hidden = true;
    await app.document.fire('visibilitychange');
    await app.settle();
    assert.equal(app.$('#driveEnable').checked, false, 'Leaving Drive must disarm its checkbox');
    assert(app.requests.some(item => item.url === '/api/stop'), 'Leaving Drive must request a stop');
    const count = app.driveRequests().length;
    await app.forward({repeat: true});
    await app.context.dashboard.sendDrive();
    assert.equal(app.driveRequests().length, count, 'Hidden Drive controls must not send new commands');
  } else if (scenario === 'stop-disarm') {
    await app.$('[data-stop]').fire('click');
    await app.settle();
    assert.equal(app.$('#driveEnable').checked, false, 'Stop must disarm keyboard control');
    assert(app.requests.some(item => item.url === '/api/stop'), 'Stop must reach the server');
    const count = app.driveRequests().length;
    await app.forward({repeat: true});
    await app.context.dashboard.sendDrive();
    assert.equal(app.driveRequests().length, count, 'Held-key repeat after Stop must not restart motors');
  } else if (scenario === 'connection-error') {
    app.failures.set('/api/status', new Error('Robot connection lost'));
    await app.context.dashboard.refreshStatus();
    await app.settle();
    assert.equal(app.$('#driveEnable').checked, false, 'Connection loss must disarm');
    assert.match(app.$('#safetyPill').textContent, /unknown|unavailable|disconnected/i, 'Stale idle/safe state must be replaced');
    assert(!app.$('#signalOutputs').classList.contains('good'), 'Unknown output state cannot show a green good signal');
    app.failures.delete('/api/status');
    await app.context.dashboard.refreshStatus();
    assert.equal(app.$('#driveEnable').checked, false, 'Reconnection must require deliberate rearming');
    const count = app.driveRequests().length;
    await app.context.dashboard.sendDrive();
    assert.equal(app.driveRequests().length, count);
  } else if (scenario === 'drive-error') {
    app.failures.set('/api/drive', {status: 403, message: 'Dashboard session expired'});
    await app.context.dashboard.sendDrive();
    await app.settle();
    assert.equal(app.$('#driveEnable').checked, false, 'Rejected drive commands must disarm');
    assert.match(app.$('#toast').textContent, /expired|failed|error|reconnect|session/i, 'Command rejection must be visible');
  } else if (scenario === 'reload-sequence') {
    for (let index = 0; index < 30; index++) await app.context.dashboard.sendDrive();
    const previous = app.driveRequests().at(-1).payload.sequence;
    const reloaded = browser(1700000001000);
    await reloaded.arm();
    await reloaded.forward();
    const next = reloaded.driveRequests().at(-1).payload.sequence;
    assert(Number.isSafeInteger(next), 'Sequence must retain integer precision');
    assert(next > previous, 'A reloaded page must not restart its sequence below the server watermark');
  } else {
    throw new Error(`Unknown scenario: ${scenario}`);
  }
}

run(process.argv[2]).catch(error => { console.error(error.stack); process.exitCode = 1; });
