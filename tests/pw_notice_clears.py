"""27.54: aide's "saved to ... / open note" notice clears itself. a click on +note keeps focus on
+note (the notice never takes it), the notice goes after its time with the pointer away and focus
left alone, and it waits while the pointer is on it. run through the gate runner."""

import json
import os
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright

WAIT_MS = 9500  # the notice's own time is 8 s

MOUNT = """async () => {
  const { saveAnswerNote } = await import('/static/js/answer_note.js');
  document.querySelector('#gate-reply')?.remove();
  const wrap = document.createElement('div');
  wrap.className = 'ai-wrap';
  wrap.id = 'gate-reply';
  wrap.answerText = 'a reply for the notice gate\\nsecond line';
  wrap.style.cssText = 'position:fixed;left:24px;bottom:260px;z-index:5';
  const button = document.createElement('button');
  button.type = 'button'; button.id = 'gate-note'; button.className = 'btn'; button.textContent = '+note';
  button.addEventListener('click', () => saveAnswerNote(button));
  wrap.append(button);
  document.body.append(wrap);
}"""


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    require_server_ownership(base, os.environ["ALLES_TEST_RUN_ID"])
    out = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        assert pw.request.new_context(base_url=base).post("/api/setup/dismiss").ok
        for name, width, touch in (("desktop", 1440, False), ("phone", 390, True)):
            context = browser.new_context(
                viewport={"width": width, "height": 900}, has_touch=touch, service_workers="block"
            )
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base + "/?view=aide", wait_until="networkidle")
            host = page.locator("#aide-note-recovery")
            expect(host).to_be_attached()
            page.evaluate(MOUNT)
            button = page.locator("#gate-note")

            def activate():
                button.tap() if touch else button.click()

            # 1. a click on +note: the notice shows, focus stays on +note (not on "open note")
            activate()
            expect(host.locator(".note-saved-open")).to_be_visible()
            assert page.evaluate(
                "() => !document.querySelector('#aide-note-recovery').contains(document.activeElement)"
            ), "the notice took focus"
            expect(host.locator("p[role=status]")).to_contain_text("saved to")
            # 2. pointer away, focus left alone: it clears after its time
            if not touch:
                page.mouse.move(2, 2)
            page.wait_for_timeout(WAIT_MS)
            expect(host.locator(".note-saved-open")).to_have_count(0)
            expect(host).to_have_text("")
            # 3. the pointer on the notice holds it, and it clears once the pointer leaves
            if not touch:
                activate()
                expect(host.locator(".note-saved-open")).to_be_visible()
                host.locator("p[role=status]").hover()
                page.wait_for_timeout(WAIT_MS)
                expect(host.locator(".note-saved-open")).to_be_visible()
                page.mouse.move(2, 2)
                page.wait_for_timeout(WAIT_MS)
                expect(host.locator(".note-saved-open")).to_have_count(0)
            assert not errors, errors
            rows.append({"profile": name, "status": "passed"})
            context.close()
        browser.close()
    (out / "notice-clears.json").write_text(json.dumps(rows, indent=1))
    print("notice clears gate passed", rows)


if __name__ == "__main__":
    run()
