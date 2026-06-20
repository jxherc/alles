"""ui-4b verify — mail categories are a Gmail-style left sidebar with unified icons,
toggleable + persisted; switching category still works."""
import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8871"
BASE = f"http://mail.localhost:{PORT}"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")


def run():
    fails, errs = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block", viewport={"width": 1300, "height": 900})
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#mail-sidebar", state="attached", timeout=15000)
        pg.wait_for_timeout(2600)

        def ok(name, cond):
            (print(f"PASS {name}") if cond else fails.append(name))

        d = pg.evaluate("""() => {
          const items = [...document.querySelectorAll('.mail-nav-item')];
          return {
            count: items.length,
            haveIcons: items.every(i => i.querySelector('.mail-nav-ic svg')),
            labels: items.map(i => i.querySelector('.mail-nav-label')?.textContent),
            noOldTabs: !document.querySelector('.mail-tab'),
            inHead: !!document.querySelector('.mail-head .mail-tabs'),
            sidebarInLayout: !!document.querySelector('.mail-layout .mail-sidebar'),
            activeFilter: document.querySelector('.mail-nav-item.active')?.dataset.filter,
          };
        }""")
        ok("9 category rows in the sidebar", d["count"] == 9)
        ok("every row has a unified icon (svg)", d["haveIcons"])
        ok("rows are labelled", "inbox" in d["labels"] and "sent" in d["labels"] and "drafts" in d["labels"])
        ok("old horizontal tabs are gone", d["noOldTabs"] and not d["inHead"])
        ok("sidebar lives in the mail layout (left column)", d["sidebarInLayout"])
        ok("inbox is active by default", d["activeFilter"] == "inbox")

        # switching category sets active
        pg.evaluate("() => document.querySelector(\".mail-nav-item[data-filter='sent']\")?.click()")
        pg.wait_for_timeout(500)
        ok("clicking a category activates it", pg.evaluate("() => document.querySelector('.mail-nav-item.active')?.dataset.filter") == "sent")

        # toggle collapses + persists
        pg.evaluate("() => document.querySelector('#mail-sidebar-toggle')?.click()")
        pg.wait_for_timeout(300)
        collapsed = pg.evaluate("() => document.querySelector('#mail-view').classList.contains('sidebar-collapsed')")
        ok("toggle collapses the sidebar", collapsed)
        ok("collapsed state is persisted", pg.evaluate("() => localStorage.getItem('mail-sidebar-collapsed')") == "1")
        labelHidden = pg.evaluate("() => getComputedStyle(document.querySelector('.mail-nav-label')).display === 'none'")
        ok("labels hide when collapsed (icons only)", labelHidden)

        real = [e for e in errs if not any(s in e for s in IGNORE)]
        ok("no console errors", not real)
        if real:
            print("ERRORS", real)
        pg.evaluate("() => document.querySelector('#mail-sidebar-toggle')?.click()")
        pg.wait_for_timeout(300)
        pg.screenshot(path="docs/evidence/ui-4b/sidebar.png")
        b.close()
    if fails:
        print("\nFAILED:", fails)
        sys.exit(1)
    print("\nALL GREEN")


if __name__ == "__main__":
    run()
