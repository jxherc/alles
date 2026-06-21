# habits — daily habit tracker (next-version workstream 3)

Dedicated habit grid (the journal has streaks, but no habit app). A `HabitLog` row = done that day;
toggling adds/removes it. Streak + completion math is pure and unit-tested.

## Tasks

### habits-1 — backend · TDD
- `Habit` + `HabitLog` models in `core/database.py` (HabitLog int rowid; one row per habit/day).
- `routes/habits.py`: pure `daily_streak` (with grace day), `week_done_count`, `completion_pct`
  (daily = done/7; weekly = done/target capped 100), `build_grid`. CRUD + `GET /habits/overview`
  (streak/week_done/pct/done_today/grid per habit) + `POST /habits/{id}/toggle`. Wired via include_router.
- **Tests** (`tests/test_habits.py`, 18): streak consecutive/grace/gap/stale, week window, weekly+daily
  pct, grid order, CRUD, toggle on/off + idempotent, overview shape, archived excluded.

### habits-2 — frontend
- `static/js/habits.js`: habit cards with 7-day tap-to-complete week strip, streak (🔥), contribution
  heatmap (CSS grid, 7 rows × weeks, accent-filled), this-week meta, inline add/edit/archive/delete.
  Custom dropdown for cadence; per-habit color drives `--habit-accent`.
- Wiring: `subdomain.js`, `app.js` (`_VIEW_IDS`, `showHabitsView`, `navigateTo`, `_ICON.habits`,
  `HOME_TILES`), `index.html` (`#habits-view` + stamp 98), `sw.js` v72, `style.css` (`#habits-*` block).
- **Audit** (`docs/evidence/habits/`): screenshots desktop + narrow, 0 console errors, findings.

## Verification
- `python -m unittest tests.test_habits` (18) + full suite green.
- `ruff` clean on new python; `node --check` on touched JS.
- `audit.py 8914` PASS; regression sweep (now 18 hosts incl. habits) green.
