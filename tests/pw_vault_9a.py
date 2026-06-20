"""9a UI — TOTP live code + countdown on reveal, Watchtower (weak/reused/breached) panel.
secrets.localhost:8868.  ALLES_DATA=/tmp/alles9a PORT=8868 AUTH_ENABLED=false python app.py
"""

import json
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

SEC = "http://secrets.localhost:8868"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "9a"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "Load failed")
MASTER = "master-9a"
RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


def _api(path, body, token=None):
    h = {"content-type": "application/json"}
    if token:
        h["X-Vault-Token"] = token
    req = urllib.request.Request(
        f"http://127.0.0.1:8868{path}", data=json.dumps(body).encode(), headers=h, method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    r = {}
    errs = []
    # seed the vault directly (sets master on first unlock), then add entries
    tok = _api("/api/vault/unlock", {"password": MASTER})["token"]
    _api("/api/vault", {"name": "WeakLogin", "type": "login", "fields": {"password": "123"}}, tok)
    _api(
        "/api/vault",
        {"name": "ReuseA", "type": "login", "fields": {"password": "SharedStrong-9!"}},
        tok,
    )
    _api(
        "/api/vault",
        {"name": "ReuseB", "type": "login", "fields": {"password": "SharedStrong-9!"}},
        tok,
    )
    _api(
        "/api/vault",
        {
            "name": "TotpLogin",
            "type": "login",
            "fields": {"password": "x9$Kf2!qZ7", "totp": RFC_SECRET},
        },
        tok,
    )

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context().new_page()
        pg.on(
            "console",
            lambda m: (
                errs.append(m.text)
                if m.type == "error" and not any(x in m.text for x in IGNORE)
                else None
            ),
        )
        pg.on(
            "pageerror",
            lambda e: errs.append(str(e)) if not any(x in str(e) for x in IGNORE) else None,
        )

        pg.goto(f"{SEC}/", wait_until="domcontentloaded")
        pg.wait_for_selector("#vault-pw-input", timeout=15000)
        pg.fill("#vault-pw-input", MASTER)
        pg.eval_on_selector("#vault-unlock-btn", "el => el.click()")
        pg.wait_for_selector(".vault-entry", timeout=10000)

        # ---- watchtower button visible ----
        r["watchtower_button"] = pg.is_visible("#vault-watchtower-btn")

        # ---- new-entry form has a TOTP field ----
        pg.eval_on_selector("#vault-new-btn", "el => el.click()")
        pg.wait_for_selector("#vf-f-totp", timeout=6000)
        r["totp_field_in_form"] = pg.query_selector("#vf-f-totp") is not None
        pg.eval_on_selector("#vf-cancel", "el => el.click()")
        pg.wait_for_timeout(200)

        # ---- reveal the TOTP entry → live code + countdown ----
        pg.eval_on_selector(".vault-entry:has-text('TotpLogin')", "el => el.click()")
        pg.wait_for_selector(".vault-totp-code", timeout=8000)
        # wait until the code is populated (not the dots placeholder)
        for _ in range(20):
            txt = pg.text_content(".vault-totp-code") or ""
            if any(ch.isdigit() for ch in txt):
                break
            pg.wait_for_timeout(300)
        code = pg.text_content(".vault-totp-code") or ""
        r["totp_code_shows_on_reveal"] = sum(ch.isdigit() for ch in code) == 6
        r["totp_countdown"] = "s" in (pg.text_content(".vault-totp-secs") or "")
        pg.screenshot(path=str(EVID / "totp.png"))
        pg.eval_on_selector("#vf-cancel", "el => el.click()")
        pg.wait_for_timeout(200)

        # ---- watchtower panel ----
        pg.eval_on_selector("#vault-watchtower-btn", "el => el.click()")
        pg.wait_for_selector(".vault-wt", timeout=10000)
        panel = pg.text_content(".vault-wt") or ""
        r["watchtower_renders"] = "breached" in panel and "reused" in panel and "weak" in panel
        r["watchtower_lists_weak"] = "WeakLogin" in panel
        r["watchtower_lists_reused"] = "ReuseA" in panel and "ReuseB" in panel
        pg.screenshot(path=str(EVID / "watchtower.png"))

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_vault_9a.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
