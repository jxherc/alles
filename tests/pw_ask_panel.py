"""The ask-aide panel: opens from any app, sends the screen only when sharing is on, streams the
answer, closes back to where it was opened, hands the session to Aide, and stays off vault and Aide."""

import json
import os
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from pw_aide_questions_real import HOME, _require_throwaway_data_root, api
from pw_aide_task_capture import current_model_turn


class PanelModel(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    questions = []

    def log_message(self, _format, *_args):
        pass

    def do_POST(self):
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self.send_error(404)
            return
        request = json.loads(self.rfile.read(int(self.headers.get("content-length", "0"))))
        turn = current_model_turn(request.get("messages", []))
        question = str(turn[0].get("content", "")) if turn else ""
        if not request.get("stream"):
            payload = json.dumps({"choices": [{"message": {"content": "panel"}}]}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.questions.append(question)
        saw = "renew passport" in question
        content = "**seen**: renew passport is due" if saw else "**blind**: no screen was shared"
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("connection", "close")
        self.end_headers()
        for delta in (content[:8], content[8:], ""):
            event = {
                "choices": [
                    {"delta": {"content": delta}, "finish_reason": None if delta else "stop"}
                ]
            }
            self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def _targets(page):
    small = page.evaluate("""() => [...document.querySelectorAll('#ask-panel button, #ask-panel textarea')]
        .filter(el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden')
        .map(el => { const r = el.getBoundingClientRect(); return [el.id || el.className || el.textContent.trim(), Math.round(r.width), Math.round(r.height)]; })
        .filter(([, w, h]) => w < 44 || h < 44)""")
    assert not small, small


def run():
    _require_throwaway_data_root()
    output = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    output.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), PanelModel)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    records, failures = [], []
    try:
        api("POST", "/api/setup/dismiss", {})
        eid = api(
            "POST",
            "/api/models/endpoint",
            {
                "name": "panel model",
                "base_url": f"http://127.0.0.1:{server.server_port}/v1",
                "provider_adapter": "manual",
            },
        )["id"]
        api("PATCH", f"/api/models/endpoint/{eid}", {"models": ["panel-fixture"]})
        api(
            "PATCH",
            "/api/settings",
            {
                "default_endpoint_id": eid,
                "default_model": "panel-fixture",
                "model_roles": {"aide_chat": {"endpoint_id": eid, "model": "panel-fixture"}},
            },
        )
        api("POST", "/api/tasks", {"title": "renew passport"})
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for width, theme in ((1440, "dark"), (1440, "light"), (390, "dark")):
                label = f"{width}-{theme}"
                record = {"profile": label, "status": "failed"}
                errors = []
                context = browser.new_context(
                    viewport={"width": width, "height": 900},
                    service_workers="block",
                    is_mobile=width < 500,
                    has_touch=width < 500,
                )
                context.request.put(f"{HOME}/api/appearance", data={"preset": theme})
                page = context.new_page()
                page.on("pageerror", lambda exc, errors=errors: errors.append(str(exc)))
                try:
                    PanelModel.questions.clear()
                    page.goto(f"{HOME}/?view=tasks")
                    # no button beside the app name: the panel opens with its shortcut only
                    expect(page.locator("#ask-aide-btn")).to_have_count(0)
                    expect(page.locator("#tasks-list")).to_contain_text("renew passport")
                    page.keyboard.press("Control+.")
                    panel = page.locator("#ask-panel")
                    expect(panel).to_be_visible()
                    expect(page.locator("#ask-panel-input")).to_be_focused()
                    # measure after the slide-in settles
                    page.wait_for_function(
                        "() => !document.getAnimations().some(a => a.playState === 'running')"
                    )
                    expect(page.locator("#ask-panel-where")).to_contain_text("plan")
                    _targets(page)
                    box = panel.bounding_box()
                    if width < 500:
                        assert box["x"] == 0 and round(box["width"]) == width, box
                    else:
                        assert (
                            400 <= box["width"] <= 420 and box["x"] + box["width"] <= width - 7
                        ), box

                    page.fill("#ask-panel-input", "what is due?")
                    page.keyboard.press("Enter")
                    answer = page.locator(".ask-panel-aide").last
                    expect(answer).to_contain_text("renew passport is due")
                    expect(answer.locator("strong")).to_have_text("seen")
                    assert "renew passport" in PanelModel.questions[-1], PanelModel.questions
                    assert "asked from plan" in PanelModel.questions[-1], PanelModel.questions
                    expect(page.locator("#ask-panel-open")).to_be_visible()

                    page.click("#ask-panel-share")
                    expect(page.locator("#ask-panel-share")).to_have_attribute(
                        "aria-pressed", "false"
                    )
                    page.fill("#ask-panel-input", "anything else?")
                    page.keyboard.press("Enter")
                    expect(page.locator(".ask-panel-aide").last).to_contain_text(
                        "no screen was shared"
                    )
                    assert "renew passport" not in PanelModel.questions[-1], PanelModel.questions

                    page.keyboard.press("Escape")
                    expect(panel).to_be_hidden()
                    expect(page.locator("#ask-panel-input")).not_to_be_focused()
                    page.keyboard.press("Control+.")
                    expect(panel).to_be_visible()
                    expect(page.locator(".ask-panel-you")).to_have_count(2)

                    page.click("#ask-panel-open")
                    expect(page.locator("#messages")).to_contain_text("what is due?")
                    expect(page.locator("#messages")).to_contain_text("renew passport is due")

                    page.goto(f"{HOME}/?view=vault")
                    expect(page.locator("#vault-view")).to_be_visible()
                    page.keyboard.press("Control+.")
                    expect(panel).to_have_count(0) if panel.count() == 0 else expect(
                        panel
                    ).to_be_hidden()

                    assert not errors, errors
                    record["status"] = "passed"
                except Exception as exc:
                    record["error"] = str(exc)[:600]
                    failures.append(label)
                    page.screenshot(path=str(output / f"ask-panel-{label}.png"))
                    traceback.print_exc()
                finally:
                    records.append(record)
                    context.close()
            browser.close()
    finally:
        server.shutdown()
    (output / "results.json").write_text(json.dumps(records, indent=1), "utf-8")
    print(json.dumps(records, indent=1))
    assert not failures, failures


if __name__ == "__main__":
    try:
        run()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
