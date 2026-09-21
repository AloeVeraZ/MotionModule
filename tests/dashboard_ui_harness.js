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
    this.open = 'open' in this.attrs;
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
  showModal() {
    if (this.open) throw new Error('InvalidStateError: the dialog is already open');
    this.open = true;
  }
  close() {
    if (!this.open) return;
    this.open = false;
    this.fire('close');
  }
  setPointerCapture() {}
  get childElementCount() { return this.children.length; }
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

function telemetryData() {
  return {
    ok: true, configured: true, project: 'TestRobot',
    cameras: [
      {id: 'camera-1', name: 'Front', url: '/camera/front', connected: true, detail: 'Forward'},
      {id: 'camera-2', name: 'Rear', url: '/camera/rear', connected: true, detail: 'Rearward'},
    ],
    imu: {name: 'Pigeon', connected: true, calibrated: true, yaw: 91, pitch: 2, roll: -3, rate: 4},
    pi_gpio: {digital_only: true, available: [{bcm: 4, physical: 7}, {bcm: 5, physical: 29}]},
    pi_inputs: [
      {name: 'Limit', value: true, kind: 'digital', unit: '', channel: 'GPIO4', connected: true, status: 'ok', minimum: null, maximum: null},
    ],
    sensors: [],
    usb_controllers: [{
      id: 'giga:test', name: 'Arduino GIGA R1 WiFi', board_id: 'arduino_giga_r1_wifi', connected: true,
      serial: 'TESTGIGA', port: '/dev/ttyACM0', bridge: 'streaming', digital_pins: ['D0','D75'],
      analog_pins: ['A0','A7'], adc_bits: 12, detail: 'MotionModule sensor bridge is streaming',
      pins: [{name: 'Range', value: 250, kind: 'analog', unit: 'raw', channel: 'A0', connected: true, status: 'ok', minimum: 0, maximum: 4095}],
    }],
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
  const currentTelemetry = telemetryData();
  let timerId = 0;
  const context = vm.createContext({
    document, window, console, URLSearchParams, AbortController,
    Date: class extends Date { static now() { return now; } },
    performance: {now: () => now},
    location: {hash: '', pathname: fixture.kind === 'station' ? '/driver-station' : '/code', reload() {}},
    history: {replaceState() {}},
    navigator: {clipboard: {writeText: async () => {}}},
    localStorage: {getItem: () => null, setItem() {}},
    confirm: () => true,
    addEventListener: (...args) => window.addEventListener(...args),
    setInterval: (callback, delay) => { intervals.set(++timerId, {callback, delay}); return timerId; },
    clearInterval: id => intervals.delete(id),
    setTimeout: () => ++timerId,
    clearTimeout() {},
    fetch: async (url, options = {}) => {
      requests.push({url, ...options, payload: options.body ? JSON.parse(options.body) : undefined});
      const failure = failures.get(url);
      if (failure instanceof Error) throw failure;
      if (failure) return {ok: false, status: failure.status, json: async () => ({error: failure.message, ...failure.data})};
      const data = url === '/api/status' ? currentStatus
        : url === '/api/drive/telemetry' ? currentTelemetry
        : {ok: true};
      return {ok: true, status: 200, json: async () => data};
    },
  });
  const exports = fixture.kind === 'station'
    ? '\nglobalThis.dashboard = {refreshStatus, refreshTelemetry, sendDrive, stopAll};'
    : '\nglobalThis.dashboard = {selectTab, refreshStatus, refreshTelemetry, sendDrive, stopAll, installUpdate};';
  vm.runInContext(fixture.script + exports, context);
  const $ = selector => document.querySelector(selector);
  const driveEndpoint = fixture.kind === 'station' ? '/api/drive' : '/api/mecanum/test';
  const driveRequests = () => requests.filter(item => item.url === driveEndpoint);
  const settle = async () => { for (let index = 0; index < 12; index++) await Promise.resolve(); };
  async function arm() {
    await context.dashboard.refreshStatus();
    if (fixture.kind === 'station') {
      $('#armConfirm').checked = true;
      await $('#armConfirm').fire('change');
      await $('#enableButton').fire('click');
    } else {
      $('#driveEnable').checked = true;
      await $('#driveEnable').fire('change');
    }
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
  return {$, context, document, window, requests, failures, intervals, driveEndpoint, driveRequests, settle, arm, forward, releaseForward, setRobotStatus};
}

async function run(scenario) {
  const app = browser();
  await app.arm();
  await app.forward();
  assert(app.driveRequests().some(item => item.payload.forward === 1), 'Fixture must first demonstrate enabled motor control');

  if (scenario === 'station-drive-model') {
    assert.equal(app.driveRequests().at(-1).payload.drive_model, 'project');
    const selector = app.$('#useMecanumDrive');
    selector.checked = true;
    await selector.fire('change');
    await app.settle();
    assert.equal(app.$('#robotState').querySelector('strong').textContent, 'DISABLED');
    assert(app.requests.some(item => item.url === '/api/stop'), 'Changing mixers must stop first');
    const count = app.driveRequests().length;
    await app.context.dashboard.sendDrive();
    assert.equal(app.driveRequests().length, count, 'Changing mixers requires re-enabling');
    await app.arm();
    await app.forward();
    assert.equal(app.driveRequests().at(-1).payload.drive_model, 'mecanum');
    selector.checked = false;
    await selector.fire('change');
    await app.settle();
    await app.arm();
    await app.forward();
    assert.equal(app.driveRequests().at(-1).payload.drive_model, 'project');
  } else if (scenario === 'rotation-held') {
    await app.releaseForward();
    for (const [key, rotate] of [['q', 1], ['e', -1]]) {
      await app.window.fire('keydown', {key});
      await app.settle();
      for (let tick = 0; tick < 15; tick++) {
        await app.context.dashboard.sendDrive();
        const request = app.driveRequests().at(-1);
        assert.equal(request.url, app.driveEndpoint);
        assert.deepEqual(
          {forward: request.payload.forward, strafe: request.payload.strafe, rotate: request.payload.rotate},
          {forward: 0, strafe: 0, rotate},
          `${key.toUpperCase()} must continuously command pure rotation, not a nudge or strafe`,
        );
        assert(request.payload.speed > 0, 'Turning must retain the selected power');
      }
      await app.window.fire('keyup', {key});
      await app.settle();
      assert.equal(app.driveRequests().at(-1).payload.rotate, 0, 'Releasing the turn key stops rotation');
    }
  } else if (scenario === 'key-release-stop') {
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
    app.context.dashboard.selectTab('diagnostics', 'wiring');
    await app.settle();
    assert.equal(app.$('#driveEnable').checked, false, 'Leaving Mecanum Test must disarm its checkbox');
    assert(app.requests.some(item => item.url === '/api/stop'), 'Leaving Mecanum Test must request a stop');
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
    app.failures.set(app.driveEndpoint, {status: 403, message: 'Dashboard session expired'});
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
  } else if (scenario === 'station-telemetry-layout') {
    await app.context.dashboard.refreshTelemetry();
    await app.settle();
    const stage = app.$('#cameraStage');
    assert.equal(stage.querySelectorAll('[data-camera-id]').length, 2, 'Both declared cameras must render');
    assert(stage.classList.contains('dual'), 'Two cameras default to a split view');
    assert.equal(app.$('#cameraControls').querySelectorAll('button').length, 3, 'Operator can choose both or either camera');
    assert.equal(app.$('#piSensorList').querySelectorAll('.sensor-row').length, 1, 'Pi digital inputs have their own tray');
    assert.equal(app.$('#usbControllerList').querySelectorAll('.controller-card').length, 1, 'The GIGA has its own controller card');
    assert.equal(app.$('#usbControllerList').querySelectorAll('.sensor-row').length, 1, 'GIGA analog inputs render under the board');
    assert.match(app.$('#usbControllerSummary').textContent, /1 connected/);
    assert.match(app.$('#imuYaw').textContent, /91\.0/, 'IMU heading must be visible');
    await app.$('#cameraControls').querySelectorAll('button')[2].fire('click');
    assert(stage.classList.contains('single'), 'Choosing one camera expands it to a single square view');
    assert.equal(stage.querySelectorAll('[data-camera-id]').filter(frame => !frame.hidden).length, 1);
  } else if (scenario === 'update-password') {
    const line = {ref: 'testing', label: 'Testing line', current: true, action: 'Update now'};
    const dialog = app.$('#updatePasswordDialog');
    const input = app.$('#updatePassword');
    const posts = () => app.requests.filter(item => item.url === '/api/updates' && item.method === 'POST');
    const asking = {status: 401, message: 'This update needs the password sudo asks for on this Pi.',
      data: {password_required: true, rejected: false, user: 'aloe'}};

    await app.context.dashboard.installUpdate(line);
    await app.settle();
    assert.equal(dialog.open, false, 'No popup when sudo on the Pi needs no password');
    assert.deepEqual(posts().at(-1).payload, {ref: 'testing'});

    app.failures.set('/api/updates', asking);
    await app.context.dashboard.installUpdate(line);
    await app.settle();
    assert.equal(dialog.open, true, 'sudo asking for a password opens the popup');
    assert.equal(app.$('#updatePasswordUser').textContent, 'aloe');
    assert.equal(app.$('#updatePasswordError').hidden, true, 'Being asked is not an error');
    assert.equal(app.document.activeElement, input, 'The password box takes the focus');
    assert.equal(posts().at(-1).payload.password, undefined, 'Nothing is sent before a password is typed');

    app.failures.set('/api/updates', {status: 401, message: 'That password was not accepted. Try again.',
      data: {password_required: true, rejected: true, user: 'aloe'}});
    input.value = 'wrong-password';
    await app.$('#updatePasswordForm').fire('submit');
    await app.settle();
    assert.equal(posts().at(-1).payload.password, 'wrong-password');
    assert.equal(dialog.open, true, 'A wrong password keeps the popup open');
    assert.equal(app.$('#updatePasswordError').hidden, false);
    assert.match(app.$('#updatePasswordError').textContent, /not accepted/);
    assert.equal(input.value, '', 'A refused password is cleared');
    assert.equal(input.disabled, false, 'The box can be used again');

    app.failures.delete('/api/updates');
    input.value = 'right-password';
    await app.$('#updatePasswordForm').fire('submit');
    await app.settle();
    assert.deepEqual(posts().at(-1).payload, {ref: 'testing', password: 'right-password'});
    assert.equal(dialog.open, false, 'The popup closes once the update starts');
    assert.equal(input.value, '', 'The password is not left in the page');
    assert.match(app.$('#toast').textContent, /started/i);

    app.failures.set('/api/updates', asking);
    await app.context.dashboard.installUpdate(line);
    await app.settle();
    const sent = posts().length;
    await app.$('#updatePasswordCancel').fire('click');
    assert.equal(dialog.open, false, 'Cancel closes the popup');
    assert.equal(posts().length, sent, 'Cancelling sends nothing');
  } else {
    throw new Error(`Unknown scenario: ${scenario}`);
  }
}

run(process.argv[2]).catch(error => { console.error(error.stack); process.exitCode = 1; });
