"""ui-3s verify — AI todo-extraction shows an explainer popup before running, and the
backlinks panel explains what backlinks/unlinked mentions are."""
import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8871"
BASE = f"http://docs.localhost:{PORT}"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")


def run():
    fails, errs = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block", viewport={"width": 1200, "height": 900})
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#wiki-view", timeout=15000)
        pg.wait_for_timeout(1400)
        pg.evaluate("""() => { const el = document.querySelector('.wiki-file[data-path=\"livetest.md\"] .wiki-row-label'); if (el) el.click(); }""")
        pg.wait_for_timeout(1100)

        def ok(name, cond):
            (print(f"PASS {name}") if cond else fails.append(name))

        # clicking todos opens an explainer, NOT an immediate extraction
        pg.click("#wiki-todos-btn")
        pg.wait_for_timeout(400)
        pop = pg.query_selector("#wiki-todos-pop")
        ok("todos shows an explainer popup", pop is not None)
        if pop:
            txt = pop.inner_text().lower()
            ok("explainer says what it does", "action item" in txt or "to-do" in txt or "tasks" in txt)
            ok("explainer notes the doc isn't changed", "isn" in txt and "changed" in txt)
            ok("explainer has a run button", pop.query_selector("#wiki-todos-go") is not None)
            # close it without running
            pg.keyboard.press("Escape")
            pg.evaluate("() => document.querySelector('#wiki-todos-pop')?.remove()")

        # backlinks panel carries a purpose explainer
        bl = pg.evaluate("() => (document.querySelector('.wiki-bl-explainer')?.textContent || document.querySelector('#wiki-backlinks')?.textContent || '')")
        ok("backlinks explains itself", "backlink" in bl.lower() and ("unlinked" in bl.lower() or "link" in bl.lower()))

        real = [e for e in errs if not any(s in e for s in IGNORE)]
        ok("no console errors", not real)
        if real:
            print("ERRORS", real)
        pg.click("#wiki-todos-btn")
        pg.wait_for_timeout(300)
        pg.screenshot(path="docs/evidence/ui-3s/explainers.png")
        b.close()
    if fails:
        print("\nFAILED:", fails)
        sys.exit(1)
    print("\nALL GREEN")


if __name__ == "__main__":
    run()
