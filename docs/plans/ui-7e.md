# ui-7e — de-icon the day-cluster apps (tasks / calendar / days / journal)

The day apps still mixed emoji/Unicode glyphs. Unified them to the Stage-0 central icon set (each file
gained a `_si()` `window.icon` guard). Journal MOODS stay — that's a deliberate mood picker, not chrome.

- **tasks.js**: repeat badge 🔁 → `refresh`.
- **days.js**: pin ★ → `star`/`star-fill`, "today" 🎉 → `party`, repeat ↻ → `refresh`.
- **journal.js**: reflect ✨ → `sparkles`, streak 🔥 → `fire`.
- **calendar.js**: feed-copy 🔗 → `link`, recurring ↻ → `refresh`, calendar-task ☑/☐ → `check` + a CSS
  box, jitsi 📹 → `video`, back ← → `chevron-left`, RSVP labels lose their ✓/✗ glyphs (plain words).
- CSS sizes each new `.ic` in its chip/badge/button.

**Bug caught in verify:** the three recurring-event spans were `'<span>${_si('refresh')}</span>'` — a
`${…}` with `'refresh'` inside a **single-quoted** string, which breaks the string and threw a parse
error that killed the whole app boot (every subdomain view went blank). `node --check` did not flag it;
the Playwright verify did. Fixed to nested backtick templates.

Tests: `tests/test_dayapps_icons.py` (7 source-contract across all 4 apps) + `docs/evidence/ui-7e/verify.py`
(live: tasks repeat icon + journal reflect icon render as svg, no emoji, 0 console errors; days/calendar
base views are account-gated here, covered by the gate test).
