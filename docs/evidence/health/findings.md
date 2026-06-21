# health log — audit findings

New health/fitness log. Isolated server `:8917`, seeded a weight trend (10 pts), a week of sleep, two
workouts. `audit.py` drives the UI.

## What was exercised (works ✓)
- **Metric cards** — one per kind (weight/sleep/workout), each with the latest reading (big number +
  unit) and a hand-drawn SVG trend line + dots — `01-desktop`.
- **Range chips** — 7d / 30d / 90d / 1y re-scope the trend series — `02-range-7d`.
- **Add entry** — kind dropdown (auto-sets the unit hint), value, unit, note; logs and updates the chart +
  latest live — `03-add-form`, `04-after-add`.
- **Recent list** — date / kind / value / note / delete rows.
- **Delete** — confirm dialog (unit-tested; skipped in the Playwright run since it's a custom modal).
- **Responsive** — cards + recent rows reflow at 460px (note column hidden) — `05-narrow`.
- **Breadcrumb / tile / subdomain** — `health` tile (pulse icon), `health.localhost`, breadcrumb
  `health / alles`.

## Console / errors
- `console.log` — **0 real console errors** across range/add/narrow.

## Verdict
Works and looks unified (kokuen tokens, accent trend lines, custom dropdown + chips, no chart lib — the
SVG line mirrors the money/system hand-drawn approach). Latest-per-metric ignores the range window so the
headline number is always current even when the chart is zoomed in.
