"""3d audit screenshot — docs view on :8825."""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

EVID = Path(r"C:\Users\jxh\alles\docs\evidence\3d")


def main():
    errs = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context().new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto("http://docs.localhost:8825/?doc=notes/python.md", wait_until="domcontentloaded")
        pg.wait_for_timeout(2500)
        pg.screenshot(path=str(EVID / "audit-docs.png"), full_page=True)
        # toolbar buttons present?
        btns = pg.eval_on_selector_all(
            "#wiki-editor-head button, .wiki-toolbar button",
            "els=>els.map(e=>e.id||e.textContent.trim()).filter(Boolean)",
        )
        b.close()
    (EVID / "audit-console.txt").write_text(
        "console errors:\n" + "\n".join(errs[:30]) + f"\n\ntoolbar/head buttons: {btns}",
        encoding="utf-8",
    )
    print("console errors:", len(errs))
    print("buttons:", btns)
    return 0


if __name__ == "__main__":
    sys.exit(main())
