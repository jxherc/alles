# alles — mobile (Capacitor wrapper)

Optional native iOS/Android shell around the self-hosted **alles** PWA. The shell doesn't
bundle the app — it points at your running alles server (`server.url` in
`capacitor.config.json`) and loads the live PWA, so you get a home-screen app with a native
splash, status bar, and push wiring while the actual app stays the one Python process you
already run. This mirrors the "honest seam" approach: nothing here runs in the no-build repo;
it's the wiring you'd use on a Mac/Linux box with Node + Xcode/Android Studio installed.

## One-time

```bash
cd mobile
npm install
# point the shell at your alles host (LAN IP or your real BASE_DOMAIN):
#   edit capacitor.config.json -> server.url
npx cap add ios       # or: npm run add:ios       (needs macOS + Xcode)
npx cap add android   # or: npm run add:android    (needs Android Studio)
```

## Build / run

```bash
npm run sync          # npx cap sync — copy config + plugins into the native projects
npm run open:ios      # open Xcode  → run on a device/simulator
npm run open:android  # open Android Studio → run
# or straight to a connected device:
npm run run:ios
npm run run:android
```

## Notes

- **Production:** set `server.url` to your HTTPS `BASE_DOMAIN` and drop `cleartext`/
  `allowMixedContent`. The LAN `http://…:8000` default is dev-only.
- **Auth:** the per-host login + `/api/auth/handoff` relay (see `core/auth.py`) works the same
  inside the webview; the subdomain SPA scoping is unchanged.
- **Offline:** the service worker (`static/sw.js`) and its IndexedDB write-queue run inside the
  Capacitor webview exactly as in a browser — offline edits queue and replay on reconnect.
- **Icons/splash:** generate from `static/icons/` with `@capacitor/assets` if you want native
  launch images; the `www/index.html` here is just the pre-load splash + unreachable-host fallback.
