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
    const event = {target: this, currentTarget: this, preventDefault() {}, stopPropagation() {}, ...extra};
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
  // Tests give an element a size by setting rect; everything else is empty.
  getBoundingClientRect() {
    const {left = 0, top = 0, width = 0, height = 0} = this.rect || {};
    return {left, top, width, height, right: left + width, bottom: top + height};
  }
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
    ? '\nglobalThis.dashboard = {refreshStatus, refreshTelemetry, sendDrive, stopAll, readPad};'
    : '\nglobalThis.dashboard = {selectTab, refreshStatus, sendDrive, stopAll, installUpdate, renderDriveTest};';
  vm.runInContext(fixture.script + exports, context);
  const $ = selector => document.querySelector(selector);
  const driveEndpoint = fixture.kind === 'station' ? '/api/drive' : '/api/drive/test';
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
  function setTelemetry(patch) { Object.assign(currentTelemetry, patch); }
  // One on-screen stick on a 200px pad. A round stick travels 40px each way;
  // a one-way stick's track travels 56px along its length.
  function stick(side) {
    const pad = $(`#${side}StickPad`);
    const sizes = {xy: [120, 120], x: [152, 56], y: [56, 152]};
    const [width, height] = sizes[pad.dataset.axes] || [0, 0];
    pad.rect = {left: 0, top: 0, width: 200, height: 200};
    pad.querySelector('.stick-base').rect = {width, height};
    pad.querySelector('.stick-knob').rect = {width: 40, height: 40};
    const send = async (type, pointerId, clientX = 0, clientY = 0) => {
      await pad.fire(type, {pointerId, pointerType: 'touch', button: 0, clientX, clientY});
      await settle();
    };
    return {
      pad,
      down: (id, x, y) => send('pointerdown', id, x, y),
      move: (id, x, y) => send('pointermove', id, x, y),
      up: id => send('pointerup', id),
    };
  }
  const motion = payload => ({forward: payload.forward, strafe: payload.strafe, rotate: payload.rotate});
  return {$, context, document, window, requests, failures, intervals, driveEndpoint, driveRequests, settle, arm, forward, releaseForward, setRobotStatus, setTelemetry, stick, motion};
}

async function run(scenario) {
  const app = browser();
  await app.arm();
  await app.forward();
  assert(app.driveRequests().some(item => item.payload.forward === 1), 'Fixture must first demonstrate enabled motor control');

  if (scenario === 'custom-servo') {
    vm.runInContext(`configData = {servos: {profiles: [{id: 'custom_position', label: 'Custom', kind: 'position', step: 0.1, unit: '°', minimum_pulse_us: 500, maximum_pulse_us: 2500}]}}`, app.context);
    app.$('#servoProfile').value = 'custom_position';
    await app.$('#servoProfile').fire('change');
    assert.equal(app.$('#servoCustomRange').hidden, false);
    app.$('#servoCustomMin').value = '-90';
    app.$('#servoCustomMax').value = '90';
    await app.$('#servoCustomMin').fire('input');
    assert.equal(Number(app.$('#servoValue').min), -90);
    assert.equal(Number(app.$('#servoValue').max), 90);
    assert.equal(Number(app.$('#servoValue').value), 0);
    assert.equal(app.requests.filter(r => r.url === '/api/servos/set').length, 0);
    app.$('#servoSafe').checked = true;
    app.$('#servoValue').value = '45';
    await app.$('#servoSet').fire('click');
    await app.settle();
    const command = app.requests.find(r => r.url === '/api/servos/set').payload;
    assert.deepEqual(command.custom_range, {minimum: -90, maximum: 90});
    assert.equal(command.value, 45);
    app.$('#servoCustomMin').value = '100';
    await app.$('#servoCustomMin').fire('input');
    assert.equal(app.$('#servoValue').disabled, true);
    assert.equal(app.$('#servoSafe').checked, false);
    await app.$('#servoSet').fire('click');
    assert.equal(app.requests.filter(r => r.url === '/api/servos/set').length, 1);
  } else if (scenario === 'touch-drive' || scenario === 'touch-stop') {
    await app.releaseForward();
    const grid = app.$(fixture.kind === 'station' ? '#keyGrid' : '#driveKeys');
    if (fixture.kind === 'station') vm.runInContext('renderKeys()', app.context);
    const buttons = grid.querySelectorAll('button');
    const forward = buttons.find(button => button.dataset.action === 'forward');
    const turn = buttons.find(button => ['turnLeft', 'turn_left'].includes(button.dataset.action));
    const stop = buttons.find(button => button.dataset.action === 'stop');
    const down = (button, id) => button.fire('pointerdown', {pointerId:id, pointerType:'touch', button:0});
    await down(forward, 1); await app.settle();
    assert.equal(app.driveRequests().at(-1).payload.forward, 1);
    if (scenario === 'touch-drive') {
      await down(turn, 2); await app.settle();
      assert.equal(app.driveRequests().at(-1).payload.rotate, 1);
      assert.equal(app.driveRequests().at(-1).payload.forward, 1);
      await turn.fire('pointercancel', {pointerId:2}); await app.settle();
      assert.equal(app.driveRequests().at(-1).payload.rotate, 0);
      assert.equal(app.driveRequests().at(-1).payload.forward, 1);
      await down(forward, 3);
      await forward.fire('pointerup', {pointerId:1}); await app.settle();
      assert.equal(app.driveRequests().at(-1).payload.forward, 1, 'Second finger still holds forward');
      await forward.fire('lostpointercapture', {pointerId:3}); await app.settle();
      assert.equal(app.driveRequests().at(-1).payload.forward, 0, 'Lost capture immediately clears movement');
    } else {
      await down(stop, 2); await app.settle();
      const count = app.driveRequests().length;
      await down(turn, 3);
      await forward.fire('pointerup', {pointerId:1}); await app.settle();
      assert.equal(app.driveRequests().length, count, 'No motion after Stop until rearmed');
      await app.arm(); await app.context.dashboard.sendDrive(); await app.settle();
      assert.equal(app.driveRequests().at(-1).payload.forward, 0, 'Rearming does not revive an old finger');
      assert.equal(app.driveRequests().at(-1).payload.rotate, 0);
    }
  } else if (scenario === 'drive-test-load-error') {
    vm.runInContext("configData = {drive_test: {source: '/robots/MyRobot/test.py', error: 'test.py could not be loaded'}}; dashboard.renderDriveTest(configData.drive_test);", app.context);
    await app.settle();
    assert.match(app.$('#driveTestSource').textContent, /could not be loaded/);
    assert.equal(app.$('#driveEnable').disabled, true);
    assert.equal(app.$('#driveEnable').checked, false);
    await app.context.dashboard.refreshStatus();
    assert.equal(app.$('#driveEnable').disabled, true, 'Status polling must not re-enable a broken hook');
    const count = app.driveRequests().length;
    await app.forward();
    await app.context.dashboard.sendDrive();
    assert.equal(app.driveRequests().length, count);
    app.context.dashboard.renderDriveTest({source: '/robots/MyRobot/test.py', error: ''});
    assert.match(app.$('#driveTestSource').textContent, /MyRobot\/test.py/);
  } else if (scenario === 'station-drive-model') {
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
  } else if (scenario === 'station-touch-sticks') {
    await app.releaseForward();
    const html = app.document.documentElement;
    const tick = async () => {
      await app.context.dashboard.sendDrive();
      await app.settle();
      return app.motion(app.driveRequests().at(-1).payload);
    };
    assert.equal(html.dataset.input, 'keys', 'A computer starts with the keys');
    assert.equal(app.$('[data-touch-panel="imu"]').hidden, false, 'A computer shows every panel');
    // The first touch anywhere brings up the sticks and the touchscreen layout.
    await app.window.fire('pointerdown', {pointerType: 'touch', pointerId: 90});
    assert.equal(html.dataset.input, 'touch');
    for (const panel of ['status', 'mechanisms', 'imu', 'pi_inputs', 'usb_controllers']) {
      assert.equal(app.$(`[data-touch-panel="${panel}"]`).hidden, true, `A touchscreen leaves out ${panel}`);
    }
    assert.equal(app.$('.right-column').hidden, true, 'An empty column folds away');
    assert.equal(app.$('#controllerSummary').textContent, 'Touch sticks');
    const left = app.stick('left');
    const right = app.stick('right');
    assert.equal(left.pad.dataset.axes, 'xy', 'The drive stick moves all the way round');
    assert.equal(right.pad.dataset.axes, 'x', 'The turning stick only goes left and right');

    // Touching down centres the stick under the thumb, so nothing moves yet.
    await left.down(1, 100, 100);
    assert.deepEqual(await tick(), {forward: 0, strafe: 0, rotate: 0});
    await left.move(1, 100, 60);
    assert.deepEqual(await tick(), {forward: 1, strafe: 0, rotate: 0}, 'Up drives forward');
    await left.move(1, 140, 100);
    assert.deepEqual(await tick(), {forward: 0, strafe: 1, rotate: 0}, 'Right strafes right');
    await left.move(1, 100, 60);
    await right.down(2, 100, 100);
    await right.move(2, 72, 180);
    const both = await tick();
    assert.equal(both.forward, 1, 'Two thumbs work two sticks');
    assert(both.rotate > 0.4 && both.rotate < 0.5, `Half way left turns left, past the deadzone: ${both.rotate}`);
    assert.equal(both.strafe, 0, 'The turning stick ignores up and down');

    // Lifting a thumb stops its stick at once, without waiting for the tick.
    const count = app.driveRequests().length;
    await left.up(1);
    assert.equal(app.driveRequests().length, count + 1);
    assert.equal(app.driveRequests().at(-1).payload.forward, 0);
    assert(app.driveRequests().at(-1).payload.rotate > 0, 'The other thumb keeps turning');

    // Stop lets go of a held stick, and that thumb stays inert after re-enabling.
    await app.$('#mobileStop').fire('click');
    await app.settle();
    assert.equal(app.$('#robotState').querySelector('strong').textContent, 'DISABLED');
    await app.arm();
    await right.move(2, 44, 100);
    assert.equal((await tick()).rotate, 0, 'A thumb held through Stop cannot drive');
    await right.up(2);
    await right.down(3, 100, 100);
    await right.move(3, 170, 100);
    assert.equal((await tick()).rotate, -1, 'A fresh touch pushed right turns right');
    await right.up(3);

    // A thumb that lands while the robot is disabled stays inert too.
    await app.$('#disableButton').fire('click');
    await app.settle();
    await left.down(4, 100, 100);
    await app.arm();
    await left.move(4, 100, 60);
    assert.equal((await tick()).forward, 0, 'A thumb that landed while disabled cannot drive');
    await left.up(4);

    // A bound key brings the keys back and lets go of the sticks.
    await left.down(5, 100, 100);
    await left.move(5, 60, 100);
    await app.window.fire('keydown', {key: 's'});
    await app.settle();
    assert.equal(html.dataset.input, 'keys');
    assert.deepEqual(app.motion(app.driveRequests().at(-1).payload), {forward: -1, strafe: 0, rotate: 0},
      'The stick let go when the keys came back');
    assert.equal(app.$('[data-touch-panel="imu"]').hidden, false, 'Every panel is back');
    assert.equal(app.$('#controllerSummary').textContent, 'Keyboard');
  } else if (scenario === 'station-stick-layout') {
    await app.releaseForward();
    // The first telemetry sets the default layouts; then the robot is enabled.
    await app.context.dashboard.refreshTelemetry();
    await app.settle();
    await app.arm();
    app.setTelemetry({
      touch_sticks: {forward: 'left_y', strafe: null, rotate: 'buttons', deadzone: 0, curve: 1},
      gamepad_sticks: {forward: '-right_y', strafe: 'left_x', rotate: null, deadzone: 0.2, curve: 2},
      touch_panels: ['imu', 'mechanisms'],
    });
    const stops = app.requests.filter(item => item.url === '/api/stop').length;
    await app.context.dashboard.refreshTelemetry();
    await app.settle();
    assert.equal(app.$('#robotState').querySelector('strong').textContent, 'DISABLED', 'A new stick layout disables');
    assert(app.requests.filter(item => item.url === '/api/stop').length > stops, 'and stops the outputs');
    await app.window.fire('pointerdown', {pointerType: 'touch', pointerId: 90});

    // touch_sticks(): forward and back on the left stick, Turn buttons on the right.
    assert.equal(app.$('#leftStickPad').dataset.axes, 'y');
    assert.equal(app.$('#rightStickPad').hidden, true);
    assert.equal(app.$('#rightStick').hidden, false);
    assert.equal(app.$('#rightStick').querySelector('.turn-buttons').hidden, false);
    assert.equal(app.$('#leftStick').querySelector('.turn-buttons').hidden, true);
    assert.equal(app.$('#rightStick').querySelector('.stick-caption strong').textContent, 'Turn');
    assert.match(app.$('#touchLegend').textContent, /^Left stick drives, the Turn buttons turn\./);
    // touch_panels(): the IMU and mechanisms join robot control, sticks and cameras.
    assert.equal(app.$('[data-touch-panel="imu"]').hidden, false);
    assert.equal(app.$('[data-touch-panel="mechanisms"]').hidden, false);
    assert.equal(app.$('[data-touch-panel="pi_inputs"]').hidden, true);
    assert.equal(app.$('[data-touch-panel="status"]').hidden, true);
    assert.equal(app.$('.right-column').hidden, false, 'The IMU keeps its column');

    await app.arm();
    const left = app.stick('left');
    await left.down(1, 100, 100);
    await left.move(1, 160, 72);
    const turnLeft = app.$('#rightStick').querySelector('[data-turn="turn_left"]');
    await turnLeft.fire('pointerdown', {pointerId: 2, pointerType: 'touch', button: 0});
    await app.settle();
    assert.deepEqual(app.motion(app.driveRequests().at(-1).payload), {forward: 0.5, strafe: 0, rotate: 1},
      'Half way up drives at half; sideways does nothing; Turn left turns left');
    assert(turnLeft.classList.contains('active'));
    await turnLeft.fire('pointerup', {pointerId: 2});
    await app.settle();
    assert.deepEqual(app.motion(app.driveRequests().at(-1).payload), {forward: 0.5, strafe: 0, rotate: 0});
    await left.up(1);

    // gamepad_sticks(): the right stick drives, flipped, past a deadzone and along a curve.
    app.context.navigator.getGamepads = () => [
      {index: 0, id: 'Test pad (STANDARD GAMEPAD)', mapping: 'standard', axes: [0.6, 0, 0.9, 0.6]},
    ];
    await app.context.dashboard.sendDrive();
    await app.settle();
    assert.deepEqual(app.motion(app.driveRequests().at(-1).payload), {forward: 0.25, strafe: 0.25, rotate: 0});
    assert.equal(app.$('#controllerSummary').textContent, 'Touch + gamepad');
    assert.match(app.$('#keyLegend').textContent, /Controller: left stick strafes, right stick drives\./);
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
  } else if (scenario === 'station-gamepad-buttons') {
    await app.releaseForward();
    await app.arm();
    const gamepadWithButtons = pressedIndexes => ({
      index: 0, id: 'Test pad (STANDARD GAMEPAD)', mapping: 'standard', axes: [0, 0, 0, 0],
      buttons: Array.from({length: 16}, (_, index) => ({pressed: pressedIndexes.includes(index)})),
    });

    // Button 13 is the D-pad's down button, "stop" by default with no dashboard.py.
    // readPad() polls on its own interval, independent of sendDrive() and of
    // whether the robot is armed, exactly as the real page's setInterval does.
    app.context.navigator.getGamepads = () => [gamepadWithButtons([13])];
    let stops = app.requests.filter(item => item.url === '/api/stop').length;
    await app.context.dashboard.readPad();
    await app.settle();
    assert.equal(app.$('#robotState').querySelector('strong').textContent, 'DISABLED',
      "The D-pad's default stop button disables the robot");
    assert(app.requests.filter(item => item.url === '/api/stop').length > stops);

    // Holding it down must not resend the stop on every poll.
    stops = app.requests.filter(item => item.url === '/api/stop').length;
    await app.context.dashboard.readPad();
    await app.settle();
    assert.equal(app.requests.filter(item => item.url === '/api/stop').length, stops,
      'A held stop button only fires once, on the initial press');

    // Releasing it, then pressing it again, fires the stop again.
    app.context.navigator.getGamepads = () => [gamepadWithButtons([])];
    await app.context.dashboard.readPad();
    await app.settle();
    await app.arm();
    app.context.navigator.getGamepads = () => [gamepadWithButtons([13])];
    stops = app.requests.filter(item => item.url === '/api/stop').length;
    await app.context.dashboard.readPad();
    await app.settle();
    assert(app.requests.filter(item => item.url === '/api/stop').length > stops,
      'Pressing the button again after releasing it fires the stop again');

    // A project can rebind any button with gamepad_buttons(); this one drives.
    await app.arm();
    app.setTelemetry({gamepad_buttons: {b: 'forward'}});
    await app.context.dashboard.refreshTelemetry();
    await app.settle();
    await app.arm();
    app.context.navigator.getGamepads = () => [gamepadWithButtons([1])];
    await app.context.dashboard.sendDrive();
    await app.settle();
    assert.deepEqual(app.motion(app.driveRequests().at(-1).payload), {forward: 1, strafe: 0, rotate: 0},
      'A button mapped to forward drives forward at full speed');
  } else if (scenario === 'station-camera-rotation') {
    await app.context.dashboard.refreshTelemetry();
    await app.settle();
    const frame = app.$('[data-camera-id="camera-1"]');
    const slider = frame.querySelector('.camera-rotate-slider');
    const number = frame.querySelector('.camera-rotate-value');
    const button = frame.querySelector('.camera-rotate-button');
    const image = frame.querySelector('img');
    assert.equal(image.style.transform, '', 'No rotation applied yet');

    slider.value = '45';
    await slider.fire('input');
    assert.equal(image.style.transform, 'rotate(45deg)');
    assert.equal(number.value, '45', 'The number box tracks the slider');

    // Holding Shift while dragging the slider snaps it to 90 degree steps.
    await app.window.fire('keydown', {key: 'Shift'});
    slider.value = '100';
    await slider.fire('input');
    assert.equal(image.style.transform, 'rotate(90deg)', 'Shift snaps the drag to the nearest 90 degrees');
    await app.window.fire('keyup', {key: 'Shift'});

    // Typing an exact angle is always free precision, Shift or not.
    number.value = '91';
    await number.fire('change');
    assert.equal(image.style.transform, 'rotate(91deg)');
    assert.equal(slider.value, '91', 'The slider tracks a typed value');

    // The round button adds 90 degrees each press, wrapping past 360.
    number.value = '300';
    await number.fire('change');
    await button.fire('click');
    assert.equal(image.style.transform, 'rotate(30deg)', 'Rotation wraps around at 360');
  } else {
    throw new Error(`Unknown scenario: ${scenario}`);
  }
}

run(process.argv[2]).catch(error => { console.error(error.stack); process.exitCode = 1; });
