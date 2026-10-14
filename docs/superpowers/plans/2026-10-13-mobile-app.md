# Shadow mobile app implementation

Approved design: docs/previews/shadow-mobile-comparison.html.

Architecture: preserve FastAPI/Jinja and existing recorder/data APIs. Add today/records routes, shared app shell, mobile.css and a presentation-only practice controller. Keep IDs and handlers, move actual controls into the action dock and settings sheet.

- [x] Real today dashboard and weekly activity.
- [x] Unified records with week/month/all filtering and archived counts.
- [x] Apple-style grouped cards, safe-area bottom navigation, theme settings.
- [x] Focused unlocked practice steps; dictation feedback, auto-skip and history preserved.
- [x] Existing R/N/T/Space/navigation shortcuts, including Chinese input support.
- [x] Real microphone/count/prelisten/autostop settings, microphone status feedback.
- [x] Import sheet, library/vocabulary search, real delete/retry actions.
- [x] Pointer selection for mouse/touch and shared rhythm/pitch tabs.
- [x] Full Python/frontend regression, 390px browser layout and actual API flows, independent final code review.

Validation uses an ignored test-data directory; no personal exercise data or credentials are committed. Physical iPhone keyboard and microphone hardware are not available to this session; recorder algorithms retain existing tests.
