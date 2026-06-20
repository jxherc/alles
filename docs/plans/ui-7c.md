# ui-7c — journal "lock now" fix

The lock action's backend (`POST /api/journal/lock` clearing unlock tokens) already worked — the bug was
the **UI**: clicking "lock now" opened the lock/change/disable picker inside `#jrnl-reflection` (the AI
reflection panel down in the main column), far from the lock button, so it read as "nothing happened".

## Fix (`static/js/journal.js`, `static/style.css`)
- `pickLockAction` now builds an **anchored dropdown** appended to `<body>`, positioned right under the
  lock button (`getBoundingClientRect`), dismissed on outside `mousedown` — no longer hijacks the
  reflection panel.
- The working lock flow is unchanged: pick "lock now" → `POST /api/journal/lock` → clear token →
  `showLock('unlock')` (lock screen + 403-gated data).
- De-iconed the lock chrome: button 🔒/🔓 → `lock`/`unlock` icons, lock-screen 🔒 → `lock` icon.

Tests: `tests/test_journal_lock_ui.py` (5 frontend contract) — backend gating stays covered by the
existing `tests/test_journal_lock.py` (incl. `test_lock_clears_tokens`) — plus
`docs/evidence/ui-7c/verify.py` (anchored menu near the button, lock-now shows the lock screen + 403s
the data endpoint + clears the token, icons render, 0 console errors).
