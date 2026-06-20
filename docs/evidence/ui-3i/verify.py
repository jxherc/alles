"""ui-3i verify — right-click in the docs editor opens a custom (non-native) context
menu with cut/copy/paste, format, headings and AI actions; format applies to the selection."""
import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8871"
BASE = f"http://docs.localhost:{PORT}"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")


def run():
    fails, errs = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block", viewport={"width": 1100, "height": 1000})
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
        pg.evaluate("""() => {
          const v = window._cmEditor.view;
          const i = v.state.doc.toString().indexOf('Some');
          v.dispatch({selection:{anchor:i, head:i+4}}); v.focus();
        }""")
        pg.wait_for_timeout(300)

        def ok(name, cond):
            (print(f"PASS {name}") if cond else fails.append(name))

        pg.click(".cm-content", button="right")
        pg.wait_for_timeout(300)
        menu = pg.query_selector("#docs-ctx")
        ok("custom menu opens", menu is not None)
        if menu:
            txt = menu.inner_text().lower()
            for label in ("cut", "copy", "paste", "bold", "italic", "link", "heading 1", "rewrite", "summarize", "fix grammar"):
                ok(f"menu has '{label}'", label in txt)
            pg.eval_on_selector("#docs-ctx [data-act='bold']", "el => el.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}))")
            pg.wait_for_timeout(400)
            src = pg.evaluate("() => document.querySelector('#wiki-source').value")
            ok("bold wrapped the selection", "**Some**" in src)
            ok("menu closed after action", pg.query_selector("#docs-ctx") is None)

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
