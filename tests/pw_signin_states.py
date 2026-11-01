"""The sign in component on its test page (static/signin-test.html, served with ALLES_TEST_DATA=1),
against the fake server that answers the /api/signin contract. Every state is reached with real
clicks and keys, then measured: 44px targets, no overlap between controls, text at least role 13,
no sideways scroll, no console errors, both themes, four sizes."""

import json
import os
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

SIZES = [(1280, 900, "dark"), (820, 1180, "light"), (390, 844, "dark"), (390, 844, "light")]
START = "[data-act=start]"
# state -> (steps to reach it, text that shows)
REACH = {
    "idle": ([], "sign in with GitHub"),
    "not-ready": ([], "isn't set up yet"),
    "starting": ([("click", START)], "starting"),
    "waiting": ([("click", START)], "ABCD-EFGH"),
    "redirect": ([("click", START)], "finish signing in on Google"),
    "paste": ([("click", START)], "code from Anthropic"),
    "paste-error": (
        [("click", START), ("fill", "bad-code"), ("press", "Enter")],
        "that code was not accepted",
    ),
    "done": ([("click", START)], "signed in as"),
    "expired": ([("click", START)], "the code ran out"),
    "denied": ([("click", START)], "said no"),
    "error": ([("click", START)], "device flow is disabled"),
    "lost": ([("click", START)], "restarted while you were signing in"),
    "signed-in": ([], "repos and issues"),
    "signed-in-mail": ([], "add another Google account"),
    "needs-sign-in": ([], "needs sign in again"),
    "account-error": ([], "didn't answer"),
}
MEASURE = """() => {
  const host = document.querySelector('#states');
  const controls = [...host.querySelectorAll('button, a[href], input')].filter(e => e.offsetParent !== null);
  const box = e => e.getBoundingClientRect();
  const small = controls.filter(e => box(e).height < 43.5).map(e => e.textContent.trim());
  const overlaps = [];
  for (let i = 0; i < controls.length; i++) for (let j = i + 1; j < controls.length; j++) {
    const a = box(controls[i]), b = box(controls[j]);
    if (Math.min(a.right, b.right) - Math.max(a.left, b.left) > 0.5 && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 0.5) overlaps.push([controls[i].textContent.trim(), controls[j].textContent.trim()]);
  }
  const sizes = [];
  const walker = document.createTreeWalker(host, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) { const n = walker.currentNode, p = n.parentElement; if (n.textContent.trim() && p.offsetParent !== null && !p.closest('.signin-sr') && p.tagName !== 'H2') sizes.push(parseFloat(getComputedStyle(p).fontSize)); }
  return { small, overlaps, minFont: Math.min(...sizes), sideways: document.documentElement.scrollWidth > document.documentElement.clientWidth };
}"""


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    records = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width, height, theme in SIZES:
            context = browser.new_context(
                viewport={"width": width, "height": height},
                service_workers="block",
                is_mobile=width == 390,
                has_touch=width == 390,
            )
            context.add_init_script(f"localStorage.setItem('aide-theme','{theme}')")
            for name, (steps, text) in REACH.items():
                page = context.new_page()
                page.set_default_timeout(10000)
                problems = []
                page.on("pageerror", lambda error: problems.append(str(error)))
                page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)
                page.goto(f"{base}/static/signin-test.html?state={name}&freeze=1")
                page.wait_for_selector("html[data-ready='1'] .signin-provider")
                assert page.evaluate("document.documentElement.dataset.theme || 'dark'") == theme
                for step in steps:
                    if step[0] == "click":
                        page.click(step[1])
                    elif step[0] == "fill":
                        page.fill("input.signin-input", step[1])
                    else:
                        page.keyboard.press(step[1])
                expect(page.locator("#states")).to_contain_text(text)
                found = page.evaluate(MEASURE)
                assert not found["small"], (name, width, found["small"])
                assert not found["overlaps"], (name, width, found["overlaps"])
                assert found["minFont"] >= 13, (name, width, found["minFont"])
                assert not found["sideways"], (name, width)
                assert not problems, (name, problems)
                records.append({"state": name, "width": width, "theme": theme})
                page.close()
            context.close()

        # the keyboard path: Tab reaches the button, Enter starts, the code panel takes focus order
        context = browser.new_context(
            viewport={"width": 1180, "height": 820}, service_workers="block"
        )
        page = context.new_page()
        page.goto(f"{base}/static/signin-test.html?state=waiting&freeze=1")
        page.wait_for_selector("html[data-ready='1'] .signin-provider")
        page.keyboard.press("Tab")
        expect(page.locator(START)).to_be_focused()
        page.keyboard.press("Enter")
        expect(page.locator("[data-code]")).to_contain_text("ABCD-EFGH")
        page.keyboard.press("Tab")
        expect(page.locator("[data-act=copy]")).to_be_focused()
        page.keyboard.press("Tab")
        page.keyboard.press("Tab")
        expect(page.locator("[data-act=cancel]")).to_be_focused()
        page.keyboard.press("Enter")
        expect(page.locator(START)).to_be_visible()
        context.close()
        browser.close()
    (output / "signin-states.json").write_text(json.dumps(records, indent=2))
    print(json.dumps({"status": "passed", "states": len(records)}))


if __name__ == "__main__":
    run()
