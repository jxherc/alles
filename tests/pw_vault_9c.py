"""9c UI — multiple vaults (switcher + create + switch), Travel Mode toggle,
biometric enable / lock-screen biometric-unlock affordance.
secrets.localhost:8870.  ALLES_DATA=/tmp/alles9c PORT=8870 AUTH_ENABLED=false python app.py
"""

import json
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

SEC = "http://secrets.localhost:8870"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "9c"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "403", "Load failed")
MASTER = "master-9c"


def _api(path, body, token=None):
    h = {"content-type": "application/json"}
    if token:
        h["X-Vault-Token"] = token
    req = urllib.request.Request(
        f"http://127.0.0.1:8870{path}", data=json.dumps(body).encode(), headers=h, method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    r = {}
    errs = []
    tok = _api("/api/vault/unlock", {"password": MASTER})["token"]
    _api(
        "/api/vault", {"name": "GitHub", "type": "login", "fields": {"password": "x9$Kf2!qZ7"}}, tok
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
        pg.wait_for_timeout(400)  # let _refreshBioUnlock settle

        # ---- lock-screen biometric button hidden (no credential registered) ----
        r["biometric_unlock_hidden_without_credential"] = not pg.is_visible("#vault-bio-unlock-btn")

        # ---- unlock the default vault ----
        pg.fill("#vault-pw-input", MASTER)
        pg.eval_on_selector("#vault-unlock-btn", "el => el.click()")
        pg.wait_for_selector(".vault-entry", timeout=10000)
        pg.wait_for_timeout(300)

        # ---- the multi-vault controls are present once unlocked ----
        r["vault_switcher_present"] = pg.is_visible("#vault-switcher")
        r["vault_add_button_present"] = pg.is_visible("#vault-add-btn")
        r["travel_toggle_present"] = pg.is_visible("#vault-travel-btn")
        r["biometric_enable_present"] = pg.is_visible("#vault-bio-add-btn")
        pg.screenshot(path=str(EVID / "switcher.png"))

        # ---- create a new vault → auto-switches into it (empty list) ----
        pg.eval_on_selector("#vault-add-btn", "el => el.click()")
        pg.wait_for_selector("#nv-name", timeout=6000)
        pg.fill("#nv-name", "Work")
        pg.fill("#nv-pw", "workpass")
        pg.screenshot(path=str(EVID / "create-vault.png"))
        pg.eval_on_selector("#nv-create", "el => el.click()")
        pg.wait_for_selector(".page-empty", timeout=8000)  # Work is empty
        pg.wait_for_timeout(300)
        r["create_vault_adds_to_switcher"] = "Work" in (pg.text_content("#vault-switcher") or "")
        r["switched_into_empty_vault"] = pg.query_selector(".vault-entry") is None

        # ---- switch back to the default vault (password prompt) → its entry returns ----
        pg.eval_on_selector(
            "#vault-switcher",
            "el => { el.value = 'default'; el.dispatchEvent(new Event('change', {bubbles:true})); }",
        )
        pg.wait_for_selector("#pp-pw", timeout=6000)
        pg.fill("#pp-pw", MASTER)
        pg.eval_on_selector("#pp-ok", "el => el.click()")
        pg.wait_for_selector(".vault-entry", timeout=8000)
        r["switch_vault_shows_its_entries"] = "GitHub" in (
            pg.text_content("#vault-entry-list") or ""
        )

        # ---- flag Work travel-safe in the manage modal; reopen → it persists ----
        pg.eval_on_selector("#vault-manage-btn", "el => el.click()")
        pg.wait_for_selector("[data-travel]", timeout=6000)
        pg.eval_on_selector(
            "#mv-list",
            """el => {
                const rows = [...el.querySelectorAll('.mv-row')];
                const work = rows.find(r => r.querySelector('.mv-name').textContent.includes('Work'));
                work.querySelector('[data-travel]').click();
            }""",
        )
        pg.wait_for_timeout(500)
        pg.screenshot(path=str(EVID / "manage.png"))
        pg.eval_on_selector("#mv-close", "el => el.click()")
        pg.wait_for_timeout(200)
        pg.eval_on_selector("#vault-manage-btn", "el => el.click()")
        pg.wait_for_selector("[data-travel]", timeout=6000)
        persisted = pg.eval_on_selector(
            "#mv-list",
            """el => {
                const rows = [...el.querySelectorAll('.mv-row')];
                const work = rows.find(r => r.querySelector('.mv-name').textContent.includes('Work'));
                return work.querySelector('[data-travel]').classList.contains('on');
            }""",
        )
        r["travel_flag_persists"] = bool(persisted)
        pg.eval_on_selector("#mv-close", "el => el.click()")

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_vault_9c.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
