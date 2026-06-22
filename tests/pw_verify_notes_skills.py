"""behavioral verify for the notes-in-docs section + skills category grouping.
run against the isolated bughunt server (AUTH off) on :8137.
  ALLES_DATA=.tmp_bughunt_data AUTH_ENABLED=false PORT=8137 python app.py
"""
import sys
from playwright.sync_api import sync_playwright

PORT = 8137
IGN = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")


def main():
    r, errs = {}, []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(service_workers="block")  # SW would re-issue + serve stale
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append(m.text)
              if m.type == "error" and not any(x in m.text for x in IGN) else None)

        # ── docs → notes section ──────────────────────────────────────────────
        pg.goto(f"http://docs.localhost:{PORT}/", wait_until="domcontentloaded")
        pg.wait_for_selector("#wiki-view", timeout=15000)
        pg.eval_on_selector("body", "() => window._navigateTo && window._navigateTo('wiki')")
        pg.wait_for_timeout(500)
        # enter notes from the docs home button
        pg.wait_for_selector("#docs-home-notes", timeout=8000)
        pg.eval_on_selector("#docs-home-notes", "el => el.click()")
        pg.wait_for_timeout(700)

        notes_visible = pg.eval_on_selector(
            "#wiki-notes", "el => !!el && el.offsetParent !== null && el.getBoundingClientRect().height > 0")
        r["notes_board_renders"] = bool(notes_visible)  # the showstopper
        r["notes_list_present"] = pg.eval_on_selector("#notes-list", "el => !!el")
        r["notes_switch_active"] = pg.eval_on_selector(
            ".docs-sec-btn[data-section='notes']", "el => el.classList.contains('active')")
        # the editor toolbar / tabs must NOT bleed into the board
        r["toolbar_hidden_in_notes"] = pg.eval_on_selector(
            "#docs-toolbar", "el => !el || el.offsetParent === null")
        r["tabs_hidden_in_notes"] = pg.eval_on_selector(
            "#wiki-tabs", "el => !el || el.offsetParent === null")
        # new note works + board shows the editor
        pg.eval_on_selector("#note-new-btn", "el => el.click()")
        pg.wait_for_timeout(600)
        r["new_note_opens_editor"] = pg.eval_on_selector_all(
            "#note-edit-title", "els => els.length === 1")

        # ── switch back to docs ───────────────────────────────────────────────
        pg.eval_on_selector(".docs-sec-btn[data-section='docs']", "el => el.click()")
        pg.wait_for_timeout(600)
        r["back_to_docs_clears_notes_mode"] = pg.eval_on_selector(
            "#wiki-view", "el => !el.classList.contains('notes-mode')")
        r["notes_board_hidden_in_docs"] = pg.eval_on_selector(
            "#wiki-notes", "el => el.offsetParent === null")

        # ── skills grouping ───────────────────────────────────────────────────
        pg.goto(f"http://aide.localhost:{PORT}/", wait_until="domcontentloaded")
        pg.wait_for_timeout(400)
        pg.eval_on_selector("body", "() => window._navigateTo('skills')")
        pg.wait_for_selector(".skl-group", timeout=12000)
        pg.wait_for_timeout(500)
        groups = pg.eval_on_selector_all(
            ".skl-group .skl-group-label", "els => els.map(e => e.textContent.trim())")
        r["skills_grouped"] = len(groups) >= 6
        r["skills_has_real_cats"] = any("coding" in g for g in groups) and any("writing" in g for g in groups)
        counts = pg.eval_on_selector_all(".skl-group-count", "els => els.map(e => +e.textContent)")
        r["skills_groups_have_counts"] = bool(counts) and all(c > 0 for c in counts)
        # collapse toggles
        before = pg.eval_on_selector(".skl-group", "el => el.classList.contains('collapsed')")
        pg.eval_on_selector(".skl-group-head", "el => el.click()")
        pg.wait_for_timeout(200)
        after = pg.eval_on_selector(".skl-group", "el => el.classList.contains('collapsed')")
        r["skills_group_collapses"] = before != after

        print("groups:", groups[:20])
        pg.close()
        b.close()

    r["no_console_errors"] = len(errs) == 0
    ok = all(r.values())
    for k, v in r.items():
        print(f"{'PASS' if v else 'FAIL'}  {k}")
    if errs:
        print("errors:", errs[:6])
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
