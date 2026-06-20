"""8d UI — CardDAV connect dialog + sync + status + disconnect.
contacts.localhost:8867.  ALLES_DATA=/tmp/alles8d PORT=8867 AUTH_ENABLED=false python app.py
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

CON = "http://contacts.localhost:8867"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "8d"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "Load failed")


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    r = {}
    errs = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context().new_page()
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
            lambda e: errs.append(str(e)) if not any(x in str(e) for x in IGNORE) else None,
        )

        pg.goto(f"{CON}/", wait_until="domcontentloaded")
        pg.wait_for_selector("#contacts-view", timeout=15000)

        # ---- CardDAV button opens the panel ----
        r["carddav_button"] = pg.query_selector("#contacts-carddav-btn") is not None
        pg.eval_on_selector("#contacts-carddav-btn", "el => el.click()")
        pg.wait_for_selector(".carddav-panel", timeout=8000)

        # ---- connect dialog ----
        pg.eval_on_selector("#cdav-connect", "el => el.click()")
        pg.wait_for_selector("#_df_url", timeout=5000)
        r["connect_dialog_opens"] = pg.query_selector("#_df_url") is not None
        nfields = pg.eval_on_selector_all(".dialog-card input", "els => els.length")
        r["dialog_has_fields"] = nfields >= 3

        pg.fill("#_df_url", "http://127.0.0.1:9/dav/addressbook")
        pg.fill("#_df_username", "alice")
        pg.fill("#_df_password", "secret")
        pg.eval_on_selector("#_dy", "el => el.click()")
        pg.wait_for_selector("#cdav-status", timeout=8000)
        # panel re-renders; wait for connected status
        for _ in range(20):
            if "connected as" in (pg.text_content("#cdav-status") or ""):
                break
            pg.wait_for_timeout(250)
        r["connect_saves_status"] = "connected as" in (pg.text_content("#cdav-status") or "")
        r["status_connected_after"] = "alice" in (pg.text_content("#cdav-status") or "")
        pg.screenshot(path=str(EVID / "carddav.png"))

        # ---- sync button runs (bogus server → graceful error result) ----
        pg.eval_on_selector("#cdav-sync", "el => el.click()")
        for _ in range(30):
            txt = pg.text_content("#cdav-result") or ""
            if txt and txt != "syncing…":
                break
            pg.wait_for_timeout(300)
        r["sync_button_calls"] = (
            bool((pg.text_content("#cdav-result") or "").strip())
            and (pg.text_content("#cdav-result") or "").strip() != "syncing…"
        )

        # ---- disconnect clears status ----
        pg.eval_on_selector("#cdav-disconnect", "el => el.click()")
        pg.wait_for_selector("#cdav-status", timeout=8000)
        for _ in range(20):
            if "not connected" in (pg.text_content("#cdav-status") or ""):
                break
            pg.wait_for_timeout(250)
        r["disconnect_clears"] = "not connected" in (pg.text_content("#cdav-status") or "")

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_carddav_8d.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
