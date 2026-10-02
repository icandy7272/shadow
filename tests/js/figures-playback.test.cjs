const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function setup({ stopDuringClip = false, stopDuringGap = false } = {}) {
  const listeners = new Map();
  const media = [];
  let stopped = 0;
  const blank = () => listeners.get('pointerdown')?.({ target: { closest: () => null } });
  class Audio {
    constructor() { this.readyState = 1; this.currentTime = 0; this.plays = 0; this.paused = true; media.push(this); }
    play() {
      this.plays += 1;
      this.paused = false;
      if (stopDuringClip && this.plays === 2) queueMicrotask(blank);
      return Promise.resolve();
    }
    pause() { this.paused = true; }
  }
  class AudioContext {
    constructor() { this.state = 'running'; }
    createMediaElementSource() { return { connect() {} }; }
  }
  const context = vm.createContext({
    Audio, window: { AudioContext }, performance,
    document: { addEventListener: (type, callback) => listeners.set(type, callback) },
    speed: { follow() {}, rate: 1 },
    setTimeout: (callback, ms) => setTimeout(() => {
      if (stopDuringGap && ms === 240) blank();
      callback();
    }, 0),
    clearTimeout,
    setInterval: (callback) => setInterval(() => {
      media.forEach((item) => { item.currentTime = 100; });
      callback();
    }, 1),
    clearInterval,
  });
  vm.runInContext(fs.readFileSync('src/shadow/web/static/figures.js', 'utf8'), context);
  context.onStopped = () => { stopped += 1; };
  const player = vm.runInContext('playback({seconds: 1}, {ref: "ref", usr: "usr", refOffset: 0, usrOffset: 0}, () => {}, onStopped)', context);
  return { player, media, blank, stopped: () => stopped };
}

test('selected rhythm words play ten times and stop', async () => {
  const { player, media, stopped } = setup();
  await player.playOne('ref', [0, 1], () => {});
  assert.equal(media[0].plays - 1, 10); // First play only unlocks browser audio.
  assert.equal(media[1].plays, 0);
  assert.equal(media[0].paused, true);
  assert.equal(stopped(), 1);
});

test('selected pitch words play ten original/recording pairs', async () => {
  const { player, media } = setup();
  await player.compare({refAt: [0, 1], usrAt: [0, 1]}, () => {});
  assert.deepEqual(media.map((item) => item.plays - 1), [10, 10]);
  assert.ok(media.every((item) => item.paused));
});

test('blank click during a clip stops audio and prevents further rounds', async () => {
  const { player, media, stopped } = setup({stopDuringClip: true});
  await player.playOne('ref', [0, 1], () => {});
  await new Promise((resolve) => setTimeout(resolve, 30));
  assert.equal(media[0].plays - 1, 1);
  assert.equal(media[0].paused, true);
  assert.equal(stopped(), 1);
});

test('blank click between clips cancels the next recording and remaining rounds', async () => {
  const { player, media, stopped } = setup({stopDuringGap: true});
  await player.compare({refAt: [0, 1], usrAt: [0, 1]}, () => {});
  assert.deepEqual(media.map((item) => item.plays - 1), [1, 0]);
  assert.ok(media.every((item) => item.paused));
  assert.equal(stopped(), 1);
});

test('blank click while playback is preparing prevents the first clip', async () => {
  const { player, media, blank, stopped } = setup();
  const pending = player.playOne('ref', [0, 1], () => {});
  blank();
  await pending;
  assert.equal(media[0].plays - 1, 0);
  assert.ok(media.every((item) => item.paused));
  assert.equal(stopped(), 1);
});
