# habits — audit findings

New habit tracker. Isolated server `:8914`, seeded 3 habits with real history (Read daily streak 6,
Drink water sporadic, Workout weekly 2/3). `audit.py` drives the UI.

## What was exercised (works ✓)
- **Overview** — per-habit card: icon, name, streak (🔥), 7-day week strip (accent-filled done days),
  GitHub-style contribution heatmap (~17 weeks), and meta (`6/7 days · 86%` / `x/target this week`) — `01-desktop`.
- **Toggle a day** — tapping a day in the week strip marks/unmarks it; streak + heatmap + % update live
  (toggling today off dropped Read 6→5 via the grace rule) — `02-after-toggle`.
- **Add** a habit through the inline form (name, icon, cadence daily/weekly, weekly target) + success
  toast — `03-add-form`, `04-after-create`.
- **Edit** (name/icon/cadence/target) + **archive** + **delete** (confirm dialog) — `05-edit-form`.
- **Responsive** — single-column stack at 460px, heatmap + strip fit, no overflow — `06-narrow`.
- **Breadcrumb / tile / subdomain** — `habits` tile (checklist icon) in the home grid; `habits.localhost`
  loads; breadcrumb `habits / alles`.

## Issues found + fixed
1. **Emoji icons showed as "??"** in the first pass — turned out to be a PowerShell seed-script encoding
   artifact (emoji mangled at the PS→HTTP boundary), not a UI/backend bug. Re-seeding the icons over a
   UTF-8 request rendered them correctly (📖 / 💧) — confirmed in `04-after-create`. Browser entry (fetch,
   UTF-8) was always correct.

## Console / errors
- `console.log` — **0 real console errors** across toggle/add/edit/delete/narrow.

## Verdict
Works and looks unified with the rest of alles (kokuen tokens, custom dropdown for cadence, accent-driven
heatmap, no shadows). Streak math (with grace day), weekly-target %, and the heatmap all behave correctly.
