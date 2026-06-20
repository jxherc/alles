"""ui-5a verify — the files app shows free disk space prominently in the quota bar."""
import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8871"
BASE = f"http://files.localhost:{PORT}"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")


def run():
    fails, errs = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block", viewport={"width": 1200, "height": 850})
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#files-view", state="attached", timeout=15000)
        pg.wait_for_selector("#files-quota", state="attached", timeout=15000)
        pg.wait_for_timeout(1500)

        def ok(name, cond):
            (print(f"PASS {name}") if cond else fails.append(name))

        d = pg.evaluate("""() => {
          const q = document.querySelector('#files-quota');
          const free = document.querySelector('.files-quota-free');
          return {
            present: !!q,
            text: q ? q.textContent : '',
            freeShown: !!free,
            freeText: free ? free.textContent : '',
            freeColor: free ? getComputedStyle(free).color : '',
            barFill: !!document.querySelector('.files-quota-fill'),
          };
        }""")
        ok("quota bar is present", d["present"])
        ok("free space is shown prominently", d["freeShown"] and "free" in d["freeText"].lower())
        ok("free space carries a real size", any(u in d["freeText"] for u in ("B", "KB", "MB", "GB", "TB")))
        ok("free space is colour-highlighted (green)", d["freeColor"] not in ("", "rgb(110, 110, 110)"))
        ok("still shows used + total", "used" in d["text"] and "of" in d["text"])
        ok("the usage bar renders", d["barFill"])

        real = [e for e in errs if not any(s in e for s in IGNORE)]
        ok("no console errors", not real)
        if real:
            print("ERRORS", real)
        pg.screenshot(path="docs/evidence/ui-5a/quota.png")
        print("quota text:", d["text"])
        b.close()
    if fails:
        print("\nFAILED:", fails)
        sys.exit(1)
    print("\nALL GREEN")


if __name__ == "__main__":
    run()
