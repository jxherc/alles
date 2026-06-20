# 11b — Mobile: PWA offline polish + optional Capacitor wrapper

ROADMAP 11b (deps 1b, done). Acceptance: installs to home screen; core apps work offline;
responsive at phone widths; optional Capacitor wrapper.

## Audit (by running)
Booted `ALLES_DATA=.tmp_11b3 PORT=8879`. The 1b offline write-queue (`sw.js` IDB outbox +
`sync.js` pending indicator) already worked (pw_sync_1b 9/9). Manifest + apple meta + icons
present. Gaps found: no phone (<=480px) breakpoint → 248px rail ate 64% of a 390px screen;
SW only cached as-you-go, so a cold offline reload showed a login wall + blank shell (the JS
module graph never went through the SW on first visit, and `/api/auth/me` fails offline); no
`mobile/` Capacitor scaffold; manifest lacked orientation/categories/shortcuts/scope/id and
index lacked `mobile-web-app-capable`.

## Built (TDD, RED→GREEN)

### 11b-1 responsive phone layout (`tests/pw_mobile_11b.py` 10/10, 390x844)
`@media (max-width:480px)` in style.css: the aide rail becomes a fixed off-canvas drawer
(closed by default on phone via a non-persisted body class in app.js), opens over a
`.nav-backdrop` dim layer; tap backdrop / nav item closes it. Plus overflow-x guard, bigger
tap targets, modal max-width clamp.

### 11b-2 PWA install polish (`tests/test_manifest_11b.py` 13/13)
manifest.json: added `id`, `lang`, `scope`, `orientation`, `categories`, `shortcuts`
(new chat / tasks / journal). index.html: `mobile-web-app-capable`, `description`,
`viewport-fit=cover`.

### 11b-3 offline app-shell precache (`tests/pw_offline_11b.py` 11/11)
sw.js install now precaches the full shell. To avoid a build manifest, `GET /api/pwa/precache`
enumerates the shell at runtime (/, css?v=, manifest, icons, **every** js module, cm6 vendor =
63 urls); the SW fetches it on install (static core as fallback). app.js: cache the last good
`/api/auth/me` in localStorage and trust it offline (no login wall), and guard the boot data
fetches so the shell renders offline. Cold offline reload now boots the hub (verified).
SW VERSION v50→v51, asset stamp 76→77.

### 11b-4 Capacitor wrapper (`tests/test_capacitor_11b.py` 10/10)
New `mobile/`: `capacitor.config.json` (server.url → the alles host, shell loads the live PWA),
`package.json` (capacitor deps + add/sync/open/run scripts), `README.md` (iOS/Android build
steps), `www/index.html` (splash + unreachable-host fallback). Honest seam — no native
toolchain runs in this no-build repo, same approach as the 11a macOS bridge.

## Regression
`tests/pw_regression.py 8879` — all subdomain views clean, errors=0 (ALL CLEAN). The boot-path
changes (auth cache + guarded fetches) didn't regress online boot. pw_sync_1b still 9/9.

## Suite
`python -m unittest discover -s tests` → Ran 1713 tests, OK (skipped=1) (+23 vs 11a's 1690).

## Verdict
11b done end-to-end: phone-responsive drawer, polished installable manifest, genuine cold
offline boot, and a documented Capacitor shell.
