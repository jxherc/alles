"""ui-3p verify — exported HTML keeps tables, links and code (and the export stylesheet
styles them), so the export matches what live/preview shows."""
import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8871"
BASE = f"http://docs.localhost:{PORT}"


def run():
    fails = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block", accept_downloads=True)
        pg = ctx.new_page()
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#wiki-view", timeout=15000)
        pg.wait_for_timeout(1400)
        pg.evaluate("""() => { const el = document.querySelector('.wiki-file[data-path=\"livetest.md\"] .wiki-row-label'); if (el) el.click(); }""")
        pg.wait_for_timeout(1000)
        pg.click("#wiki-export-btn")
        pg.wait_for_timeout(300)
        with pg.expect_download() as dl_info:
            pg.eval_on_selector("#wiki-export-pop [data-x='html']", "el => el.click()")
        path = dl_info.value.path()
        html = open(path, encoding="utf-8").read()

        def ok(name, cond):
            (print(f"PASS {name}") if cond else fails.append(name))

        ok("export contains a real table", "<table" in html and "<th" in html and "Ada" in html)
        ok("export keeps the link with its href", 'href="https://example.com/some/long/url"' in html)
        ok("export keeps the link text", "visible link text" in html)
        ok("export keeps fenced code", "<pre" in html and "const x = 1" in html)
        ok("export keeps inline code", "<code" in html)
        ok("export keeps the callout", "md-callout" in html)
        ok("export embeds images", "<img" in html)
        # the export stylesheet styles tables/links/code
        ok("export css borders table cells", "th,td{border:1px" in html.replace(" ", ""))
        ok("export css colours links", "a{color:" in html.replace(" ", ""))
        ok("export css styles code blocks", "pre{" in html.replace(" ", ""))
        print("export bytes:", len(html))
        b.close()
    if fails:
        print("FAILED:", fails)
        sys.exit(1)
    print("ALL GREEN")


if __name__ == "__main__":
    run()
