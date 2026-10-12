const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
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
      extra, takeCount: 3, startButton: {}, setRecording() {}, createSpeaker: () => speaker,
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
    assert.equal(heard, extra ? 4 : 12);
    assert.equal(settings.takes.value, '3');
    assert.equal(settings.prelisten.value, '4');
  });
}
