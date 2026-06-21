"""habits audit — drive the tracker UI, screenshot states desktop + narrow, capture console."""

import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8914"
OUT = "docs/evidence/habits"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")
URL = f"http://habits.localhost:{PORT}/"


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
        pg.wait_for_selector(".habit-card, .habits-empty", timeout=15000)
        pg.wait_for_timeout(1000)
        pg.screenshot(path=f"{OUT}/01-desktop.png", full_page=True)

        # toggle today on the first habit's week strip
        pg.click('.habit-card .habit-day:last-child')
        pg.wait_for_timeout(900)
        pg.screenshot(path=f"{OUT}/02-after-toggle.png", full_page=True)

        # add a habit through the UI
        pg.click("#habits-add-toggle")
        pg.wait_for_selector(".habit-add", timeout=5000)
        pg.wait_for_timeout(300)
        pg.screenshot(path=f"{OUT}/03-add-form.png", full_page=True)
        add = pg.query_selector(".habit-add")
        add.query_selector('[data-f="name"]').fill("Meditate")
        pg.click('.habit-add [data-act="create"]')
        pg.wait_for_timeout(900)
        pg.screenshot(path=f"{OUT}/04-after-create.png", full_page=True)

        # edit the first habit
        pg.click('.habit-card[data-id] [data-act="edit"]')
        pg.wait_for_selector(".habit-card.editing", timeout=5000)
        pg.wait_for_timeout(300)
        pg.screenshot(path=f"{OUT}/05-edit-form.png", full_page=True)
        pg.click('.habit-card.editing [data-act="cancel"]')
        pg.wait_for_timeout(300)

        # narrow width
        pg.set_viewport_size({"width": 460, "height": 900})
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_selector(".habit-card", timeout=10000)
        pg.wait_for_timeout(800)
        pg.screenshot(path=f"{OUT}/06-narrow.png", full_page=True)

        ctx.close()
        b.close()

    real = clean(errs)
    with open(f"{OUT}/console.log", "w", encoding="utf-8") as f:
        f.write("ALL:\n" + ("\n".join(errs) or "(none)") + "\n\nREAL:\n" + ("\n".join(real) or "(none)"))
    if real:
        print("FAIL — real console errors:", real[:5])
        sys.exit(1)
    print("PASS — habits audit clean, 0 real console errors")


if __name__ == "__main__":
    run()
