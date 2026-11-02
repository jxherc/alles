"""A dropdown opened inside a dialog floats above that dialog and stays fully on screen.

The list lives on the body, so a dialog with a higher layer (the news source editor at 1600,
the files dialogs at 1200) used to cover it. WebKit at desktop and phone, both themes: open
each dropdown with a click, then check its z-index beats every layer above its trigger, that
its first and last options are what the pointer would hit, and that it fits the screen.

  python scripts/run_browser_gates.py --suite kit-rules
"""

from __future__ import annotations

import os
import sys

from browser_gate_safety import require_server_ownership
from playwright.sync_api import sync_playwright
from pw_ui_audit import goto, set_theme

SIZES = {"desktop": (1280, 900), "phone": (390, 844)}

# the list the trigger opened, found by its aria-controls: andromeda's history list wears the
# same class for its look and stays in the page, so the class alone can name the wrong list
PANEL = """trigger => {
  const panel = document.getElementById(trigger.getAttribute('aria-controls') || '');
  if (!panel) return {open: false};
  let layer = 0;
  for (let node = trigger.parentElement; node && node !== document.body; node = node.parentElement) {
    const z = parseInt(getComputedStyle(node).zIndex, 10);
    if (z > layer) layer = z;
  }
  const r = panel.getBoundingClientRect();
  const options = [...panel.querySelectorAll('[role=option]')];
  const hit = option => {
    option.scrollIntoView({block: 'nearest'});
    const o = option.getBoundingClientRect();
    return panel.contains(document.elementFromPoint(o.left + o.width / 2, o.top + o.height / 2));
  };
  return {
    open: true, id: panel.id, layer, z: parseInt(getComputedStyle(panel).zIndex, 10), options: options.length,
    first: options.length ? hit(options[0]) : false,
    last: options.length ? hit(options[options.length - 1]) : false,
    inside: r.left >= 0 && r.top >= 0 && r.right <= innerWidth && r.bottom <= innerHeight,
    expanded: trigger.getAttribute('aria-expanded'),
  };
}"""


def open_news(page, base):
    goto(page, base, "scheduled")
    page.locator('[data-scheduled-tab="news"]').click()
    page.locator("[data-news-action='add-source']").click()
    page.locator(".news-editor").wait_for(state="visible")
    return ["#news-editor-category", "#news-editor-language"]


def open_files(page, base):
    goto(page, base, "files")
    page.locator("#files-add-location").click()
    page.locator("#files-location-dialog").wait_for(state="visible")
    return ["#files-location-kind"]


def main() -> int:
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    fails: list[str] = []
    checked = 0
    with sync_playwright() as pw:
        browser = pw.webkit.launch()
        for theme in ("dark", "light"):
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
                page = ctx.new_page()
                page.set_default_timeout(8000)
                goto(page, base, "home")
                if page.locator("#setup-skip").is_visible():
                    page.locator("#setup-skip").click()
                for opener in (open_news, open_files):
                    for selector in opener(page, base):
                        where = f"{selector} {size} {theme}"
                        trigger = page.locator(selector)
                        trigger.scroll_into_view_if_needed()
                        trigger.click()
                        state = trigger.evaluate(PANEL)
                        checked += 1
                        if not state["open"] or state["expanded"] != "true":
                            fails.append(f"{where}: did not open {state}")
                            continue
                        if state["z"] <= state["layer"]:
                            fails.append(
                                f"{where}: z {state['z']} under its layer {state['layer']}"
                            )
                        if not (state["options"] and state["first"] and state["last"]):
                            fails.append(f"{where}: an option is covered {state}")
                        if not state["inside"]:
                            fails.append(f"{where}: the list leaves the screen {state}")
                        page.keyboard.press("Escape")
                        page.locator(f"#{state['id']}").wait_for(state="detached")
                ctx.close()
        browser.close()
    for fail in fails:
        print("FAIL", fail)
    print(f"dropdown layers: {checked} dropdowns checked, {len(fails)} failures")
    return 1 if fails or not checked else 0


if __name__ == "__main__":
    sys.exit(main())
