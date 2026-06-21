"""watch (uptime/status) audit — drive every control in the UI like a real user,
screenshot every state at desktop + narrow widths, capture console errors."""

import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8912"
OUT = "docs/evidence/watch"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")
URL = f"http://watch.localhost:{PORT}/"


def clean(errs):
    return [e for e in errs if not any(s in e for s in IGNORE)]


def run():
    errs = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block", viewport={"width": 1280, "height": 900})
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda ex: errs.append("PAGEERR:" + str(ex)))

        pg.goto(URL, wait_until="domcontentloaded")
        pg.wait_for_selector(".watch-card, .watch-empty", timeout=15000)
        pg.wait_for_timeout(1200)
        pg.screenshot(path=f"{OUT}/01-desktop.png", full_page=True)

        # open the add form
        pg.click("#watch-add-toggle")
        pg.wait_for_selector(".watch-add", timeout=5000)
        pg.wait_for_timeout(300)
        pg.screenshot(path=f"{OUT}/02-add-form.png", full_page=True)

        # actually create one through the UI
        add = pg.query_selector(".watch-add")
        add.query_selector('[data-f="name"]').fill("UI-made monitor")
        add.query_selector('[data-f="url"]').fill("http://127.0.0.1:1")
        pg.click('.watch-add [data-act="create"]')
        pg.wait_for_timeout(1500)
        pg.screenshot(path=f"{OUT}/03-after-create.png", full_page=True)

        # edit the first card
        pg.click('.watch-card[data-id] [data-act="edit"]')
        pg.wait_for_selector(".watch-card.editing", timeout=5000)
        pg.wait_for_timeout(300)
        pg.screenshot(path=f"{OUT}/04-edit-form.png", full_page=True)
        pg.click('.watch-card.editing [data-act="cancel"]')
        pg.wait_for_timeout(300)

        # check-now on the first card
        pg.click('.watch-card[data-id] [data-act="check"]')
        pg.wait_for_timeout(1500)

        # refresh-all
        pg.click("#watch-refresh-all")
        pg.wait_for_timeout(1500)
        pg.screenshot(path=f"{OUT}/05-after-refresh.png", full_page=True)

        # narrow width (responsive / balance check)
        pg.set_viewport_size({"width": 460, "height": 900})
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_selector(".watch-card", timeout=10000)
        pg.wait_for_timeout(1000)
        pg.screenshot(path=f"{OUT}/06-narrow.png", full_page=True)

        # home grid — confirm the new tile sits in nicely
        pg.set_viewport_size({"width": 1280, "height": 900})
        pg.goto(f"http://localhost:{PORT}/", wait_until="domcontentloaded")
        pg.wait_for_timeout(1500)
        pg.screenshot(path=f"{OUT}/07-home-grid.png", full_page=True)

        ctx.close()
        b.close()

    real = clean(errs)
    with open(f"{OUT}/console.log", "w", encoding="utf-8") as f:
        f.write("ALL console errors (incl. ignored noise):\n")
        f.write("\n".join(errs) or "(none)")
        f.write("\n\nREAL (filtered) errors:\n")
        f.write("\n".join(real) or "(none)")
    if real:
        print("FAIL — real console errors:", real[:4])
        sys.exit(1)
    print("PASS — watch audit clean, 0 real console errors")


if __name__ == "__main__":
    run()
