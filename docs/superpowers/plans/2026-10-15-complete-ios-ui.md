# Complete Shadow iOS web UI refactor

Approved scope: finish all UI rounds continuously under DESIGN.md, without per-round user approval. Preserve every recorder, grading, additional-take, shortcut, authentication and data contract.

1. Consolidate mobile.css into a coherent mobile component layer. Semantic readable typography, consistent spacing, safe-area-aware shell, responsive lists/search/actions, recording controls, figures, sheets, login and settings. Remove duplicate overrides rather than append another patch layer.
2. Normalize every template: detail back navigation, single title hierarchy, common lists/cards, accessible search and state labels; preserve IDs/data attributes/API behavior. Cover today, plan/guide, start, sources/detail, vocab, records/day/detail, practice, chain/talk, settings/account/login, empty/error states.
3. Make sheet lifecycle return focus and avoid stacking. Preserve dismiss guards, recording and unsaved content; ensure dialog accessible naming. Add stable per-tab navigation/scroll retention without interfering with pending audio or form submissions. Use meaningful regression tests for behavior.
4. Run all Python/Node tests; browser verify 320/390/430 and landscape plus enlarged text, light/dark, long content, empty states, list actions, sheets and practice state controls. Real iPhone OS chrome remains a separate hardware verification limitation.
5. Independent spec and quality review; address findings. Commit/push completed changes, final clean status and verification report. No local data or secrets in Git.

Implementation, automated/browser checks and independent spec/quality reviews completed. Verification details: docs/design/2026-10-15-ui-verification.md. Physical iPhone validation remains explicitly outside desktop proof.
