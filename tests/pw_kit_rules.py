"""The kit rules (decisions 0049 to 0051) in WebKit at the owner's four sizes, both themes.

Runs pw_ui_audit's KIT_RULES probe on every route plus the kit page, with seeded rows so the
row and pill checks have something to measure, and screenshots the kit page per profile.
Exits 1 on any failure.

  python scripts/run_browser_gates.py --suite kit-rules
  KIT_ROUTES=kit,settings python tests/pw_kit_rules.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import Error as PWError
from playwright.sync_api import sync_playwright
from pw_ui_audit import KIT_RULES, KIT_THEME, ROUTES, goto, set_theme

SIZES = {
    "desktop": (1280, 900),
    "ipad-landscape": (1180, 820),
    "ipad-portrait": (820, 1180),
    "phone": (390, 844),
}
THEMES = ("dark", "light")


def seed(request, base) -> None:
    # enough rows for a picked row to have neighbors, and a note for the docs rail
    for title in ("renew the passport", "book the dentist", "move the gym to 6pm", "pay rent"):
        request.post(base + "/api/tasks", data={"title": title})
    request.post(
        base + "/api/vault-md/file",
        data={"path": "weekly review.md", "content": "# weekly review\n\n- one\n- two\n"},
    )


def main() -> int:
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    out = Path(os.environ.get("ALLES_BROWSER_ARTIFACTS", "/tmp/alles-kit-rules"))
    out.mkdir(parents=True, exist_ok=True)
    routes = [r for r in (os.environ.get("KIT_ROUTES") or ",".join(ROUTES)).split(",") if r]
    fails: list[dict] = []
    errors: list[str] = []
    started = time.monotonic()
    with sync_playwright() as pw:
        browser = pw.webkit.launch()
        seed(pw.request.new_context(), base)
        for theme in THEMES:
            for size, (width, height) in SIZES.items():
                ctx = browser.new_context(
                    viewport={"width": width, "height": height},
                    has_touch=size != "desktop",
                    locale="en-US",
                    timezone_id="UTC",
                    reduced_motion="reduce",
                    service_workers="block",
                )
                set_theme(ctx.request, base, theme)
                KIT_THEME["now"] = theme
                page = ctx.new_page()
                page.set_default_timeout(8000)
                page.on("dialog", lambda d: d.dismiss())
                # a fresh data folder opens the setup wizard over everything; skip it once
                goto(page, base, "home")
                if page.locator("#setup-skip").is_visible():
                    page.locator("#setup-skip").click()
                for route in routes:
                    where = f"{route} {size} {theme}"
                    try:
                        goto(page, base, route)
                        if route == "kit":
                            page.screenshot(
                                path=str(out / f"kit-{size}-{theme}.png"), full_page=True
                            )
                        page.keyboard.press("Shift")
                        for check, sig, detail in page.evaluate(KIT_RULES):
                            fails.append(
                                {"check": check, "sig": sig, "detail": detail, "where": where}
                            )
                    except PWError as exc:
                        errors.append(f"{where}: {str(exc)[:200]}")
                ctx.close()
        browser.close()
    grouped: dict[str, dict] = {}
    for f in fails:
        g = grouped.setdefault(f"{f['check']} {f['sig']}", {**f, "count": 0, "where": []})
        g["count"] += 1
        if len(g["where"]) < 4:
            g["where"].append(f["where"])
    result = {
        "failures": sorted(grouped.values(), key=lambda g: (g["check"], -g["count"])),
        "errors": errors,
        "routes": routes,
        "seconds": round(time.monotonic() - started, 1),
    }
    (out / "kit-rules.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps({"unique_failures": len(grouped), "errors": len(errors)}, indent=1))
    for g in result["failures"]:
        print(f"  {g['check']}: {g['sig']} ({g['detail']}) x{g['count']} {g['where'][:2]}")
    return 0 if not grouped and not errors else 1


if __name__ == "__main__":
    sys.exit(main())
