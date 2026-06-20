"""ui-8c verify — authenticator-app (TOTP) 2FA end to end: enrol in settings, then a locked unlock
demands the 6-digit code. Codes are computed here with the app's own totp_now."""

import os
import sys

sys.path.insert(0, os.getcwd())  # so we can import the app's totp helper

from playwright.sync_api import sync_playwright  # noqa: E402

from services.pwtools import totp_now  # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "8875"
BASE = f"http://secrets.localhost:{PORT}"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")


def run():
    fails, errs = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block", viewport={"width": 1280, "height": 860})
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#vault-view", state="attached", timeout=15000)
        pg.wait_for_timeout(1200)

        def ok(name, cond):
            print(f"PASS {name}") if cond else fails.append(name)

        # unlock (first unlock sets the master)
        pg.evaluate("""() => { document.getElementById('vault-pw-input').value='totpmaster';
          document.getElementById('vault-unlock-btn').click(); }""")
        pg.wait_for_function(
            "() => getComputedStyle(document.getElementById('vault-unlocked')).display !== 'none'",
            timeout=15000,
        )
        pg.wait_for_timeout(600)

        # open settings → 2FA panel with both methods + the explainer
        pg.evaluate("() => document.getElementById('vault-manage-btn').click()")
        pg.wait_for_selector("#mv-extra", state="attached", timeout=10000)
        pg.wait_for_timeout(400)
        panel = pg.evaluate("""() => ({
          hasKeyRow: !!document.getElementById('mv-2fa-add'),
          hasTotpSetup: !!document.getElementById('mv-totp-add'),
          explain: (document.querySelector('.mv-2fa-note')?.innerText || ''),
        })""")
        ok("2FA panel offers a passkey/security-key option", panel["hasKeyRow"])
        ok("2FA panel offers an authenticator-app (TOTP) option", panel["hasTotpSetup"])
        ok(
            "explainer distinguishes biometric vs passkey 2FA",
            "biometric" in panel["explain"].lower() and "second factor" in panel["explain"].lower(),
        )

        # start TOTP setup → read the secret shown
        pg.evaluate("() => document.getElementById('mv-totp-add').click()")
        pg.wait_for_selector("#totp-secret", state="attached", timeout=10000)
        secret = pg.evaluate("() => document.getElementById('totp-secret').textContent")
        ok("setup reveals a secret to scan", bool(secret) and len(secret) >= 16)

        # confirm with the current code
        pg.evaluate(
            "(c) => { document.getElementById('totp-code').value = c; "
            "document.getElementById('totp-ok').click(); }",
            totp_now(secret),
        )
        pg.wait_for_timeout(800)
        # the manage panel re-rendered; enrollment shows as a badge on the TOTP row
        badge = pg.evaluate("() => !!document.querySelector('#mv-extra .mv-badge.mv-main')")
        ok("authenticator app is now enrolled", badge)

        # lock, then unlock → it must demand the TOTP code
        pg.evaluate("() => document.getElementById('vault-lock-btn').click()")
        pg.wait_for_function(
            "() => getComputedStyle(document.getElementById('vault-locked')).display !== 'none'",
            timeout=10000,
        )
        pg.wait_for_timeout(400)
        pg.evaluate("""() => { document.getElementById('vault-pw-input').value='totpmaster';
          document.getElementById('vault-unlock-btn').click(); }""")
        pg.wait_for_selector("#cc-code", state="attached", timeout=10000)
        ok("a locked unlock now prompts for the authenticator code", True)

        # wrong code is rejected, correct code unlocks
        pg.evaluate(
            "() => { document.getElementById('cc-code').value='000000'; document.getElementById('cc-ok').click(); }"
        )
        pg.wait_for_timeout(600)
        stillLocked = pg.evaluate(
            "() => getComputedStyle(document.getElementById('vault-locked')).display !== 'none'"
        )
        ok("a wrong code does not unlock", stillLocked)

        # the prompt closed on the wrong code; re-open by clicking unlock again
        pg.evaluate("""() => { document.getElementById('vault-pw-input').value='totpmaster';
          document.getElementById('vault-unlock-btn').click(); }""")
        pg.wait_for_selector("#cc-code", state="attached", timeout=10000)
        pg.evaluate(
            "(c) => { document.getElementById('cc-code').value=c; document.getElementById('cc-ok').click(); }",
            totp_now(secret),
        )
        pg.wait_for_function(
            "() => getComputedStyle(document.getElementById('vault-unlocked')).display !== 'none'",
            timeout=10000,
        )
        ok("the correct authenticator code unlocks the vault", True)

        real = [e for e in errs if not any(s in e for s in IGNORE)]
        ok("no console errors", not real)
        if real:
            print("ERRORS", real)
        b.close()
    if fails:
        print("\nFAILED:", fails)
        sys.exit(1)
    print("\nALL GREEN")


if __name__ == "__main__":
    run()
