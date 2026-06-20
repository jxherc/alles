"""post-1a full-app regression — load every subdomain with seeded data, assert
zero real console errors, screenshot each. drives the live isolated server :8811."""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "localhost:8811"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "1a" / "regression"
SUBS = [
    "",  # apex hub
    "aide", "mail", "docs", "gallery", "calendar", "tasks", "subs", "money",
    "days", "journal", "activity", "system", "files", "contacts", "secrets",
]
IGNORE = ("ERR_CONNECTION_CLOSED", "ERR_ABORTED", "ERR_NETWORK_CHANGED", "favicon", "401")


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    rows = []
    ok_all = True
    with sync_playwright() as p:
        b = p.chromium.launch()
        for sub in SUBS:
            host = f"{sub}.{BASE}" if sub else BASE
            pg = b.new_page()
            errs = []
            pg.on("console", lambda m, e=errs: e.append(m.text) if m.type == "error" and not any(x in m.text for x in IGNORE) else None)
            pg.on("pageerror", lambda ex, e=errs: e.append(str(ex)) if not any(x in str(ex) for x in IGNORE) else None)
            try:
                pg.goto(f"http://{host}/", wait_until="domcontentloaded", timeout=20000)
                pg.wait_for_timeout(1800)
                pg.screenshot(path=str(EVID / f"{sub or 'apex'}.png"))
                ok = len(errs) == 0
                ok_all = ok_all and ok
                rows.append(f"{'PASS' if ok else 'FAIL'}  {sub or 'apex':10} errors={len(errs)}" + (f" {errs[:3]}" if errs else ""))
            except Exception as ex:
                ok_all = False
                rows.append(f"FAIL  {sub or 'apex':10} EXCEPTION {ex}")
            pg.close()
        b.close()
    out = "\n".join(rows)
    (EVID.parent / "regression.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{'ALL CLEAN' if ok_all else 'ISSUES FOUND'}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
