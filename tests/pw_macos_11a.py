"""11a UI — macOS integration status card (tools pane). On this Windows box it honestly reports
unavailable.  aide.localhost:8878.  ALLES_DATA=/tmp/alles11a PORT=8878 AUTH_ENABLED=false python app.py
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

AIDE = "http://aide.localhost:8878"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "11a"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "403", "Load failed")


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

        pg.goto(f"{AIDE}/", wait_until="domcontentloaded")
        pg.wait_for_selector('.nav-item[data-view="settings"]', timeout=15000)
        pg.eval_on_selector('.nav-item[data-view="settings"]', "el => el.click()")
        pg.wait_for_selector('.s-nav-item[data-pane="tools"]', timeout=8000)
        pg.eval_on_selector('.s-nav-item[data-pane="tools"]', "el => el.click()")
        pg.wait_for_selector("#macos-status", timeout=8000)
        pg.wait_for_timeout(600)

        r["macos_card_present"] = pg.query_selector("#macos-status") is not None
        r["card_header_present"] = "macOS integration" in (pg.text_content("#s-pane-tools") or "")
        txt = pg.text_content("#macos-status") or ""
        r["status_fetched"] = len(txt.strip()) > 0
        # status endpoint reachable + reports availability matching the platform
        st = pg.evaluate("() => fetch('/api/macos/status').then(r => r.json())")
        r["status_endpoint_reachable"] = "available" in st
        r["available_matches_platform"] = st["available"] == (sys.platform == "darwin")
        if sys.platform != "darwin":
            r["shows_unavailable_off_darwin"] = "unavailable" in txt.lower()
            r["mentions_mac_mini"] = "mac mini" in txt.lower()
        else:
            r["shows_unavailable_off_darwin"] = "available" in txt.lower()
            r["mentions_mac_mini"] = True
        pg.screenshot(path=str(EVID / "macos-status.png"))

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_macos_11a.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
