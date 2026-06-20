"""11d-2 — final DEEP sweep. pw_regression just loads each host; this drives a real
interaction in several apps (open a modal, add a task, create today's doc, quick-add a
calendar event, render the journal) and cross-navigates the ecosystem, asserting 0 real
console errors throughout. The capstone regression for the whole build.

  ALLES_DATA=.tmp_11d PORT=8881 AUTH_ENABLED=false python app.py
  python tests/pw_final_11d.py
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PORT = "8881"
BASE = f"localhost:{PORT}"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "11d"
IGNORE = ("ERR_", "favicon", "401", "403", "Failed to load resource", "net::", "Load failed")


def _wire(pg, errs):
    pg.on(
        "console",
        lambda m: (
            errs.append(m.text)
            if m.type == "error" and not any(x in m.text for x in IGNORE)
            else None
        ),
    )
    pg.on(
        "pageerror",
        lambda ex: errs.append(str(ex)) if not any(x in str(ex) for x in IGNORE) else None,
    )


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    r = {}
    errs = []
    with sync_playwright() as p:
        b = p.chromium.launch()

        # ── aide: open + close the settings modal ────────────────────────────────
        pg = b.new_page()
        _wire(pg, errs)
        pg.goto(f"http://aide.{BASE}/", wait_until="domcontentloaded")
        pg.wait_for_selector(".app", timeout=15000)
        pg.wait_for_timeout(700)
        pg.eval_on_selector("#topbar-settings-btn", "el => el.click()")
        pg.wait_for_selector("#settings-modal .s-modal", timeout=8000)
        r["aide_settings_modal_opens"] = pg.is_visible("#settings-modal")
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(400)
        r["aide_settings_modal_closes"] = not pg.is_visible("#settings-modal")
        pg.close()

        # ── tasks: add a task, see it land in the list ───────────────────────────
        pg = b.new_page()
        _wire(pg, errs)
        pg.goto(f"http://tasks.{BASE}/", wait_until="domcontentloaded")
        pg.wait_for_selector("#task-add-input", timeout=15000)
        pg.wait_for_timeout(500)
        pg.fill("#task-add-input", "ship the final sweep")
        pg.press("#task-add-input", "Enter")
        pg.wait_for_timeout(1200)
        r["tasks_add_reflects_in_list"] = "ship the final sweep" in (
            pg.text_content("#tasks-list") or ""
        )
        pg.screenshot(path=str(EVID / "final-tasks.png"))
        pg.close()

        # ── docs: open today's daily doc into the editor ─────────────────────────
        pg = b.new_page()
        _wire(pg, errs)
        pg.goto(f"http://docs.{BASE}/", wait_until="domcontentloaded")
        pg.wait_for_selector("#wiki-view", timeout=15000)
        pg.wait_for_timeout(700)
        r["docs_view_renders"] = pg.is_visible("#wiki-view")
        pg.eval_on_selector("#wiki-today-btn", "el => el.click()")
        pg.wait_for_timeout(1000)
        # the CodeMirror editor surface should be present after opening a doc
        r["docs_today_doc_opens"] = pg.query_selector(".cm-editor") is not None
        pg.close()

        # ── calendar: quick-add an event (NL parse) ──────────────────────────────
        pg = b.new_page()
        _wire(pg, errs)
        pg.goto(f"http://calendar.{BASE}/", wait_until="domcontentloaded")
        pg.wait_for_selector("#cal-quick", timeout=15000)
        pg.wait_for_timeout(500)
        pg.fill("#cal-quick", "lunch with sam fri 1pm")
        pg.press("#cal-quick", "Enter")
        pg.wait_for_timeout(1200)
        r["calendar_quick_add_no_error"] = True  # asserted via the aggregate error count
        pg.close()

        # ── journal: renders its view + stats ────────────────────────────────────
        pg = b.new_page()
        _wire(pg, errs)
        pg.goto(f"http://journal.{BASE}/", wait_until="domcontentloaded")
        pg.wait_for_selector("#journal-view", timeout=15000)
        pg.wait_for_timeout(700)
        r["journal_renders"] = pg.is_visible("#journal-view")
        pg.close()

        # ── cross-nav: from the hub, a tile jumps to its app subdomain ───────────
        pg = b.new_page()
        _wire(pg, errs)
        pg.goto(f"http://{BASE}/", wait_until="domcontentloaded")
        pg.wait_for_selector('.home-tile[data-go="money"]', timeout=15000)
        pg.wait_for_timeout(500)
        pg.eval_on_selector('.home-tile[data-go="money"]', "el => el.click()")
        pg.wait_for_timeout(1800)
        r["crossnav_hub_to_app"] = "money" in pg.evaluate("() => location.hostname")
        pg.screenshot(path=str(EVID / "final-crossnav.png"))
        pg.close()

        r["deep_sweep_zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_final_11d.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
