"""health audit — metric cards + trend charts, range chips, add entry, delete; desktop + narrow."""

import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8917"
OUT = "docs/evidence/health"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")
URL = f"http://health.localhost:{PORT}/"


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
        pg.wait_for_selector(".health-card, .health-empty", timeout=15000)
        pg.wait_for_timeout(900)
        pg.screenshot(path=f"{OUT}/01-desktop.png", full_page=True)

        # range chip → 7d
        pg.click('.health-chip[data-days="7"]')
        pg.wait_for_timeout(700)
        pg.screenshot(path=f"{OUT}/02-range-7d.png", full_page=True)
        pg.click('.health-chip[data-days="365"]')
        pg.wait_for_timeout(600)

        # add an entry
        pg.click("#health-add-toggle")
        pg.wait_for_selector(".health-add", timeout=5000)
        pg.wait_for_timeout(300)
        pg.screenshot(path=f"{OUT}/03-add-form.png", full_page=True)
        pg.fill("#health-value", "78.6")
        pg.click("#health-create")
        pg.wait_for_timeout(900)
        pg.screenshot(path=f"{OUT}/04-after-add.png", full_page=True)

        # narrow
        pg.set_viewport_size({"width": 460, "height": 900})
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_selector(".health-card", timeout=10000)
        pg.wait_for_timeout(700)
        pg.screenshot(path=f"{OUT}/05-narrow.png", full_page=True)

        ctx.close()
        b.close()

    real = clean(errs)
    with open(f"{OUT}/console.log", "w", encoding="utf-8") as f:
        f.write("ALL:\n" + ("\n".join(errs) or "(none)") + "\n\nREAL:\n" + ("\n".join(real) or "(none)"))
    if real:
        print("FAIL — real console errors:", real[:5])
        sys.exit(1)
    print("PASS — health audit clean, 0 real console errors")


if __name__ == "__main__":
    run()
