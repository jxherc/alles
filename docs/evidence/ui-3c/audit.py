"""ui-3c audit — open livetest.md in docs, switch to live mode, capture how each
markdown element currently renders (RED state for the live-preview engine work)."""
import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8871"
BASE = f"http://docs.localhost:{PORT}"
OUT = "docs/evidence/ui-3c"


def run():
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block", viewport={"width": 1100, "height": 1400})
        pg = ctx.new_page()
        errs = []
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#wiki-view", timeout=15000)
        # open the doc from the tree
        pg.wait_for_timeout(1200)
        # open the doc — fire the delegated click on its tree row (row may be in a collapsed panel)
        pg.evaluate("""() => {
          const el = document.querySelector('.wiki-file[data-path=\"livetest.md\"] .wiki-row-label');
          if (el) el.click();
        }""")
        pg.wait_for_timeout(1200)
        # ensure live mode
        mode = pg.query_selector("#wiki-mode-toggle")
        if mode:
            for _ in range(3):
                txt = (mode.inner_text() or "").lower()
                if "live" in txt:
                    break
                mode.click()
                pg.wait_for_timeout(400)
        pg.wait_for_timeout(1000)
        # dump the live editor DOM summary
        info = pg.evaluate("""() => {
          const c = document.querySelector('.cm-content');
          if (!c) return {error:'no .cm-content'};
          return {
            text: c.innerText.slice(0, 1200),
            imgs: c.querySelectorAll('img').length,
            tables: c.querySelectorAll('table').length,
            checkboxes: c.querySelectorAll('input[type=checkbox]').length,
            callouts: c.querySelectorAll('.cm-callout,.cm-callout-block').length,
            links: [...c.querySelectorAll('a')].map(a=>({t:a.textContent,h:a.getAttribute('href')})).slice(0,5),
            html: c.innerHTML.slice(0, 2500),
          };
        }""")
        print("=== LIVE DOM SUMMARY ===")
        for k, v in info.items():
            if k == "html":
                continue
            print(f"{k}: {v}")
        with open(OUT + "/live-dom.html", "w", encoding="utf-8") as f:
            f.write(info.get("html", ""))
        pg.screenshot(path=OUT + "/live-current.png", full_page=True)
        print("console errors:", [e for e in errs if not any(s in e for s in ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed"))])
        b.close()


if __name__ == "__main__":
    run()
