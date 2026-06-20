"""11c-2 — alles↔aide unification sweep. One server, walk every subdomain and assert each
boots into the right *scope* (apex = hub, aide = the full rail, every other app = a scoped
subapp with just its crumb), the right app is active, and nothing logs a console error. Then
verify the cross-jump: clicking the crumb on a subapp navigates back toward the hub.

  ALLES_DATA=.tmp_11c PORT=8880 AUTH_ENABLED=false python app.py
  python tests/pw_unify_11c.py
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PORT = "8880"
BASE = f"localhost:{PORT}"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "11c"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")

# sub → expected body.dataset.app + scope class
HOSTS = {
    "": ("alles", "is-hub"),
    "aide": ("aide", "is-aide"),
    "mail": ("mail", "is-subapp"),
    "docs": ("docs", "is-subapp"),
    "gallery": ("gallery", "is-subapp"),
    "calendar": ("calendar", "is-subapp"),
    "tasks": ("tasks", "is-subapp"),
    "subs": ("subs", "is-subapp"),
    "money": ("money", "is-subapp"),
    "days": ("days", "is-subapp"),
    "journal": ("journal", "is-subapp"),
    "activity": ("activity", "is-subapp"),
    "system": ("system", "is-subapp"),
    "files": ("files", "is-subapp"),
    "contacts": ("contacts", "is-subapp"),
    "secrets": ("secrets", "is-subapp"),
}


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    r = {}
    all_errs = {}
    scope_ok = {}
    boot_ok = {}
    app_ok = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        for sub, (want_app, want_scope) in HOSTS.items():
            host = f"{sub}.{BASE}" if sub else BASE
            pg = b.new_page()
            errs = []
            pg.on(
                "console",
                lambda m, e=errs: (
                    e.append(m.text)
                    if m.type == "error" and not any(x in m.text for x in IGNORE)
                    else None
                ),
            )
            pg.on(
                "pageerror",
                lambda ex, e=errs: (
                    e.append(str(ex)) if not any(x in str(ex) for x in IGNORE) else None
                ),
            )
            pg.goto(f"http://{host}/", wait_until="domcontentloaded", timeout=20000)
            # hub is chrome-less; subapps/aide show .app — either way wait for boot to finish
            pg.wait_for_function(
                "() => !document.body.classList.contains('preboot')", timeout=15000
            )
            pg.wait_for_timeout(900)
            boot_ok[sub] = not pg.evaluate("() => document.body.classList.contains('login-mode')")
            scope_ok[sub] = pg.evaluate(f"() => document.body.classList.contains('{want_scope}')")
            app_ok[sub] = pg.evaluate("() => document.body.dataset.app") == want_app
            all_errs[sub] = errs
            pg.close()
        # ── specific scope details ──────────────────────────────────────────────
        # aide shows the rail; a subapp hides it and shows the crumb instead
        aide = b.new_page()
        aide.goto(f"http://aide.{BASE}/", wait_until="domcontentloaded")
        aide.wait_for_selector(".app", timeout=15000)
        aide.wait_for_timeout(700)
        r["sidebar_visible_on_aide"] = aide.is_visible(".sidebar")
        aide.close()

        mail = b.new_page()
        mail.goto(f"http://mail.{BASE}/", wait_until="domcontentloaded")
        mail.wait_for_selector(".app", timeout=15000)
        mail.wait_for_timeout(700)
        r["sidebar_hidden_on_subapp"] = not mail.is_visible(".sidebar")
        r["crumb_present_on_subapp"] = mail.is_visible("#app-crumb")
        # cross-jump: clicking the crumb leaves the subdomain back toward the hub
        mail.eval_on_selector("#app-crumb", "el => el.click()")
        mail.wait_for_timeout(1500)
        landed = mail.evaluate("() => location.hostname")
        r["crossjump_back_to_hub"] = landed == "localhost"
        mail.screenshot(path=str(EVID / "unify-crossjump.png"))
        mail.close()
        b.close()

    r["apex_is_hub"] = scope_ok.get("") is True
    r["aide_is_aide"] = scope_ok.get("aide") is True
    r["subapps_are_subapp"] = all(scope_ok[s] for s in HOSTS if HOSTS[s][1] == "is-subapp")
    r["every_host_boots"] = all(boot_ok.values())
    r["right_app_active_each_host"] = all(app_ok.values())
    total_errs = sum(len(e) for e in all_errs.values())
    r["every_host_zero_errors"] = total_errs == 0

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    bad = {s: e for s, e in all_errs.items() if e}
    if bad:
        lines.append(f"errors_by_host: {bad}")
    failed_scope = [s for s in HOSTS if not scope_ok.get(s)]
    if failed_scope:
        lines.append(f"scope_fail: {failed_scope}")
    out = "\n".join(lines)
    (EVID / "pw_unify_11c.txt").write_text(out, encoding="utf-8")
    print(out)
    print(
        f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed  ({len(HOSTS)} hosts swept)"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
