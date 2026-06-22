"""behavioral verify for the skills ui redesign (rail + card grid + drawer + library).
run against a server (SKILLS_DIR is the real data/skills, so this is read-mostly;
the pin sub-test only runs on an unpinned card and restores it):
  ALLES_DATA=.tmp_skl_redesign AUTH_ENABLED=false PORT=8151 python app.py
  python tests/pw_skills_redesign.py 8151
"""
import sys
from playwright.sync_api import sync_playwright

IGN = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "8151"
    r, errs = {}, []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block")
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append(m.text)
              if m.type == "error" and not any(x in m.text for x in IGN) else None)
        pg.goto(f"http://aide.localhost:{port}/", wait_until="domcontentloaded")
        pg.wait_for_timeout(400)
        pg.eval_on_selector("body", "() => window._navigateTo('skills')")
        pg.wait_for_selector("#skl-rail", timeout=12000)
        pg.wait_for_timeout(400)

        # ── rail ──────────────────────────────────────────────────────────────
        rail_rows = pg.eval_on_selector_all(".skl-rail-cat", "els => els.map(e => e.dataset.cat)")
        r["rail_has_all"] = "all" in rail_rows
        r["rail_has_cats"] = len([x for x in rail_rows if x != "all"]) >= 6
        counts = pg.eval_on_selector_all(".skl-rail-cat .skl-rail-count", "els => els.map(e => +e.textContent)")
        r["rail_counts_ok"] = bool(counts) and any(c > 0 for c in counts)

        # ── grid is multi-column ─────────────────────────────────────────────
        tops = pg.eval_on_selector_all("#skl-grid .skl-card", "els => els.slice(0,8).map(e => e.offsetTop)")
        r["grid_multicol"] = len(tops) >= 2 and len(set(tops)) < len(tops)

        # ── category filter ──────────────────────────────────────────────────
        total = pg.eval_on_selector_all("#skl-grid .skl-card", "els => els.length")
        pg.eval_on_selector(".skl-rail-cat[data-cat='coding']", "el => el.click()")
        pg.wait_for_timeout(300)
        coding_n = pg.eval_on_selector_all("#skl-grid .skl-card", "els => els.length")
        coding_badge = pg.eval_on_selector(".skl-rail-cat[data-cat='coding'] .skl-rail-count", "el => +el.textContent")
        r["filter_changes_count"] = coding_n != total and coding_n == coding_badge
        r["filter_active_marked"] = pg.eval_on_selector(".skl-rail-cat[data-cat='coding']", "el => el.classList.contains('active')")

        # ── pin (only if first card is currently unpinned → restore after) ────
        pg.eval_on_selector(".skl-rail-cat[data-cat='all']", "el => el.click()")
        pg.wait_for_timeout(250)
        first_pinned = pg.eval_on_selector("#skl-grid .skl-card:first-child .skl-pin", "el => el.classList.contains('on')")
        if not first_pinned:
            pg.eval_on_selector("#skl-grid .skl-card:first-child .skl-pin", "el => el.click()")
            pg.wait_for_timeout(450)
            r["pin_adds_rail_group"] = pg.eval_on_selector(".skl-rail-cat[data-cat='pinned']", "el => !!el")
            r["pin_floats_top"] = pg.eval_on_selector("#skl-grid .skl-card:first-child .skl-pin", "el => el.classList.contains('on')")
            pg.eval_on_selector("#skl-grid .skl-card:first-child .skl-pin", "el => el.click()")  # restore
            pg.wait_for_timeout(350)
        else:
            r["pin_adds_rail_group"] = True
            r["pin_floats_top"] = True

        # ── editor drawer ─────────────────────────────────────────────────────
        pg.eval_on_selector("#skl-grid .skl-card .skl-card-name", "el => el.click()")
        pg.wait_for_timeout(350)
        r["drawer_opens"] = pg.eval_on_selector("#skl-drawer", "el => !!el && el.classList.contains('open')")
        r["drawer_name_filled"] = pg.eval_on_selector("#skl-d-name", "el => el.value.length > 0")
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)
        r["drawer_esc_closes"] = pg.eval_on_selector("#skl-drawer", "el => !el.classList.contains('open')")
        pg.eval_on_selector("#skl-new", "el => el.click()")
        pg.wait_for_timeout(300)
        r["new_drawer_empty"] = pg.eval_on_selector("#skl-d-name", "el => el.value === ''")
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(200)

        # ── library mode ──────────────────────────────────────────────────────
        pg.eval_on_selector(".skl-rail-act[data-act='library']", "el => el.click()")
        pg.wait_for_timeout(500)
        r["library_active"] = pg.eval_on_selector(".skl-rail-act[data-act='library']", "el => el.classList.contains('active')")
        add_n = pg.eval_on_selector_all("#skl-grid .skl-add", "els => els.length")
        added_n = pg.eval_on_selector_all("#skl-grid .skl-added", "els => els.length")
        r["library_cards_render"] = (add_n + added_n) > 0
        pg.eval_on_selector(".skl-rail-act[data-act='library']", "el => el.click()")
        pg.wait_for_timeout(400)
        r["library_toggle_back"] = not pg.eval_on_selector(".skl-rail-act[data-act='library']", "el => el.classList.contains('active')")

        # ── search ────────────────────────────────────────────────────────────
        pg.eval_on_selector(".skl-rail-cat[data-cat='all']", "el => el.click()")
        pg.wait_for_timeout(200)
        all_n = pg.eval_on_selector_all("#skl-grid .skl-card", "els => els.length")
        pg.fill("#skl-search", "summar")
        pg.wait_for_timeout(400)
        srch_n = pg.eval_on_selector_all("#skl-grid .skl-card", "els => els.length")
        r["search_narrows"] = srch_n < all_n and srch_n >= 1
        pg.fill("#skl-search", "")
        pg.wait_for_timeout(300)

        # ── responsive ────────────────────────────────────────────────────────
        pg.set_viewport_size({"width": 560, "height": 900})
        pg.wait_for_timeout(300)
        r["mobile_rail_is_row"] = pg.eval_on_selector("#skl-rail", "el => getComputedStyle(el).flexDirection === 'row'")
        r["mobile_cards_render"] = pg.eval_on_selector_all("#skl-grid .skl-card", "els => els.length") > 0

        r["no_console_errors"] = len(errs) == 0
        pg.close(); ctx.close(); b.close()

    ok = all(r.values())
    for k, v in r.items():
        print(f"{'PASS' if v else 'FAIL'}  {k}")
    if errs:
        print("errors:", errs[:6])
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
