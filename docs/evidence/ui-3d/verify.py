"""ui-3d verify — the docs image toolbar button opens an insert dialog (paste URL
or upload a file) instead of dumping a raw ![](url) placeholder."""
import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8871"
BASE = f"http://docs.localhost:{PORT}"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")


def run():
    fails, errs = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block", viewport={"width": 1100, "height": 1300})
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#wiki-view", timeout=15000)
        pg.wait_for_timeout(1400)
        pg.evaluate("""() => {
          const el = document.querySelector('.wiki-file[data-path=\"livetest.md\"] .wiki-row-label');
          if (el) el.click();
        }""")
        pg.wait_for_timeout(1200)

        def ok(name, cond):
            (print(f"PASS {name}") if cond else fails.append(name))

        # click the img toolbar button
        pg.click('.dt-btn[data-fmt="image"]')
        pg.wait_for_timeout(400)
        pop = pg.query_selector("#wiki-img-pop")
        ok("image dialog opens", pop is not None)
        urlbox = pg.query_selector("#wiki-img-url")
        ok("has a url field", urlbox is not None)
        ok("has an upload option", pg.query_selector("#wiki-img-file") is not None
           or pg.query_selector("#wiki-img-upload") is not None)
        if urlbox:
            urlbox.fill("https://example.com/pic.png")
            pg.click("#wiki-img-insert")
            pg.wait_for_timeout(400)
            src = pg.evaluate("() => document.querySelector('#wiki-source')?.value || ''")
            ok("url inserted as markdown image", "](https://example.com/pic.png)" in src)
            ok("dialog closed after insert", pg.query_selector("#wiki-img-pop") is None)

        real = [e for e in errs if not any(s in e for s in IGNORE)]
        ok("no console errors", not real)
        if real:
            print("ERRORS", real)
        pg.screenshot(path="docs/evidence/ui-3d/dialog.png")
        b.close()
    if fails:
        print("\nFAILED:", fails)
        sys.exit(1)
    print("\nALL GREEN")


if __name__ == "__main__":
    run()
