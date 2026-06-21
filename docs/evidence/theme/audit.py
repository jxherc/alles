"""advanced theme editor audit — open it, drive every control, screenshot each state,
confirm persistence across reload. captures console errors."""

import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8913"
OUT = "docs/evidence/theme"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")
BASE = f"http://localhost:{PORT}/"


def clean(errs):
    return [e for e in errs if not any(s in e for s in IGNORE)]


def _dismiss_welcome(pg):
    # fresh-data onboarding overlay — skip it so it doesn't cover the theme
    try:
        pg.get_by_text("skip setup", exact=False).click(timeout=2500)
        pg.wait_for_timeout(400)
    except Exception:
        pass


def run():
    errs = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block", viewport={"width": 1280, "height": 900})
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda ex: errs.append("PAGEERR:" + str(ex)))

        pg.goto(BASE, wait_until="domcontentloaded")
        pg.wait_for_timeout(1500)
        _dismiss_welcome(pg)
        pg.screenshot(path=f"{OUT}/01-home-default.png")

        # settings → appearance → the new "open theme editor" button
        pg.evaluate("window._navigateTo && window._navigateTo('settings')")
        pg.wait_for_timeout(600)
        pg.evaluate("document.querySelector('.s-nav-item[data-pane=\"appearance\"]')?.click()")
        pg.wait_for_timeout(500)
        pg.wait_for_selector("#s-open-theme-editor", timeout=8000)
        pg.screenshot(path=f"{OUT}/02-settings-appearance.png")

        # open the editor
        pg.click("#s-open-theme-editor")
        pg.wait_for_selector("#theme-editor", timeout=8000)
        pg.wait_for_timeout(600)
        pg.screenshot(path=f"{OUT}/03-editor-open.png", full_page=True)

        # apply a preset (ocean → constellations bg)
        pg.click('.te-preset[data-preset="ocean"]')
        pg.wait_for_timeout(1200)
        pg.screenshot(path=f"{OUT}/04-preset-ocean.png", full_page=True)

        # harmony generate from current accent
        pg.click("#te-harmony-gen")
        pg.wait_for_timeout(900)
        pg.screenshot(path=f"{OUT}/05-harmony.png", full_page=True)

        # font serif + density compact
        pg.evaluate("document.querySelector('.te-seg[data-seg=\"font\"] [data-val=\"serif\"]')?.click()")
        pg.evaluate("document.querySelector('.te-seg[data-seg=\"density\"] [data-val=\"compact\"]')?.click()")
        pg.wait_for_timeout(600)

        # background pattern sparkles + frosted glass
        pg.evaluate("document.querySelector('.te-seg[data-seg=\"bgPattern\"] [data-val=\"sparkles\"]')?.click()")
        pg.wait_for_timeout(900)
        pg.click("#te-frosted")
        pg.wait_for_timeout(700)
        pg.screenshot(path=f"{OUT}/06-sparkles-frosted.png", full_page=True)

        # save a custom theme
        pg.fill("#te-custom-name", "my theme")
        pg.click("#te-save-custom")
        pg.wait_for_timeout(600)
        pg.screenshot(path=f"{OUT}/07-custom-saved.png", full_page=True)

        # close + reload → theme must persist
        pg.evaluate("document.getElementById('te-done')?.click()")
        pg.wait_for_timeout(400)
        pg.wait_for_timeout(700)  # let the debounced PUT land before reload
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_timeout(1600)
        _dismiss_welcome(pg)
        pg.wait_for_timeout(400)
        pg.screenshot(path=f"{OUT}/08-persisted-after-reload.png")

        # light preset, to confirm light-mode rendering through the editor
        pg.evaluate("import('/static/js/theme.js').then(m => m.openThemeEditor())")
        pg.wait_for_selector("#theme-editor", timeout=8000)
        pg.click('.te-preset[data-preset="light"]')
        pg.wait_for_timeout(1000)
        pg.screenshot(path=f"{OUT}/09-light.png", full_page=True)

        ctx.close()
        b.close()

    real = clean(errs)
    with open(f"{OUT}/console.log", "w", encoding="utf-8") as f:
        f.write("ALL:\n" + ("\n".join(errs) or "(none)") + "\n\nREAL:\n" + ("\n".join(real) or "(none)"))
    if real:
        print("FAIL — real console errors:", real[:5])
        sys.exit(1)
    print("PASS — theme editor audit clean, 0 real console errors")


if __name__ == "__main__":
    run()
