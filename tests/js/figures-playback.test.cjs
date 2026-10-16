const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function setup({ stopDuringClip = false, stopDuringGap = false, cache = null, refOffset = 0, usrOffset = 0 } = {}) {
  const listeners = new Map();
  const media = [];
  let stopped = 0;
  const blank = () => listeners.get('pointerdown')?.({ target: { closest: () => null } });
  class Audio {
    constructor(src) { this.src = src; this.readyState = 1; this.currentTime = 0; this.plays = 0; this.starts = []; this.paused = true; media.push(this); }
    play() {
      this.plays += 1;
      this.starts.push(this.currentTime);
      this.paused = false;
      if (stopDuringClip && this.plays === 2) queueMicrotask(blank);
      return Promise.resolve();
    }
    pause() { this.paused = true; }
    load() { this.readyState = 1; }
  }
  class AudioContext {
    constructor() { this.state = 'running'; }
    createMediaElementSource() { return { connect() {} }; }
  }
  const context = vm.createContext({
    Audio, window: { AudioContext, ShadowAudio: cache }, performance,
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
  context.testOffsets={refOffset,usrOffset};
  const player = vm.runInContext('playback({seconds: 1}, {ref: "ref", usr: "usr", refOffset: testOffsets.refOffset, usrOffset: testOffsets.usrOffset}, () => {}, onStopped)', context);
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


test('feedback prepares both cached tracks before playback and reuses them', async () => {
  const requests = [];
  const { player, media } = setup({ cache: { peek: () => undefined, url: async (src) => {
    requests.push(src); return `blob:${src}`;
  } } });
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(requests, ['ref', 'usr']);
  assert.deepEqual(media.map((item) => item.src), ['blob:ref', 'blob:usr']);
  await player.play([player.ref, player.usr], true);
  player.stop();
  await player.play([player.ref, player.usr], true);
  player.stop();
  assert.equal(requests.length, 2);
});

test('stopping while cached audio loads prevents playback after it arrives', async () => {
  let deliver;
  const pending = new Promise((resolve) => { deliver = resolve; });
  const { player, media } = setup({ cache: { peek: () => undefined, url: () => pending } });
  assert.deepEqual(media.map((item) => item.src), ['ref', 'usr']);
  const playing = player.play([player.ref, player.usr], true);
  player.stop();
  deliver('blob:ready');
  await playing;
  assert.ok(media.every((item) => item.paused));
  assert.ok(media.every((item) => item.plays === 1)); // Only synchronous unlock.
});

for(const [refOffset,usrOffset] of [[0,.42],[.04,.5],[.6,.02],[.4,.7]]) {
 test(`simultaneous speech onsets share the same lead-in (${refOffset}, ${usrOffset})`,async()=>{
  const {player,media}=setup({refOffset,usrOffset});
  await player.play([player.ref,player.usr],true);player.stop();
  const refLead=refOffset-media[0].starts[1],usrLead=usrOffset-media[1].starts[1];
  assert.ok(Math.abs(refLead-usrLead)<1e-9,`unequal lead-ins: ${refLead} vs ${usrLead}`);
  assert.ok(Math.abs(refLead-Math.min(.15,refOffset,usrOffset))<1e-9);
 });
}
test('single track playback keeps its available lead-in',async()=>{
 const {player,media}=setup({refOffset:0,usrOffset:.5});
 await player.play([player.usr],false);player.stop();
 assert.ok(Math.abs(media[1].starts[1]-.35)<1e-9);
});
