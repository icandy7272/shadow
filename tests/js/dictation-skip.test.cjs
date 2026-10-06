const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

for (const [value, event, expected] of [
  ['', {}, 'skip'],
  ['  \n\t', {}, 'skip'],
  ['some words', {}, 'submit'],
  ['?', {}, 'submit'],
  ['', { isComposing: true }, null],
  ['', { shiftKey: true }, null],
]) {
  test(`dictation Enter routes ${JSON.stringify(value)} with ${JSON.stringify(event)}`, () => {
    const source = fs.readFileSync('src/shadow/web/static/app.js', 'utf8');
    const start = source.indexOf('  typed.addEventListener("keydown",');
    const end = source.indexOf('\n  // 在光标处', start);
    let handler;
    let action = null;
    let prevented = false;
    vm.runInNewContext(source.slice(start, end), {
      typed: { value, addEventListener: (_, callback) => { handler = callback; } },
      physicalKey: () => 'Enter',
      submitDrill: { click: () => { action = 'submit'; } },
      skipDrill: { click: () => { action = 'skip'; } },
    });
    handler({ preventDefault: () => { prevented = true; }, ...event });
    assert.equal(action, expected);
    assert.equal(prevented, expected !== null);
  });
}

test('skipping dictation unlocks recording without grading or discarding the draft', () => {
  const source = fs.readFileSync('src/shadow/web/static/app.js', 'utf8');
  const start = source.indexOf('  skipDrill.addEventListener(');
  assert.notEqual(start, -1, 'skip handler exists');
  const end = source.indexOf('\n  submitDrill.addEventListener(', start);
  let click;
  let stopped = false;
  let folded = false;
  let focused = false;
  const classes = new Set(['locked']);
  const draft = { value: 'already typed' };
  vm.runInNewContext(source.slice(start, end), {
    skipDrill: { addEventListener: (_, handler) => { click = handler; } },
    submitDrill: { disabled: false },
    drillStep: { classList: { contains: () => false, add: (name) => classes.add(name) } },
    typed: draft,
    stopLoops: () => { stopped = true; },
    setFolded: (value) => { folded = value; },
    document: { getElementById: (id) => id === 'step-record'
      ? { classList: { remove: (name) => classes.delete(name) } }
      : { focus: () => { focused = true; } } },
  });
  click();
  assert.equal(stopped, true);
  assert.equal(folded, true);
  assert.equal(classes.has('locked'), false);
  assert.equal(classes.has('skipped'), true);
  assert.equal(focused, true);
  assert.equal(draft.value, 'already typed');
});

test('mastered dictation advances to recording after blind rating', async () => {
  const source = fs.readFileSync('src/shadow/web/static/app.js', 'utf8');
  const start = source.indexOf('      const drill = document.getElementById("step-drill");');
  const end = source.indexOf('\n    });', start);
  for (const mastered of [false, true]) {
    let skipped = false;
    let focused = false;
    let target;
    const drill = {
      dataset: { autoSkip: String(mastered) },
      classList: { remove() {}, contains: () => false },
      scrollIntoView: () => { target = 'drill'; },
    };
    await vm.runInNewContext(`(async () => {${source.slice(start, end)} })()`, {
      listenStep: {}, markComplete() {},
      window: { matchMedia: () => ({ matches: true }) },
      document: { getElementById: (id) => ({
        'step-drill': drill,
        'skip-drill': { click: () => { skipped = true; } },
        'step-record': { scrollIntoView: () => { target = 'record'; } },
        'dictation-text': { focus: () => { focused = true; } },
      })[id] },
    });
    assert.equal(skipped, mastered);
    assert.equal(target, mastered ? 'record' : 'drill');
    assert.equal(focused, !mastered);
  }
});
