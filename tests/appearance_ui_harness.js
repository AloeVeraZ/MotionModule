'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const script = fs.readFileSync(process.argv[2], 'utf8');

for (const blockedStorage of [false, true]) {
  const listeners = new Map();
  const stored = new Map();
  const root = {attributes: {}, setAttribute(key, value) { this.attributes[key] = value; }};
  const scheme = {matches: false, addEventListener(type, callback) { this.follow = callback; }};
  const buttons = ['light', 'dark', 'system'].map(choice => ({
    dataset: {themeChoice: choice}, attributes: {},
    setAttribute(key, value) { this.attributes[key] = value; },
    addEventListener(type, callback) { this.click = callback; },
  }));
  const meta = {setAttribute(key, value) { this[key] = value; }};
  const context = vm.createContext({
    document: {
      documentElement: root,
      querySelectorAll(selector) {
        if (selector === '[data-theme-choice]') return buttons;
        if (selector === 'meta[name="theme-color"]') return [meta];
        return [];
      },
      querySelector() { return null; },
      addEventListener() {},
    },
    window: {matchMedia: query => query.includes('color-scheme') ? scheme : {matches: false}},
    localStorage: {
      getItem(key) { if (blockedStorage) throw Error('blocked'); return stored.get(key); },
      setItem(key, value) { if (blockedStorage) throw Error('blocked'); stored.set(key, value); },
    },
    addEventListener(type, callback) { listeners.set(type, callback); },
  });
  vm.runInContext(script, context);
  const expect = (theme, choice) => {
    assert.equal(root.attributes['data-theme'], theme);
    assert.equal(buttons.find(button => button.dataset.themeChoice === choice).attributes['aria-pressed'], 'true');
  };
  expect('dark', 'dark');
  buttons[0].click(); expect('light', 'light');
  assert.equal(meta.content, '#d5dce7');
  buttons[1].click(); expect('dark', 'dark');
  buttons[2].click(); expect('dark', 'system');
  scheme.matches = true; scheme.follow(); expect('light', 'system');
  scheme.matches = false; scheme.follow(); expect('dark', 'system');
  buttons[0].click(); scheme.follow(); expect('light', 'light');
  if (!blockedStorage) {
    stored.set('motionmodule-theme', 'dark');
    listeners.get('storage')({key: 'motionmodule-theme'});
    expect('dark', 'dark');
  }
}
console.log('Appearance preferences, system changes, cross-tab sync, and blocked storage passed.');
