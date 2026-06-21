# watch (uptime/status dashboard) — audit findings

Built new from the next-version plan. Isolated server `:8912`, fresh `ALLES_DATA`, real seeded
monitors (a live local target, a dead `127.0.0.1:1`, a real TLS cert on example.com, google).

## What was exercised (works ✓)
- **Create** monitor via the inline add form (name/url/kind dropdown/interval/keyword) — `02-add-form`, `03-after-create`.
- **List + overview** — status dot (up/down/unknown), latency, uptime 24h/7d, "x ago", kind badge — `01-desktop`.
- **Live probing** — `check now` per card + `refresh all`; real results: local target up (~157ms), dead target down (WinError 10061), example.com cert valid (70d left), google returned a real `429`.
- **Edit** (inline, all advanced fields: interval/expect_status/keyword/latency-ceiling) + save — `04-edit-form`.
- **Delete** with confirm dialog.
- **Sparklines** — per-monitor latency series (blue up / red down), hand-drawn SVG, no chart lib.
- **AI usage card** — reads `/api/usage/summary` (0/0/0 on a fresh instance, renders fine).
- **Background job** — `jobs.register("watch", …, 60)`; emits `watch.down` on a fresh failure.
- **Home tile + breadcrumb + subdomain** — `watch` tile (eye icon) sits unified in the home grid; `watch.localhost` loads; breadcrumb `watch / alles` — `07-home-grid`.
- **Responsive** — single-column stack at 460px, no overflow — `06-narrow`.

## Issues found + fixed
1. **Cert sparkline was meaningless** — cert checks have no latency (always 0ms), so the card drew a
   flat line. **Fixed**: cert monitors now render a color-coded depleting *expiry bar* (green→amber<30d→red<14d)
   over a 90-day horizon instead of a sparkline. Re-verified in `05-after-refresh` (example cert shows a green bar).

## Console / errors
- `console.log` — **0 real console errors** across create/edit/delete/check/refresh/narrow/home (filtered the
  usual favicon/401 boot noise). Playwright audit script: `audit.py`.

## Verdict
Works on both axes — functional and visually unified with the rest of alles (kokuen tokens, custom
controls only, 2–4px radii, no shadows). The duplicate "UI-made monitor" cards in `05-after-refresh`
are just the audit's create-flow run twice, not a defect.
