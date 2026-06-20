# ui-7e — day-cluster de-icon (findings)

## Audit
tasks/calendar/days/journal carried leftover emoji (🔁 ★ 🎉 ↻ ✨ 🔥 🔗 ☑ ☐ 📹 ✓ ✗) — the day apps the
user pointed at with "remove icons maybe that helps".

## Fix
Swapped every control glyph to the central icon set via `_si`/`window.icon`; sized them in CSS.

## Bug found by the behavioral verify
The calendar recurring-chip swap produced `'<span class="cal-chip-recur">${_si('refresh')}</span>'` —
`${…}` with `'refresh'` nested inside a **single-quoted** string. That breaks the string literal and
throws "Unexpected identifier 'refresh'", which aborts app.js boot, so EVERY subdomain view rendered
blank. `node --check` passed it; only the Playwright verify (app fails to build the view) exposed it.
Fixed by making the inner strings nested backtick templates. Lesson logged: glyph→`${_si()}` swaps must
land in template literals, never single-quoted strings.

## Verify
After the fix: tasks repeat badge + journal reflect button render real `<svg class=ic>`, no emoji,
0 console errors. days/calendar base views stay account-gated on this server (gate test covers them).
