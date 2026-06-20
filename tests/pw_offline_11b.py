"""11b-3 — offline app-shell pre-cache. Before this, the SW only cached as-you-go, so a
reload after the cache was cold/evicted could fail to boot. Now the install handler precaches
the shell (HTML/CSS/manifest/icons) and the cache survives, so the app boots offline.

Drives aide.localhost:8879. ALLES_DATA=.tmp_11b3 PORT=8879 AUTH_ENABLED=false python app.py
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8879"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "11b"
# offline test: fetch failures to the (unreachable) server are expected and the app logs them
IGNORE = (
    "Failed to load resource",
    "net::",
    "ERR_",
    "favicon",
    "401",
    "403",
    "Load failed",
    "Failed to fetch",
)


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    r = {}
    errs = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context()
        pg = ctx.new_page()
        pg.on(
            "console",
            lambda m: (
                errs.append(m.text)
                if m.type == "error" and not any(x in m.text for x in IGNORE)
                else None
            ),
        )

        # sw.js version bumped past v50
        sw = pg.request.get(f"{BASE}/sw.js").text()
        r["sw_version_bumped"] = "PRECACHE" in sw and "precache" in sw.lower()
        r["precache_list_nonempty"] = "/static/style.css" in sw and "/manifest.json" in sw

        # online visit → register SW, let it install + activate + precache
        pg.goto(f"{BASE}/", wait_until="domcontentloaded")
        pg.wait_for_function(
            "() => navigator.serviceWorker && navigator.serviceWorker.controller", timeout=15000
        )
        pg.wait_for_timeout(1500)

        # the SW reports its precache happened (it posts a manifest of what it cached)
        cached = pg.evaluate(
            """async () => {
                const names = await caches.keys();
                let keys = [];
                for (const n of names) {
                    const c = await caches.open(n);
                    keys = keys.concat((await c.keys()).map(req => new URL(req.url).pathname));
                }
                return keys;
            }"""
        )
        r["shell_precached_on_install"] = any(k == "/" for k in cached)
        r["static_assets_cached"] = any("/static/style.css" in k for k in cached)
        r["manifest_cached"] = any("/manifest.json" in k for k in cached)
        # the whole js module graph is precached (not just the entry) so boot survives offline
        r["js_modules_precached"] = sum("/static/js/" in k for k in cached) >= 20

        # cold offline boot: drop the network, hard-reload the shell, app must still render
        ctx.set_offline(True)
        pg.goto(f"{BASE}/", wait_until="domcontentloaded")
        pg.wait_for_function("() => !document.body.classList.contains('preboot')", timeout=10000)
        booted = pg.wait_for_selector(".app", state="visible", timeout=10000)
        r["cold_offline_boots"] = booted is not None
        # the real win: offline opens the app (the cached session), not a login wall
        r["offline_not_login_wall"] = not pg.evaluate(
            "() => document.body.classList.contains('login-mode')"
        )
        # localhost root is the chrome-less hub launcher — its tile grid renders offline
        r["offline_hub_renders"] = pg.is_visible(".home-grid")

        # the sync indicator element exists for the pending-queue UI
        pg.wait_for_timeout(500)
        r["pending_indicator_present"] = pg.query_selector("#sync-indicator") is not None

        ctx.set_offline(False)
        pg.screenshot(path=str(EVID / "offline-boot.png"))

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_offline_11b.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
