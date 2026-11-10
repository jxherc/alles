"""A chat opens on its newest line in WebKit (Safari on an iPad or iPhone).

Opening the chat view hides every view and shows the chat again. On a phone a code block's
header takes its own row through a container query, and WebKit applies that one layout pass
late: it puts a scroller that was hidden back where it was against the shorter first pass, about
51px short for every code block. The last reply ended up under the box and following stopped.
A chat of plain text never showed it, so this one has code blocks. It opens the chat on a phone
and an iPad, checks it sits at its end, shows the chat view again, and checks a chat the owner
scrolled up stays where they left it.
"""

import json
import os
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_gate_safety import require_server_ownership

base = "http://127.0.0.1:" + os.environ["PORT"]
require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
out.mkdir(parents=True, exist_ok=True)
PROFILES = [
    ("phone", {"viewport": {"width": 390, "height": 844}, "has_touch": True, "is_mobile": True}),
    ("ipad", {"viewport": {"width": 1210, "height": 834}, "has_touch": True}),
]
REPLY = (
    "three things:\n\n- one\n- two\n- three\n\n```python\nprint('synthetic')\n```\n\nanything else?"
)
FROM_END = """() => {
  const chat = document.getElementById('chat');
  return Math.round(chat.scrollHeight - chat.scrollTop - chat.clientHeight);
}"""
rows = []

with sync_playwright() as pw:
    browser = pw.webkit.launch()
    try:
        for label, options in PROFILES:
            row = {"scenario_id": "aide.webkit-scroll", "profile": label, "status": "failed"}
            rows.append(row)
            context = browser.new_context(service_workers="block", **options)
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            try:
                assert context.request.post(base + "/api/setup/dismiss").ok
                session = context.request.post(
                    base + "/api/sessions", data={"name": "owned webkit scroll"}
                ).json()["id"]
                history = context.request.get(base + f"/api/sessions/{session}/history").json()
                history["messages"] = [
                    {
                        "id": f"owned-message-{index}",
                        "role": "user" if index % 2 == 0 else "assistant",
                        "content": f"synthetic question {index}" if index % 2 == 0 else REPLY,
                        "meta": {},
                        "timestamp": "2032-11-06T14:30:00Z",
                    }
                    for index in range(12)
                ]
                page.route(
                    base + f"/api/sessions/{session}/history",
                    lambda route: route.fulfill(json=history),
                )
                page.goto(base + "/?view=chat#" + session, wait_until="networkidle")
                expect(page.locator("#messages .msg-row")).to_have_count(12)
                # the bad scroll came about 50ms after the messages; give it time to happen
                page.wait_for_timeout(700)
                opened = page.evaluate(FROM_END)
                assert opened <= 1, f"{label}: the chat opened {opened}px short of its end"
                expect(page.locator("#jump-latest")).to_be_hidden()

                page.evaluate("window._enterChatView()")
                page.wait_for_timeout(400)
                again = page.evaluate(FROM_END)
                assert again <= 1, f"{label}: showing the chat again left it {again}px short"
                expect(page.locator("#jump-latest")).to_be_hidden()

                # the owner reads further up: showing the chat again must not pull them down.
                # not the very top: a chat sitting at exactly 0 is taken for one that was never
                # scrolled and is sent to its end (aidecentral.js)
                page.evaluate("document.getElementById('chat').scrollTop = 160")
                page.wait_for_timeout(200)
                expect(page.locator("#jump-latest")).to_be_visible()
                page.evaluate("window._enterChatView()")
                page.wait_for_timeout(400)
                away = page.evaluate(FROM_END)
                assert away > 96, f"{label}: a chat scrolled up was pulled to {away}px from its end"
                expect(page.locator("#jump-latest")).to_be_visible()
                assert not errors, errors
                row.update(status="passed", opened=opened, again=again, away=away)
            finally:
                context.close()
    finally:
        browser.close()
        (out / "scenarios.json").write_text(json.dumps(rows, indent=2))

failed = [row for row in rows if row["status"] != "passed"]
if failed:
    raise SystemExit(json.dumps(failed, indent=2))
print(json.dumps({"status": "passed", "scenarios": rows}))
