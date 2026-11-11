"""Home's two columns hold tomorrow and today without drawing one on the other.

From 8 pm home leads with a tomorrow section above today's schedule. On a wide screen the
schedule is the main column of a grid, and both sections were given the same cell, so their rows
were drawn on top of each other every evening. Nothing caught it because every check ran in the
daytime. This pins the browser clock to 9 pm and to noon, on an iPad, a desktop and a phone, and
checks that no two home sections share any space and that tomorrow sits right above today.
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_gate_safety import require_server_ownership

base = "http://127.0.0.1:" + os.environ["PORT"]
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
out.mkdir(parents=True, exist_ok=True)
ZONE = "America/Toronto"
PROFILES = [
    ("ipad", {"viewport": {"width": 1210, "height": 834}, "has_touch": True}),
    ("desktop", {"viewport": {"width": 1440, "height": 900}}),
    ("phone", {"viewport": {"width": 390, "height": 844}, "has_touch": True, "is_mobile": True}),
]
BOXES = """() => {
  const boxes = [...document.querySelectorAll('#today-sections [data-home-section]')]
    .filter(section => section.getClientRects().length)
    .map(section => {
      const box = section.getBoundingClientRect();
      return { key: section.dataset.homeSection, left: box.left, top: box.top + scrollY,
               right: box.right, bottom: box.bottom + scrollY };
    });
  const shared = [];
  boxes.forEach((a, i) => boxes.slice(i + 1).forEach(b => {
    if (a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1)
      shared.push(a.key + ' and ' + b.key);
  }));
  return { boxes, shared, wide: document.documentElement.scrollWidth > innerWidth };
}"""
rows = []

with sync_playwright() as pw:
    browser = pw.webkit.launch()
    try:
        day = datetime.now(ZoneInfo(ZONE)).replace(minute=0, second=0, microsecond=0)
        setup = browser.new_context(service_workers="block")
        assert setup.request.post(base + "/api/setup/dismiss").ok
        assert setup.request.patch(base + "/api/settings", data={"timezone": ZONE}).ok
        for title, due in (
            ("owned today errand", day.date()),
            ("owned today call", day.date()),
            ("owned tomorrow errand", day.date() + timedelta(days=1)),
            ("owned tomorrow call", day.date() + timedelta(days=1)),
        ):
            assert setup.request.post(
                base + "/api/tasks", data={"title": title, "due_date": due.isoformat()}
            ).ok
        setup.close()
        for label, options in PROFILES:
            for hour in (21, 12):
                row = {
                    "scenario_id": "home.evening-columns",
                    "profile": f"{label}-{hour}h",
                    "status": "failed",
                }
                rows.append(row)
                context = browser.new_context(service_workers="block", timezone_id=ZONE, **options)
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                try:
                    page.clock.set_fixed_time(day.replace(hour=hour))
                    page.goto(base + "/", wait_until="networkidle")
                    today = page.locator('#today-sections [data-home-section="today"]')
                    tomorrow = page.locator('#today-sections [data-home-section="tomorrow"]')
                    expect(today).to_be_visible()
                    expect(today).to_contain_text("owned today errand")
                    if hour >= 20:
                        expect(tomorrow).to_be_visible()
                        expect(tomorrow).to_contain_text("owned tomorrow errand")
                    else:
                        expect(tomorrow).to_have_count(0)
                    found = page.evaluate(BOXES)
                    assert not found["shared"], f"sections drawn on each other: {found['shared']}"
                    assert not found["wide"], "the page scrolls sideways"
                    boxes = {box["key"]: box for box in found["boxes"]}
                    if hour >= 20:
                        upper, lower = boxes["tomorrow"], boxes["today"]
                        assert abs(upper["left"] - lower["left"]) < 1, (upper, lower)
                        assert abs(upper["right"] - lower["right"]) < 1, (upper, lower)
                        # nothing between them but the one gap every pair of sections has
                        assert 0 <= lower["top"] - upper["bottom"] <= 40, (upper, lower)
                    if options["viewport"]["width"] >= 1024:
                        main = boxes["today"]
                        for key, box in boxes.items():
                            if key not in ("today", "tomorrow"):
                                assert box["left"] >= main["right"], (key, box, main)
                    assert not errors, errors
                    page.screenshot(path=str(out / f"home-{label}-{hour}h.png"))
                    row["status"] = "passed"
                    row["detail"] = f"{len(boxes)} sections, none sharing space"
                except Exception as error:
                    row["detail"] = str(error)[:400]
                    page.screenshot(path=str(out / f"home-{label}-{hour}h-failed.png"))
                finally:
                    context.close()
    finally:
        browser.close()

(out / "scenarios.json").write_text(json.dumps(rows, indent=2))
failed = [row for row in rows if row["status"] != "passed"]
print(json.dumps({"status": "failed" if failed else "passed", "scenarios": rows}))
sys.exit(1 if failed else 0)
