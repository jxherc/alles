"""behavioral verify for the skill ranking surface. data/skills is the real shared
dir, so this is read-only - no installs/deletes, just looks at how rank shows up."""
import sys
from playwright.sync_api import sync_playwright

IGN = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "8153"
    r, errs = {}, []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context(service_workers="block").new_page()
        pg.on("console", lambda m: errs.append(m.text)
              if m.type == "error" and not any(x in m.text for x in IGN) else None)
        pg.goto(f"http://aide.localhost:{port}/", wait_until="domcontentloaded")
        pg.wait_for_timeout(400)
        pg.eval_on_selector("body", "() => window._navigateTo('skills')")
        pg.wait_for_selector("#skl-rail", timeout=12000)
        pg.wait_for_timeout(300)

        # installed grid carries the rank explainer when not searching
        r["rankhint_present"] = pg.eval_on_selector_all(".skl-rankhint", "els => els.length") == 1

        # open the match panel
        pg.eval_on_selector("#skl-match", "el => el.click()")
        pg.wait_for_timeout(300)
        r["match_drawer_opens"] = pg.eval_on_selector("#skl-match-q", "el => !!el && el.offsetParent !== null")

        # type a task -> rows render, first row tagged auto-loaded, a bar has width
        pg.fill("#skl-match-q", "summarize a long article")
        pg.wait_for_timeout(600)
        rows = pg.eval_on_selector_all("#skl-match-results .skl-match-row", "els => els.length")
        r["match_rows_render"] = rows >= 1
        r["first_row_tagged"] = pg.eval_on_selector(
            "#skl-match-results .skl-match-row", "el => !!el.querySelector('.skl-match-auto')")
        r["bar_has_width"] = pg.eval_on_selector_all(
            "#skl-match-results .skl-match-bar span",
            "els => els.some(e => parseFloat(e.style.width) > 0)")
        # soft: the seeded Summarize skill is a natural top pick, but don't hard-fail if
        # something equally valid ranks first
        name = pg.eval_on_selector("#skl-match-results .skl-match-name", "el => el.textContent.toLowerCase()")
        if "summ" not in name:
            print(f"(note: top match was '{name}', not the Summarize skill - still valid)")

        # esc closes the drawer
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)
        r["esc_closes"] = pg.eval_on_selector("#skl-drawer", "el => !el || !el.classList.contains('open')")

        r["no_console_errors"] = len(errs) == 0
        b.close()
    ok = all(r.values())
    for k, v in r.items(): print(f"{'PASS' if v else 'FAIL'}  {k}")
    if errs: print("errors:", errs[:6])
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
