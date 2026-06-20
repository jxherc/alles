"""ui-3j verify — native spellcheck (typo underline) is enabled on both docs editor
surfaces (the CM wysiwyg content + the raw source textarea)."""
import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8871"
BASE = f"http://docs.localhost:{PORT}"


def run():
    fails = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block")
        pg = ctx.new_page()
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#wiki-view", timeout=15000)
        pg.wait_for_timeout(1400)
        pg.evaluate("""() => {
          const el = document.querySelector('.wiki-file[data-path=\"livetest.md\"] .wiki-row-label');
          if (el) el.click();
        }""")
        pg.wait_for_timeout(1000)
        d = pg.evaluate("""() => ({
          cm: document.querySelector('.cm-content')?.getAttribute('spellcheck'),
          src: document.querySelector('#wiki-source')?.getAttribute('spellcheck'),
        })""")

        def ok(name, cond):
            (print(f"PASS {name}") if cond else fails.append(name))

        ok("live wysiwyg surface has spellcheck on", d["cm"] == "true")
        ok("raw source surface has spellcheck on", d["src"] == "true")
        print("attrs:", d)
        b.close()
    if fails:
        print("FAILED:", fails)
        sys.exit(1)
    print("ALL GREEN")


if __name__ == "__main__":
    run()
