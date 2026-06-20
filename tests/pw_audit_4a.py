import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

EVID = Path(r"C:\Users\jxh\alles\docs\evidence\4a")


def main():
    errs = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context().new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto("http://money.localhost:8829/", wait_until="domcontentloaded")
        pg.wait_for_timeout(2500)
        pg.screenshot(path=str(EVID / "audit-money.png"), full_page=True)
        b.close()
    (EVID / "audit-console.txt").write_text(
        "console errors: " + str(len(errs)) + "\n" + "\n".join(errs[:20]), encoding="utf-8"
    )
    print("console errors:", len(errs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
