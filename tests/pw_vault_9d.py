"""9d UI — passkey item type (create + list), require-security-key (2FA) toggle,
autofill / browser-extension affordance.  secrets.localhost:8871.
ALLES_DATA=/tmp/alles9d PORT=8871 AUTH_ENABLED=false python app.py
"""

import json
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

SEC = "http://secrets.localhost:8871"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "9d"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "403", "Load failed")
MASTER = "master-9d"


def _api(path, body, token=None):
    h = {"content-type": "application/json"}
    if token:
        h["X-Vault-Token"] = token
    req = urllib.request.Request(
        f"http://127.0.0.1:8871{path}", data=json.dumps(body).encode(), headers=h, method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    r = {}
    errs = []
    _api("/api/vault/unlock", {"password": MASTER})  # set the master

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
        pg.wait_for_selector("#vault-new-btn", timeout=10000)
        pg.wait_for_timeout(300)

        # ---- passkey type present in the new-item form ----
        pg.eval_on_selector("#vault-new-btn", "el => el.click()")
        pg.wait_for_selector("#vf-type", timeout=6000)
        r["passkey_type_present"] = "Passkey" in (
            pg.get_attribute("#vf-type", "data-options") or ""
        )

        # ---- create a passkey → keypair minted server-side, entry appears ----
        pg.eval_on_selector(
            "#vf-type",
            "el => { el.value = 'passkey'; el.dispatchEvent(new Event('change', {bubbles:true})); }",
        )
        pg.wait_for_selector("#vf-f-rp_id", timeout=6000)
        pg.fill("#vf-name", "GitHub passkey")
        pg.fill("#vf-f-rp_id", "github.com")
        pg.fill("#vf-f-username", "octocat")
        pg.screenshot(path=str(EVID / "passkey-form.png"))
        pg.eval_on_selector("#vf-save", "el => el.click()")
        pg.wait_for_selector(".vault-entry", timeout=8000)
        pg.wait_for_timeout(300)
        list_txt = pg.text_content("#vault-entry-list") or ""
        r["create_passkey_adds_entry"] = "github.com" in list_txt
        r["passkey_listed"] = "Passkey" in list_txt  # the type label shows on the row
        pg.screenshot(path=str(EVID / "passkey-list.png"))

        # ---- 2FA toggle in manage modal + autofill affordance ----
        pg.eval_on_selector("#vault-manage-btn", "el => el.click()")
        pg.wait_for_selector("#mv-2fa", timeout=6000)
        r["twofa_toggle_present"] = pg.is_visible("#mv-2fa")
        r["autofill_info_present"] = pg.is_visible("#vault-autofill-info")
        r["extension_link_present"] = pg.is_visible("#vault-ext-link")
        pg.screenshot(path=str(EVID / "manage-2fa.png"))

        # toggle 2FA on → close → reopen → still on (persisted server-side)
        pg.eval_on_selector("#mv-2fa", "el => el.click()")
        pg.wait_for_timeout(400)
        pg.eval_on_selector("#mv-close", "el => el.click()")
        pg.wait_for_timeout(200)
        pg.eval_on_selector("#vault-manage-btn", "el => el.click()")
        pg.wait_for_selector("#mv-2fa", timeout=6000)
        pg.wait_for_timeout(300)
        r["twofa_toggle_persists"] = "on" in (pg.get_attribute("#mv-2fa", "class") or "")
        pg.eval_on_selector("#mv-close", "el => el.click()")

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_vault_9d.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
