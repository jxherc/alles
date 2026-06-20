"""ui-7e verify — the day-cluster apps render control glyphs as real <svg class=ic>, not emoji:
tasks repeat badge + journal reflect button (both verified live in their own fresh context).
days + calendar base views are account-gated on this server; their swaps are covered by the
source-contract gate test tests/test_dayapps_icons.py."""

import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8873"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")

fails, errs = [], []


def host(sub):
    return f"http://{sub}.localhost:{PORT}"


def ok(name, cond):
    print(f"PASS {name}") if cond else fails.append(name)


def fresh(b):
    ctx = b.new_context(service_workers="block", viewport={"width": 1280, "height": 860})
    pg = ctx.new_page()
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    return pg


def run():
    with sync_playwright() as p:
        b = p.chromium.launch()

        # ── tasks: a repeating task shows the refresh icon ──
        pg = fresh(b)
        pg.goto(host("tasks") + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#tasks-view", state="attached", timeout=15000)
        pg.wait_for_timeout(500)
        pg.evaluate("""async () => {
          await fetch('/api/tasks',{method:'POST',headers:{'content-type':'application/json'},
            body:JSON.stringify({title:'water plants',repeat:'weekly'})});
        }""")
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_selector(".task-repeat", state="attached", timeout=15000)
        pg.wait_for_timeout(500)
        t = pg.evaluate("""() => {
          const rep = document.querySelector('.task-repeat');
          return { svg: !!(rep && rep.querySelector('svg.ic')), text: document.getElementById('tasks-list').innerText };
        }""")
        ok("repeating task renders a repeat icon", t["svg"])
        ok("no repeat emoji in the tasks list", "🔁" not in t["text"])

        # ── journal: reflect button uses the sparkles icon (built via the unlock path) ──
        pg = fresh(b)
        pg.goto(host("journal") + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#journal-body", state="attached", timeout=15000)
        pg.wait_for_timeout(500)
        pg.evaluate("""async () => {
          for (const pc of ['1234','0000']) await fetch('/api/journal/lock/disable',
            {method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({passcode:pc})});
          await fetch('/api/journal/lock/set',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({passcode:'1234'})});
          const u = await fetch('/api/journal/unlock',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({passcode:'1234'})});
          sessionStorage.setItem('journal_token', (await u.json()).token);
        }""")
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_selector("#jrnl-reflect", state="attached", timeout=15000)
        pg.wait_for_timeout(500)
        j = pg.evaluate("""() => {
          const r = document.getElementById('jrnl-reflect');
          return { svg: !!(r && r.querySelector('svg.ic')), text: r ? r.textContent : '' };
        }""")
        ok("journal reflect button uses an icon", j["svg"])
        ok("no sparkles emoji on the reflect button", "✨" not in j["text"])

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
