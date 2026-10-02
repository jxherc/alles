"""Inbox calendar capture lands on a real Plan calendar layer, with isolated fixtures."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from browser_gate_safety import require_server_ownership
from playwright.sync_api import expect, sync_playwright


class ModelReply(BaseHTTPRequestHandler):
    calls = 0

    def do_POST(self):
        assert self.path == "/v1/chat/completions"
        self.rfile.read(int(self.headers["content-length"]))
        type(self).calls += 1
        event = {
            "found": True,
            "title": "Mail calendar link",
            "start": f"{date.today().isoformat()}T11:00",
            "end": None,
            "location": "",
            "all_day": False,
        }
        chunk = json.dumps({"choices": [{"delta": {"content": json.dumps(event)}}]})
        body = f"data: {chunk}\n\ndata: [DONE]\n\n".encode()
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def run():
    base = f"http://127.0.0.1:{os.environ['PORT']}"
    data = Path(os.environ["ALLES_DATA"]).resolve()
    run_id = os.environ["ALLES_TEST_RUN_ID"]
    assert os.environ.get("ALLES_TEST_DATA") == "1"
    assert os.environ.get("PYTHON_DOTENV_DISABLED") == "1"
    assert (data / ".alles-test-owner").read_text().strip() == run_id
    require_server_ownership(base, run_id)

    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    output.mkdir(parents=True, exist_ok=True)
    model = ThreadingHTTPServer(("127.0.0.1", 0), ModelReply)
    thread = threading.Thread(target=model.serve_forever, daemon=True)
    thread.start()
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from core.database import MailAccount, ModelEndpoint, SessionLocal

        with SessionLocal() as db:
            account = MailAccount(name="Fixture", email="me@example.invalid")
            db.add(account)
            db.add(
                ModelEndpoint(
                    name="local fixture",
                    base_url=f"http://127.0.0.1:{model.server_port}/v1",
                    cached_models=json.dumps(["fixture-model"]),
                    enabled=True,
                )
            )
            db.commit()

        records = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for device, width in (("desktop", 1440), ("phone", 390)):
                    context = browser.new_context(
                        viewport={"width": width, "height": 900},
                        service_workers="block",
                        is_mobile=device == "phone",
                        has_touch=device == "phone",
                        reduced_motion="reduce",
                        timezone_id="UTC",
                    )
                    page = context.new_page()
                    page.set_default_timeout(15000)
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on(
                        "console",
                        lambda message: (
                            errors.append(message.text) if message.type == "error" else None
                        ),
                    )
                    mail = {
                        "uid": "701",
                        "from": "Teammate <teammate@example.invalid>",
                        "to": "me@example.invalid",
                        "subject": "Planning from mail",
                        "text": "Meet today at 11.",
                        "date": date.today().isoformat(),
                        "date_ts": time.time(),
                        "seen": True,
                    }
                    page.route(
                        "**/api/mail/inbox/**",
                        lambda route: route.fulfill(json={"messages": [mail]}),
                    )
                    page.route("**/api/mail/message/**", lambda route: route.fulfill(json=mail))
                    page.route(
                        "**/api/mail/attachments/**",
                        lambda route: route.fulfill(json={"attachments": []}),
                    )
                    page.route(
                        "**/api/mail/seen/**", lambda route: route.fulfill(json={"ok": True})
                    )

                    page.goto(base + "/?view=today", wait_until="networkidle")
                    if page.locator("#setup-skip").is_visible():
                        page.locator("#setup-skip").click()
                    page.goto(base + "/?view=inbox", wait_until="networkidle")
                    page.get_by_role("tab", name="mail", exact=True).click()
                    page.get_by_role("button", name="Planning from mail", exact=True).click()
                    button = page.locator("#mail-to-cal")
                    expect(button).to_be_visible()
                    if device == "desktop":
                        button.focus()
                        with page.expect_response("**/api/mail/extract-event") as captured:
                            button.press("Enter")
                    else:
                        with page.expect_response("**/api/mail/extract-event") as captured:
                            button.click()
                    assert captured.value.ok, captured.value.text()
                    result = captured.value.json()
                    assert result["preview"] is True
                    assert result["candidate"]["end_dt"] == f"{date.today().isoformat()}T12:00:00"
                    expect(page.locator(".capture-review")).to_be_visible()
                    before = context.request.get(base + "/api/calendar").json()
                    with page.expect_response(base + "/api/calendar") as accepted:
                        page.locator("#capture-accept").click()
                    assert accepted.value.ok, accepted.value.text()
                    result = accepted.value.json()
                    expect(page.locator(".capture-status")).to_contain_text("saved in plan")
                    assert (
                        len(context.request.get(base + "/api/calendar").json()) == len(before) + 1
                    )
                    page.locator("#capture-cancel").click()

                    saved = next(
                        row
                        for row in context.request.get(base + "/api/calendar").json()
                        if row["id"] == result["id"]
                    )
                    calendars = context.request.get(base + "/api/calendars").json()
                    assert saved["calendar_id"] == calendars[0]["id"]
                    page.goto(base + "/?view=plan", wait_until="networkidle")
                    page.get_by_role("tab", name="calendar", exact=True).click()
                    chip = page.locator(f'.cal-chip[data-id="{result["id"]}"]')
                    expect(chip).to_be_visible()
                    chip.scroll_into_view_if_needed()
                    page.screenshot(path=str(output / f"{device}-visible.png"), full_page=True)

                    cal_url = base + "/api/calendars/" + saved["calendar_id"]
                    assert context.request.patch(cal_url, data={"visible": False}).ok
                    page.reload(wait_until="networkidle")
                    page.get_by_role("tab", name="calendar", exact=True).click()
                    expect(chip).to_have_count(0)
                    assert context.request.patch(cal_url, data={"visible": True}).ok
                    page.reload(wait_until="networkidle")
                    page.get_by_role("tab", name="calendar", exact=True).click()
                    expect(chip).to_be_visible()
                    assert not errors, errors
                    records.append(
                        {
                            "scenario_id": "inbox.mail-calendar-layer",
                            "feature_id": "inbox.plan-capture",
                            "profile": device,
                            "status": "passed",
                            "detail": "keyboard/pointer capture, saved duration, Plan visibility and layer toggle",
                        }
                    )
                    context.close()
            finally:
                browser.close()
        assert ModelReply.calls == 2, ModelReply.calls
        (output / "scenarios.json").write_text(json.dumps(records, indent=2) + "\n")
    finally:
        model.shutdown()
        model.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    run()
