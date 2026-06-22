"""behavioral verify for library skill sources. data/skills is the real shared dir,
so this is read-mostly. github sources are network-live (best-effort)."""
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

        # enter library -> rail lists sources incl built-in
        pg.eval_on_selector(".skl-rail-act[data-act='library']", "el => el.click()")
        pg.wait_for_timeout(700)
        src_ids = pg.eval_on_selector_all(".skl-rail-cat", "els => els.map(e => e.dataset.src).filter(Boolean)")
        r["rail_lists_sources"] = "builtin" in src_ids and len(src_ids) >= 3
        # built-in grid renders catalog cards
        r["builtin_cards"] = pg.eval_on_selector_all("#skl-grid .skl-card", "els => els.length") > 5

        # clicking a github source row triggers a browse (cards OR an inline error, both fine)
        gh = [s for s in src_ids if s != "builtin"]
        if gh:
            pg.eval_on_selector(f".skl-rail-cat[data-src='{gh[0]}']", "el => el.click()")
            pg.wait_for_timeout(2500)
            r["github_browse_resolves"] = pg.eval_on_selector(
                "#skl-grid", "el => el.querySelectorAll('.skl-card').length > 0 || el.querySelector('.skl-empty') !== null")
        else:
            r["github_browse_resolves"] = False

        r["no_console_errors"] = len(errs) == 0
        b.close()
    ok = all(r.values())
    for k, v in r.items(): print(f"{'PASS' if v else 'FAIL'}  {k}")
    if errs: print("errors:", errs[:6])
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} passed")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
