"""ui-7c verify — journal 'lock now' actually locks: the action menu is an anchored dropdown near the
lock button, picking 'lock now' shows the lock screen and gates the data; lock chrome uses icons."""

import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8873"
BASE = f"http://journal.localhost:{PORT}"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")


def run():
    fails, errs = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block", viewport={"width": 1280, "height": 860})
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#journal-body", state="attached", timeout=15000)
        pg.wait_for_timeout(700)

        # reset to a known passcode, hold a token, reload into the unlocked journal
        pg.evaluate("""async () => {
          for (const pc of ['1234','0000']) await fetch('/api/journal/lock/disable',
            {method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({passcode:pc})});
          await fetch('/api/journal/lock/set',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({passcode:'1234'})});
          const u = await fetch('/api/journal/unlock',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({passcode:'1234'})});
          sessionStorage.setItem('journal_token', (await u.json()).token);
        }""")
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_selector("#jrnl-lock", state="attached", timeout=15000)
        pg.wait_for_timeout(900)

        def ok(name, cond):
            print(f"PASS {name}") if cond else fails.append(name)

        unlocked = pg.evaluate("""() => {
          const btn = document.getElementById('jrnl-lock');
          return {
            enabled: btn ? btn.dataset.enabled : '',
            btnIcon: !!(btn && btn.querySelector('svg.ic')),
            onLockScreen: !!document.querySelector('.jrnl-lock'),
          };
        }""")
        ok("journal is unlocked (entry shell shown)", not unlocked["onLockScreen"])
        ok("lock button shows 'lock now' state", unlocked["enabled"] == "1")
        ok("lock button uses an svg icon", unlocked["btnIcon"])

        # click the lock button → anchored dropdown appears near it
        menu = pg.evaluate("""async () => {
          const btn = document.getElementById('jrnl-lock');
          const br = btn.getBoundingClientRect();
          btn.click();
          await new Promise(r => setTimeout(r, 300));
          const m = document.querySelector('.jrnl-lockmenu');
          if (!m) return { shown: false };
          const mr = m.getBoundingClientRect();
          return {
            shown: true,
            fixed: getComputedStyle(m).position === 'fixed',
            nearButton: Math.abs(mr.top - br.bottom) < 30 && Math.abs(mr.left - br.left) < 60,
            inReflection: !!m.closest('#jrnl-reflection'),
            hasLockNow: !!m.querySelector('[data-a="lock"]'),
          };
        }""")
        ok("lock menu appears", menu["shown"])
        ok("menu is an anchored fixed dropdown", menu.get("fixed"))
        ok("menu sits right under the lock button", menu.get("nearButton"))
        ok("menu is NOT buried in the reflection panel", not menu.get("inReflection"))
        ok("menu offers 'lock now'", menu.get("hasLockNow"))

        # pick 'lock now' → journal locks: lock screen shows + data endpoint 403s
        locked = pg.evaluate("""async () => {
          document.querySelector('.jrnl-lockmenu [data-a="lock"]').click();
          await new Promise(r => setTimeout(r, 600));
          const tok = sessionStorage.getItem('journal_token');
          const st = await fetch('/api/journal/2026-06-20',
            { headers: tok ? {'X-Journal-Token': tok} : {} }).then(r => r.status);
          return {
            lockScreen: !!document.querySelector('.jrnl-lock'),
            tokenCleared: !tok,
            dataStatus: st,
            screenIcon: !!document.querySelector('.jrnl-lock-icon svg.ic'),
          };
        }""")
        ok("lock now shows the lock screen", locked["lockScreen"])
        ok("lock now clears the unlock token", locked["tokenCleared"])
        ok("data endpoint is gated (403) after locking", locked["dataStatus"] == 403)
        ok("lock screen uses an svg icon", locked["screenIcon"])

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
