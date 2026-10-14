# Shadow native mobile app implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Apply the approved openGym interaction matrix to Shadow's existing learning flows, with durable practice restoration and consistent native mobile navigation and controls.

**Architecture:** Keep FastAPI/Jinja and existing recorder APIs. Add focused browser modules for session persistence and sheet interaction; integrate them through explicit practice snapshots rather than storing rendered HTML. Keep actual results and recordings authoritative, preserve extra takes in the same run and all physical-key shortcuts.

**Tech Stack:** FastAPI, Jinja, vanilla JavaScript, IndexedDB, CSS; pytest and Node test runner.

## 1. Navigation and durable practice session (A04–A09)
- [x] Add failing tests for session URL validation, restoration, Blob persistence failure and five navigation entries.
- [x] Create static/session.js with IndexedDB storage and a small localStorage resume pointer. Snapshot includes sentence URL and queue, active stage, rating/run ID, typed draft, grading JSON, latest analysis JSON, pending take Blobs and submission ID. Store no rendered HTML.
- [x] Integrate app.js and mobile.js snapshot/restore. Restoration disables actions until loaded. Recording cannot be minimized mid-take; failed upload cannot be left until durable save succeeds. Failed storage keeps the existing navigation protection.
- [x] Add /start picker and five-slot navigation: Today, Plan, central Start/Resume, Records, Library; vocab accessible through Library. Restore actual state and allow explicit ending/discard of a saved session.
- [x] Verify Node/Python regression suites, then commit and push.

## 2. Practice screen and native sheets (D/E/F/G)
- [x] Add tests for history-aware sheet close, drag exclusion, number bounds and saved-completion conditions.
- [x] Create static/native-ui.js: dialog stack, background scroll preservation, back closes top sheet, drag only from grabber, accessible native dialog focus, press-and-hold steppers and clearable search.
- [x] Replace practice header with minimize/title/progress/more/finish; show current sentence and stage progress, stable bottom action region. Keep three initial takes and successive additional takes in one run.
- [x] Use grouped quick settings, picker/stepper controls, explicit session ending confirmation and real saved-result summary. Maintain loading/failure/retry states and desktop shortcuts.
- [x] Unify CSS tokens, grouped rows, safe areas, 44px targets, motion and keyboard behavior. Verify and commit/push.

## 3. Today, library, records and settings (B/C/H/I)
- [x] Add server tests for start/settings pages, date drill-down and real record detail.
- [x] Refine Today and Plan into task-focused grouped screens; Library links vocabulary, horizontal filters and clearable search; move explanatory text to details.
- [x] Add records date drilling and recent/history separation using actual persisted run/talk data. Add settings root grouped categories, appearance and service/about/install information with working links.
- [x] Add standalone PWA manifest/icons; do not cache private recordings or claim offline recording support.
- [x] Run full regression suite and browser-check narrow mobile layouts, sheet return, draft/session recovery and extra take flow. Commit/push and integrate main.

## Validation and acceptance
Run `PYTHONPATH=src /Users/wenchaodu/Documents/Claude/Projects/shadow/.venv/bin/python -m pytest` and `node --test tests/js/*.test.cjs` in the worktree. Test browser against isolated seeded data. Check 390px and 320px layouts, input keyboard visibility, pending-upload guard, real resume and all main navigation links. Optional business additions in matrix (accounts, Coach, reminders, arbitrary queue reorder) are outside this approved reuse pass. Each delivered stage must be usable and synced; report remaining device-only limits honestly.

## Review refinements
- Persist each completed take before upload, preserving original submission UUID and append mode across retry. IndexedDB is authoritative; resume pointer changes only after successful write. Version snapshots, validate same-origin practice URLs, tolerate malformed/deleted/stale data without enabling unsafe submission; allow one retained session per sentence, explicitly resolve replacement before starting another unfinished session.
- Keep saved-result snapshots until user ends the session; pending recordings clear only after authoritative successful response or explicit discard. Restore selected take and settings where needed. Browser interruption retries use the same UUID for server deduplication.
- Restore scroll on history return for Library/material/vocab/records; forward navigation starts at top. Sheet dimensions account for visualViewport height and offset; nested Back/Escape closes only highest layer; confirm keyboard dismissal does not jump the background.
- Drag dismissal is intentionally grabber-only to preserve content scrolling and chart gestures.

## Delivered verification notes
- Actual browser checked blind rating → typed draft → minimize → central resume; submitted dictation result also restores its answer and current stage.
- Native nested recording sheet Back closes only the top layer; cancel source deletion returns to the source menu, next Back closes that menu.
- Recording retry and additional-take restoration, quota failure, active learning mutations, and same-sentence stale-tab save/clear/restart races covered by automated tests.
- The sheet uses a grabber-only drag dismissal. iPhone keyboard, microphone permission, interruption and home-screen installation still require physical-device acceptance; browser viewport checks do not replace those.
- This pass reuses existing learning functionality. New learning curves, notification business, arbitrary schedule/queue editors and accounts are not introduced.
