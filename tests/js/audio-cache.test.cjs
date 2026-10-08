const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function setup(fetch) {
  const window = {};
  vm.runInNewContext(fs.readFileSync('src/shadow/web/static/audio.js', 'utf8'), {
    window, fetch, URL: { createObjectURL: () => 'blob:cached' }, AbortController, setTimeout, clearTimeout,
  });
  return window.ShadowAudio;
}
test('concurrent preparation and later playback share one download and decode', async () => {
  let requests = 0, decodes = 0;
  const audio = setup(async () => { requests++; return { ok: true, blob: async () => ({ arrayBuffer: async () => new ArrayBuffer(8) }) }; });
  const context = { decodeAudioData: async () => { decodes++; return { duration: 2 }; } };
  await Promise.all([audio.url('/audio/1/1'), audio.decode('/audio/1/1', context)]);
  await audio.decode('/audio/1/1', context);
  await audio.url('/audio/1/1');
  assert.equal(requests, 1);
  assert.equal(decodes, 1);
});
test('failed downloads can be retried', async () => {
  let requests = 0;
  const audio = setup(async () => { if (++requests === 1) throw new Error('offline'); return { ok: true, blob: async () => ({}) }; });
  await assert.rejects(audio.url('/audio/1/1'), /offline/);
  assert.equal(await audio.url('/audio/1/1'), 'blob:cached');
  assert.equal(requests, 2);
});
test('failed decoding can be retried without downloading again', async () => {
  let requests = 0, decodes = 0;
  const audio = setup(async () => { requests++; return { ok: true, blob: async () => ({ arrayBuffer: async () => new ArrayBuffer(8) }) }; });
  const context = { decodeAudioData: async () => { if (++decodes === 1) throw new Error('decode'); return {}; } };
  await assert.rejects(audio.decode('ref', context), /decode/);
  await audio.decode('ref', context);
  assert.equal(requests, 1);
});
