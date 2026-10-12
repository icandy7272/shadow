const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function api() {
  const window = {};
  const path = 'src/shadow/web/static/extra-practice.js';
  if (fs.existsSync(path)) vm.runInNewContext(fs.readFileSync(path, 'utf8'), {window});
  assert.ok(window.ShadowExtraPractice, 'extra practice API exists');
  return window.ShadowExtraPractice;
}
const issue = {kind: 'stretched', ref_index: 0, title: 'too long', hits: 2, total: 3};
function result(issues = [], uncertain = []) {
  return {issues, count: 1, view: {chosen: 0, takes: [{issues, uncertain, audio: {ref: '/ref', usr: '/take'}, pitch: []}]}};
}
test('extra practice fixes baseline and keeps successful attempts separate', () => {
  const session = api().session();
  const base = result([issue]); base.count = 3;
  session.accept(base, false);
  session.accept(result(), true);
  session.accept(result([issue]), true);
  assert.equal(session.baseline, base);
  assert.equal(session.attempts.length, 2);
  assert.equal(base.count, 3);
  assert.equal(session.rows()[0].hits, 1);
  assert.equal(session.rows()[0].total, 2);
  session.accept(result(), false);
  assert.equal(session.attempts.length, 0);
});
test('one absent issue is only an observation, not stable improvement', () => {
  const session = api().session();
  session.accept(result([issue]), false);
  session.accept(result(), true);
  assert.equal(session.rows()[0].state, 'absent');
  assert.equal(session.rows()[0].total, 1);
});
test('unreliable words never become resolved issues', () => {
  const session = api().session();
  session.accept(result([issue]), false);
  session.accept(result([], [0]), true);
  assert.equal(session.rows()[0].state, 'uncertain');
  assert.equal(session.rows()[0].total, 0);
});
test('issues match by position and kind, not their changing title', () => {
  const session = api().session();
  session.accept(result([issue]), false);
  session.accept(result([{...issue, title: 'different wording'}]), true);
  assert.equal(session.rows()[0].state, 'present');
});
test('missing pitch evidence does not masquerade as improvement', () => {
  const session = api().session();
  const pitch = {...issue, kind: 'flat_fall'};
  session.accept(result([pitch]), false);
  const after = result(); after.view.takes[0].uncertain_issues = ['flat_fall:0'];
  session.accept(after, true);
  assert.equal(session.rows()[0].state, 'uncertain');
});

function panelSetup({deferStart = false} = {}) {
  let releaseStart;
  const window = {};
  const tracks = [];
  class Element {
    constructor(tag, text) { this.tag = tag; this.textContent = text; this.children = []; this.handlers = {}; }
    append(...children) { this.children.push(...children); }
    setAttribute() {}
    addEventListener(name, handler) { this.handlers[name] = handler; }
  }
  class Audio {
    constructor(src) { this.src = src; this.readyState = 1; this.currentTime = 0; this.starts = []; this.ended = false; tracks.push(this); }
    play() {
      this.starts.push(this.currentTime);
      if (deferStart && this === tracks[0] && this.starts.length === 2)
        return new Promise(resolve => {releaseStart = resolve;});
      return Promise.resolve();
    }
    pause() {}
  }
  const loops = new Set();
  vm.runInNewContext(fs.readFileSync('src/shadow/web/static/extra-practice.js', 'utf8'), {
    window, Audio, recording: false, loops, stopLoops: () => loops.forEach(stop => stop()),
    el: (tag, cls, text) => new Element(tag, text),
    setInterval: fn => setInterval(() => {tracks.forEach(t => {t.currentTime += 0.1; t.ended = t.currentTime > 4;}); fn();}, 1),
    clearInterval, Date,
  });
  const state = window.ShadowExtraPractice.session();
  const base = result([issue]);
  base.view.takes[0].pitch = [{refAt: [1, 2], usrAt: [1.5, 2.5]}];
  const after = result(); after.view.takes[0].pitch = [{refAt: [1, 2], usrAt: [2, 3]}];
  state.accept(base, false); state.accept(after, true);
  const panel = window.ShadowExtraPractice.panel(state, () => {});
  return {panel, tracks, loops, releaseStart: () => releaseStart()};
}
test('local comparison of first word plays three bounded clips in order', async () => {
  const {panel, tracks, loops} = panelSetup();
  const row = panel.node.children.find(node => node.children?.some(child => child.textContent === issue.title));
  await row.children.at(-1).handlers.click();
  assert.deepEqual(tracks.map(t => t.starts.at(-1)), [0.94, 1.44, 1.94]);
  panel.dispose(); assert.equal(loops.size, 0);
});
test('stopping comparison prevents following audio from playing', async () => {
  const {panel, tracks} = panelSetup();
  const audioRow = panel.node.children.find(node => node.children?.some(child => child.textContent === '▶ 原声 → 加练前 → 加练后'));
  const playing = audioRow.children[0].handlers.click();
  await Promise.resolve();
  audioRow.children[1].handlers.click();
  await playing;
  assert.equal(tracks[1].starts.length, 1); // only browser permission priming
  assert.equal(tracks[2].starts.length, 1);
  panel.dispose();
});

test('late playback startup cannot interrupt a restarted comparison', async () => {
  const {panel, tracks, releaseStart} = panelSetup({deferStart: true});
  const audioRow = panel.node.children.find(node => node.children?.some(child => child.textContent === '▶ 原声 → 加练前 → 加练后'));
  const first = audioRow.children[0].handlers.click();
  audioRow.children[1].handlers.click();
  const second = audioRow.children[0].handlers.click();
  releaseStart();
  await Promise.race([
    Promise.all([first, second]),
    new Promise((_, reject) => setTimeout(() => reject(new Error('restarted playback stalled')), 500)),
  ]);
  assert.ok(tracks[2].starts.length >= 3);
  panel.dispose();
});

for (const extra of [true, false]) {
  test(`${extra ? 'extra' : 'normal'} recording uses its intended takes and prelisten without editing settings`, async () => {
    const source = fs.readFileSync('src/shadow/web/static/app.js', 'utf8');
    const begin = source.indexOf('  async function recordRound(extra) {');
    const end = source.indexOf('\n  // 录音只存在这个页面里', begin);
    let heard = 0, recorded = 0, submitted;
    const settings = {takes: {value: '3'}, prelisten: {value: '4'}};
    const speaker = {ready: async () => {}, context: {}, close() {}, play: async () => {heard++;}, beep: async () => {}};
    const classes = {add() {}, remove() {}};
    await vm.runInNewContext(`${source.slice(begin, end)}\nrecordRound(extra)`, {
      extra, startButton: {}, setRecording() {}, createSpeaker: () => speaker,
      document: {getElementById: id => settings[id] || {classList: classes}},
      navigator: {mediaDevices: {getUserMedia: async () => ({getTracks: () => [{stop() {}}]})}},
      micWanted: () => ({}), status: {classList: classes}, fillMics() {},
      listenTo: async () => null, watchLevel() {}, micMeter: null, autoBox: {checked: true},
      sleep: async () => {}, awake: async () => {}, GAP_MS: 100, BEEP_MS: 20,
      minTake: .1, minSpoken: .1,
      recordOne: async () => {recorded++; return {blob: {}, seconds: 1, loudest: null};},
      submit: async blobs => {submitted = blobs.length;},
    });
    assert.equal(recorded, extra ? 1 : 3);
    assert.equal(submitted, extra ? 1 : 3);
    assert.equal(heard, extra ? 1 : 12);
    assert.equal(settings.takes.value, '3');
    assert.equal(settings.prelisten.value, '4');
  });
}
