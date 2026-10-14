# Native mobile interaction round two

> Use superpowers:subagent-driven-development or executing-plans, tests and review per component.

**Goal:** Complete previously approved matrix interactions G08, F01/F05, D03, E01/E02, H10, B02/B08, C06/C07, A11 using existing learning data.

**Design:** Keep existing audio/recorder and form controls authoritative. Picker sheets dispatch the existing change events; speed controls keep their listening-only semantics. Move live recording status/progress into the fixed dock and show saved/draft/request phases distinctly. Take menus reuse selection and playback; a fullscreen graph viewer moves the actual interactive graph nodes and returns them when closed. Week navigation changes only calendar selection, never today's task. Search empty states and counters follow filtered DOM state. Optional screen-awake setting uses Wake Lock when supported, is released in background and never claims background recording.

**Files:** new static/mobile-controls.js and tests/js/mobile-controls.test.cjs; static/figures.js and graph tests; mobile.css; app.py and today/settings/practice templates; tests/test_web_mobile.py.

- [x] Write failing tests for picker selection/change, graph selection/menu/viewer, week bounds/actual past counts and awake lifecycle.
- [x] Implement touch pickers, search result state, filter visibility and switches without replacing form values or keyboard targets.
- [x] Implement dock live status/progress and completed-step state; optional awake capability and release handling.
- [x] Implement take operation sheet and graph viewer preserving existing playback/selection/disposal behavior.
- [x] Implement previous/next week and streak card with real archived/current counts; reject unreasonable week offsets.
- [x] Review, run full Python/Node suites, browser-check 320/390px, nested picker return and viewer state restoration. Commit and push each completed component; integrate main automatically per project instructions.

**Non-goals:** No new scoring, no separate before/after extra-take comparison, no destructive take menu, accounts, notifications, manual plan editing or fabricated learning metrics.

## Verification
Full Python suite: 561 passed. Full JS suite: 88 passed. Browser checked 390px picker selection, search clear and no-match state, prior week navigation, enlarged rhythm/pitch viewer with original playback controls, three nested levels of Back and selected-view restoration. Graph browser checks use explicitly labeled isolated samples outside version control. Physical-device Wake Lock behavior remains capability dependent.
