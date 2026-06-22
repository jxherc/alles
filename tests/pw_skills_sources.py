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

        # back to built-in for the catalog grid
        pg.eval_on_selector(".skl-rail-cat[data-src='builtin']", "el => el.click()")
        pg.wait_for_timeout(500)

        # builtin category sub-filter: rail shows libcat rows, clicking one narrows the grid
        libcats = pg.eval_on_selector_all(".skl-rail-cat[data-libcat]", "els => els.map(e => e.dataset.libcat)")
        r["libcat_filter_present"] = len(libcats) >= 2 and "all" in libcats
        all_n = pg.eval_on_selector_all("#skl-grid .skl-card", "els => els.length")
        # pick a non-'all' category row and click it
        pick = next((c for c in libcats if c != "all"), None)
        if pick:
            pg.eval_on_selector(f".skl-rail-cat[data-libcat='{pick}']", "el => el.click()")
            pg.wait_for_timeout(300)
            cat_n = pg.eval_on_selector_all("#skl-grid .skl-card", "els => els.length")
            r["libcat_narrows"] = 0 < cat_n < all_n
            # search composes with the active category (narrows further or stays within)
            pg.fill("#skl-search", "the")
            pg.wait_for_timeout(400)
            search_n = pg.eval_on_selector_all("#skl-grid .skl-card", "els => els.length")
            r["search_composes_with_cat"] = search_n <= cat_n
            pg.fill("#skl-search", "")
            pg.wait_for_timeout(400)
            # clicking 'all' restores the full grid
            pg.eval_on_selector(".skl-rail-cat[data-libcat='all']", "el => el.click()")
            pg.wait_for_timeout(300)
            restored = pg.eval_on_selector_all("#skl-grid .skl-card", "els => els.length")
            r["libcat_all_restores"] = restored == all_n
        else:
            r["libcat_narrows"] = r["search_composes_with_cat"] = r["libcat_all_restores"] = False

        # github card rendering (network-live -> soft): if a github browse yields cards,
        # check breadcrumb + added/+add render. skip cleanly if offline / no cards.
        if gh:
            pg.eval_on_selector(f".skl-rail-cat[data-src='{gh[0]}']", "el => el.click()")
            pg.wait_for_timeout(2500)
            ncards = pg.eval_on_selector_all("#skl-grid .skl-card[data-kind='github']", "els => els.length")
            if ncards > 0:
                # every github card has either a +add button or an 'added' span
                r["gh_card_has_action"] = pg.eval_on_selector_all(
                    "#skl-grid .skl-card[data-kind='github']",
                    "els => els.every(e => e.querySelector('.skl-add') || e.querySelector('.skl-added'))")
                # breadcrumb shows where present (some skills sit at repo root -> no dir, that's fine)
                r["gh_breadcrumb_renders"] = pg.eval_on_selector_all(
                    "#skl-grid .skl-card-dir", "els => els.every(e => e.textContent.trim().length > 0)")
            else:
                print("(github browse returned no cards - offline? skipping gh render checks)")
            # back to builtin so the trailing checks below run against the catalog
            pg.eval_on_selector(".skl-rail-cat[data-src='builtin']", "el => el.click()")
            pg.wait_for_timeout(500)
        pg.eval_on_selector("#skl-grid .skl-card .skl-card-name", "el => el.click()")
        pg.wait_for_timeout(400)
        r["preview_opens"] = pg.eval_on_selector("#skl-drawer", "el => !!el && el.classList.contains('open')")
        r["preview_has_body"] = pg.eval_on_selector("#skl-drawer .skl-pv-body", "el => !!el && el.textContent.trim().length > 0")
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)
        r["preview_esc_closes"] = pg.eval_on_selector("#skl-drawer", "el => !el || !el.classList.contains('open')")

        r["no_console_errors"] = len(errs) == 0
        b.close()
    ok = all(r.values())
    for k, v in r.items(): print(f"{'PASS' if v else 'FAIL'}  {k}")
    if errs: print("errors:", errs[:6])
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} passed")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
